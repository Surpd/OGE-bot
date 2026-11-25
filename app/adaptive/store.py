"""Owner-scoped incremental projection and controlled rebuild from the training archive."""

import json
from dataclasses import asdict
from datetime import datetime
from typing import Any
from uuid import UUID

import asyncpg

from app.adaptive.engine import CURRENT, Evidence, State, apply, apply_written
from app.adaptive.sources import item


def restore(raw: str) -> State:
    data = json.loads(raw)
    data["errors"] = tuple(tuple(e) for e in data["errors"])
    return State(**data)


_ARCHIVE = """
SELECT user_id owner,'ordinary' source,id::text task FROM issued_problems
UNION ALL SELECT s.user_id,'mixed',p.id::text FROM mixed_training_problems p
 JOIN mixed_training_sessions s ON s.id=p.session_id
UNION ALL SELECT s.user_id,'scenario',s.id::text||':'||p.position FROM oge15_question_progress p
 JOIN oge15_sessions s ON s.id=p.session_id WHERE p.status<>'pending'
UNION ALL SELECT u.id,'written',i.id::text FROM part2_issues i
 JOIN users u ON u.telegram_user_id=i.owner
UNION ALL SELECT user_id,'replay',id::text FROM training_error_replays
"""


async def sync(
    conn: asyncpg.Connection, owner: UUID, *, rebuild: bool = False
) -> list[tuple[str, str]]:
    # Readers serialize per learner; writes to source rows never acquire this lock.
    await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended($1,294))", str(owner))
    if rebuild:
        for table in ("adaptive_evidence", "adaptive_skills"):
            await conn.execute(f"DELETE FROM {table} WHERE owner=$1", owner)
        await conn.execute(
            "INSERT INTO adaptive_dirty SELECT * FROM ("
            + _ARCHIVE
            + ") a WHERE owner=$1 ON CONFLICT DO NOTHING",
            owner,
        )
    dirty = await conn.fetch(
        "DELETE FROM adaptive_dirty WHERE owner=$1 RETURNING source,task", owner
    )
    touched: dict[str, datetime] = {}
    if not rebuild:
        for old in await conn.fetch(
            "SELECT skill,latest FROM adaptive_skills WHERE owner=$1 AND policy<>$2",
            owner,
            CURRENT.version,
        ):
            touched[old["skill"]] = old["latest"]
    for key in dirty:
        result = await item(conn, owner, key["source"], key["task"])
        if result is None:
            continue
        for f in result.facts:
            added = await conn.fetchval(
                """INSERT INTO adaptive_evidence(owner,skill,number,source,task,ordinal,
                   variant,occurred,outcome,assisted,attempt,score,grade_status,used_hint,solution_before)
                   VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)
                   ON CONFLICT DO NOTHING RETURNING true""",
                owner,
                result.skill,
                result.number,
                result.source,
                result.task,
                f.ordinal,
                result.variant,
                f.at,
                f.outcome,
                f.assisted,
                f.attempt,
                f.score,
                f.grade_status,
                f.used_hint,
                f.solution_before,
            )
            if added:
                touched[result.skill] = min(touched.get(result.skill, f.at), f.at)
    milestones = []
    for skill, earliest in touched.items():
        milestones.extend(await _project(conn, owner, skill, earliest))
    return milestones


async def _project(
    conn: asyncpg.Connection, owner: UUID, skill: str, earliest: datetime
) -> list[tuple[str, str]]:
    saved = await conn.fetchrow(
        "SELECT * FROM adaptive_skills WHERE owner=$1 AND skill=$2", owner, skill
    )
    incremental = saved and saved["policy"] == CURRENT.version and earliest > saved["latest"]
    after = saved["latest"] if incremental else None
    state = restore(saved["state"]) if incremental else State()
    rows = await conn.fetch(
        """SELECT e.*, issued.occurred AS issued_at, NOT EXISTS(SELECT FROM adaptive_evidence prev
           WHERE prev.owner=e.owner
           AND (prev.skill=e.skill OR e.number=19 AND prev.number=19)
           AND prev.variant=e.variant AND prev.outcome='issued'
           AND (prev.source,prev.task)<>(e.source,e.task)
           AND prev.occurred<=e.occurred)
           AND issued.task IS NOT NULL AS fresh
           FROM adaptive_evidence e LEFT JOIN adaptive_evidence issued
           ON (issued.owner,issued.source,issued.task,issued.ordinal)=(e.owner,e.source,e.task,0)
           WHERE e.owner=$1 AND e.skill=$2 AND ($3::timestamptz IS NULL OR e.occurred>$3)
           ORDER BY e.occurred,e.source,e.task,e.ordinal""",
        owner,
        skill,
        after,
    )
    milestones = []
    updates = []
    for row in rows:
        evidence = Evidence(
            row["source"] + ":" + row["task"],
            row["variant"],
            row["occurred"].timestamp(),
            "ambiguous" if skill == "OGE19-MIXED" and row["outcome"] == "wrong" else row["outcome"],
            row["attempt"],
            row["assisted"],
            row["fresh"],
            row["issued_at"].timestamp() if row["issued_at"] else None,
        )
        state, reason = (apply_written if row["number"] >= 20 else apply)(state, evidence)
        if reason and row["policy"] is None:
            milestones.append((skill, reason))
        updates.append(
            (
                owner,
                row["source"],
                row["task"],
                row["ordinal"],
                reason,
                state.stage,
                CURRENT.version,
            )
        )
    await conn.executemany(
        """UPDATE adaptive_evidence SET reason=$5,stage_after=$6,policy=$7
        WHERE owner=$1 AND source=$2 AND task=$3 AND ordinal=$4""",
        updates,
    )
    await conn.execute(
        """INSERT INTO adaptive_skills(owner,skill,number,state,latest,policy)
        VALUES($1,$2,$3,$4,$5,$6) ON CONFLICT(owner,skill) DO UPDATE SET
        state=excluded.state,latest=excluded.latest,policy=excluded.policy""",
        owner,
        skill,
        rows[-1]["number"],
        json.dumps(asdict(state)),
        rows[-1]["occurred"],
        CURRENT.version,
    )

    return milestones


async def overview(repository: Any, learner: int) -> list[tuple[int, str, State, datetime]]:
    pool = getattr(repository, "_pool", None)
    if pool is None:
        return []
    async with pool.acquire() as conn, conn.transaction():
        row = await conn.fetchrow(
            """SELECT id,EXISTS(SELECT FROM adaptive_dirty d WHERE d.owner=u.id)
            OR EXISTS(SELECT FROM adaptive_skills s WHERE s.owner=u.id AND policy<>$2) pending
            FROM users u WHERE u.telegram_user_id=$1""",
            learner,
            CURRENT.version,
        )
        if not row:
            return []
        if row["pending"]:
            await sync(conn, row["id"])
        rows = await conn.fetch(
            """SELECT number,skill,state,latest FROM adaptive_skills
            WHERE owner=$1 ORDER BY latest DESC,skill""",
            row["id"],
        )
        return [(r["number"], r["skill"], restore(r["state"]), r["latest"]) for r in rows]


async def menu_available(repository: Any, learner: int) -> bool:
    pool = getattr(repository, "_pool", None)
    if pool is None:
        return False
    row = await pool.fetchrow(
        """SELECT EXISTS(SELECT FROM adaptive_dirty WHERE owner=u.id)
        OR EXISTS(SELECT FROM adaptive_skills WHERE owner=u.id AND policy<>$2) pending,
        EXISTS(SELECT FROM adaptive_sessions WHERE owner=u.id AND finished IS NULL)
        OR EXISTS(SELECT FROM adaptive_skills WHERE owner=u.id AND number BETWEEN 1 AND 19
            AND policy=$2 AND state->>'stage'<>'unchecked') AS available
        FROM users u WHERE telegram_user_id=$1
        AND preferences->>'personal_training' IS DISTINCT FROM 'false'""",
        learner,
        CURRENT.version,
    )
    if row and row["pending"] and not row["available"]:
        from app.adaptive.planner import unlocked

        return unlocked(await overview(repository, learner))
    return bool(row and row["available"])
