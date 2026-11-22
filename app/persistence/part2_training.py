"""Owner-scoped, version-pinned bank issuance and append-only student work."""

import json
from functools import cache
from typing import Any, Literal

import asyncpg

from app.persistence.part2_bank import ATLAS


@cache
def _rotation_groups(number: int) -> str:
    catalog = json.loads((ATLAS / "rotation.json").read_text())
    active_groups = {
        group["id"]
        for subtype, groups in catalog.items()
        if subtype.startswith(f"OGE{number}-")
        for group in groups
    }
    profiles = {
        task: [group["id"], group["additional_step"], group["method"]]
        for groups in catalog.values()
        for group in groups
        if group["id"] in active_groups
        for task in (*group["cards"], *group.get("historical_versions", []))
    }
    return json.dumps(profiles)


class Part2Training:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool

    async def choices(self, number: int, owner: int) -> list[asyncpg.Record]:
        return list(
            await self.pool.fetch(
                """SELECT s.subtype_id,s.title,count(*) total,
                count(*) FILTER(WHERE NOT EXISTS(
                    SELECT 1 FROM part2_issues i WHERE i.owner=$2 AND i.task_id=v.task_id
                )) unseen
                FROM part2_subtypes s JOIN part2_cards c USING(subtype_id)
                JOIN part2_versions v USING(task_id) JOIN part2_families f USING(family_id)
                WHERE f.number=$1 AND v.available GROUP BY s.subtype_id,s.title
                ORDER BY s.title,s.subtype_id""",
                number,
                owner,
            )
        )

    async def unfinished(self, owner: int, number: int) -> list[asyncpg.Record]:
        return list(
            await self.pool.fetch(
                """SELECT i.id,s.title,i.solution_viewed_at,i.touched_at,
                v.payload->>'statement' AS statement,
                EXISTS(SELECT FROM part2_work w WHERE w.issue_id=i.id
                    AND w.revision=i.revision AND NOT superseded) AS draft
            FROM part2_issues i JOIN part2_subtypes s USING(subtype_id)
            JOIN part2_versions v USING(task_id,version)
            WHERE owner=$1 AND number=$2 AND NOT closed
            ORDER BY touched_at DESC,id DESC""",
                owner,
                number,
            )
        )

    async def show_intro(self, owner: int) -> bool:
        return bool(
            await self.pool.fetchval(
                """UPDATE users SET part2_intro_seen=true WHERE telegram_user_id=$1
            AND NOT part2_intro_seen RETURNING true""",
                owner,
            )
        )

    async def open(
        self,
        owner: int,
        number: int,
        subtype: str | None = None,
        *,
        repeat: Literal["errors", "skipped", "all"] | None = None,
    ) -> int | None:
        async with self.pool.acquire() as conn, conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock($1)", owner)
            card = await conn.fetchrow(
                """WITH history AS MATERIALIZED (
                    SELECT i.id,i.task_id,i.subtype_id,i.closed,i.skipped_at,
                        COALESCE($5::jsonb->(i.task_id || '@' || i.version),
                                 $5::jsonb->i.task_id) AS profile,
                        s.family_id
                    FROM part2_issues i JOIN part2_subtypes s USING(subtype_id)
                    WHERE owner=$1 AND number=$2
                ), latest AS (
                    SELECT coalesce($5::jsonb->(i.task_id || '@' || i.version),
                                    $5::jsonb->i.task_id)->>0 AS construction
                    FROM part2_issues i WHERE owner=$1 ORDER BY id DESC LIMIT 1
                ), recency AS MATERIALIZED (
                    SELECT kind, value, max(id) AS last_id FROM history h
                    CROSS JOIN LATERAL (VALUES
                        ('task', h.task_id), ('subtype', h.subtype_id), ('family', h.family_id),
                        ('group', h.profile->>0), ('extra', h.profile->>1),
                        ('method', h.profile->>2)
                    ) dimensions(kind,value)
                    GROUP BY kind,value
                ), candidates AS (
                    SELECT task_id,v.version,subtype_id,f.family_id,
                        $5::jsonb->task_id AS profile
                    FROM part2_versions v
                    JOIN part2_cards c USING(task_id) JOIN part2_subtypes s USING(subtype_id)
                    JOIN part2_families f USING(family_id)
                    WHERE v.available AND f.number=$2 AND ($3::text IS NULL OR subtype_id=$3)
                ), unseen AS (
                    SELECT * FROM candidates c WHERE NOT EXISTS(
                        SELECT 1 FROM history h WHERE h.task_id=c.task_id
                    )
                ), majority AS (
                    SELECT profile->>0 AS construction FROM unseen
                    WHERE $3::text IS NOT NULL GROUP BY profile->>0
                    HAVING 2*count(*) > (SELECT count(*) FROM unseen)
                )
                SELECT c.task_id,c.version,c.subtype_id
                FROM candidates c
                LEFT JOIN recency t ON t.kind='task' AND t.value=c.task_id
                LEFT JOIN recency s ON s.kind='subtype' AND s.value=c.subtype_id
                LEFT JOIN recency f ON f.kind='family' AND f.value=c.family_id
                LEFT JOIN recency g ON g.kind='group' AND g.value=c.profile->>0
                LEFT JOIN recency e ON e.kind='extra' AND e.value=c.profile->>1
                LEFT JOIN recency m ON m.kind='method' AND m.value=c.profile->>2
                WHERE
                  ($4::text IS NULL AND EXISTS(SELECT FROM unseen u WHERE u.task_id=c.task_id))
                  OR ($4 IS NOT NULL AND NOT EXISTS(SELECT FROM unseen) AND EXISTS(
                    SELECT FROM history h WHERE h.task_id=c.task_id AND
                    ($4='all' OR $4='skipped' AND h.skipped_at IS NOT NULL OR $4='errors'
                      AND EXISTS(SELECT FROM part2_grades g WHERE g.issue_id=h.id AND g.score<2))
                  ) AND NOT EXISTS(
                    SELECT FROM history h WHERE h.task_id=c.task_id AND NOT h.closed
                  ))
                ORDER BY CASE WHEN $4 IS NOT NULL THEN t.last_id END NULLS FIRST,
                  COALESCE(c.profile->>0=(SELECT construction FROM latest),false),
                  s.last_id NULLS FIRST,
                  COALESCE(c.profile->>0 <> (SELECT construction FROM majority),false),
                  g.last_id NULLS FIRST, f.last_id NULLS FIRST,
                  m.last_id NULLS FIRST, e.last_id NULLS FIRST, md5(c.task_id || $1::bigint::text),
                  c.task_id
                LIMIT 1""",
                owner,
                number,
                subtype,
                repeat,
                _rotation_groups(number),
            )
            if card is None:
                return None
            return int(
                await conn.fetchval(
                    """INSERT INTO part2_issues(owner,number,task_id,version,subtype_id,repeat_kind)
                VALUES ($1,$2,$3,$4,$5,$6) RETURNING id""",
                    owner,
                    number,
                    *card.values(),
                    repeat,
                )
            )

    async def skip(self, owner: int, issue: int, revision: int) -> bool:
        async with self.pool.acquire() as conn, conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock($1)", owner)
            return bool(
                await conn.fetchval(
                    """UPDATE part2_issues SET closed=true,skipped_at=now()
                WHERE owner=$1 AND id=$2 AND NOT closed AND revision=$3
                AND solution_viewed_at IS NULL AND NOT EXISTS(
                    SELECT FROM part2_grades g WHERE g.issue_id=$2
                    AND (g.score IS NOT NULL OR g.status='pending')
                ) RETURNING true""",
                    owner,
                    issue,
                    revision,
                )
            )

    async def finish(self, owner: int, issue: int) -> bool:
        async with self.pool.acquire() as conn, conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock($1)", owner)
            return bool(
                await conn.fetchval(
                    """UPDATE part2_issues i SET closed=true
                WHERE i.owner=$1 AND i.id=$2 AND NOT i.closed
                AND (i.solution_viewed_at IS NOT NULL OR EXISTS(
                    SELECT FROM part2_grades g WHERE g.issue_id=i.id AND g.score IS NOT NULL
                )) RETURNING true""",
                    owner,
                    issue,
                )
            )

    async def current(
        self, owner: int, issue: int | None = None, *, activate: bool = False
    ) -> dict[str, Any] | None:
        async with self.pool.acquire() as conn, conn.transaction():
            if activate:
                await conn.execute("SELECT pg_advisory_xact_lock($1)", owner)
                await conn.execute(
                    """UPDATE part2_issues SET touched_at=clock_timestamp()
                    WHERE owner=$1 AND id=$2 AND NOT closed""",
                    owner,
                    issue,
                )
            row = await conn.fetchrow(
                """SELECT i.*,v.payload,v.reviewed,s.title,
                EXISTS(SELECT FROM part2_work w WHERE w.issue_id=i.id AND w.revision=i.revision
                    AND NOT superseded) AS draft,
                EXISTS(SELECT FROM part2_grades g WHERE g.issue_id=i.id AND g.score IS NOT NULL)
                    AS scored,
                (SELECT message_id FROM part2_work w WHERE w.issue_id=i.id
                 AND w.revision=i.revision AND NOT superseded AND w.photo IS NOT NULL
                 ORDER BY message_id DESC LIMIT 1) AS photo_message
                FROM part2_issues i JOIN part2_versions v USING(task_id,version)
                JOIN part2_subtypes s ON s.subtype_id=i.subtype_id
                WHERE owner=$1 AND NOT closed AND ($2::bigint IS NULL OR i.id=$2)
                ORDER BY touched_at DESC,id DESC LIMIT 1""",
                owner,
                issue,
            )
        return {**row, "card": json.loads(row["payload"])} if row else None

    async def bind_prompt(self, owner: int, issue: int, message: int) -> None:
        await self.pool.execute(
            "UPDATE part2_issues SET prompt_message_id=$3 WHERE owner=$1 AND id=$2 AND NOT closed",
            owner,
            issue,
            message,
        )

    async def remove_photo(self, owner: int, issue: int, revision: int, message: int) -> bool:
        async with self.pool.acquire() as conn, conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock($1)", owner)
            current = await conn.fetchval(
                """SELECT id FROM part2_issues WHERE owner=$1 AND id=$2 AND NOT closed
                AND revision=$3 AND solution_viewed_at IS NULL
                AND id=(SELECT id FROM part2_issues WHERE owner=$1 AND NOT closed
                        ORDER BY touched_at DESC,id DESC LIMIT 1) FOR UPDATE""",
                owner,
                issue,
                revision,
            )
            if not current:
                return False
            return bool(
                await conn.fetchval(
                    """UPDATE part2_work SET superseded=true,photo=NULL,body=NULL
                WHERE issue_id=$1 AND revision=$2 AND message_id=$3
                AND NOT superseded AND photo IS NOT NULL RETURNING true""",
                    issue,
                    revision,
                    message,
                )
            )

    async def append(
        self,
        owner: int,
        issue: int,
        revision: int,
        message: int,
        body: str | None,
        photo: str | None,
        media_group: str | None = None,
        *,
        replace_photo: int | None = None,
        condition_message: int | None = None,
    ) -> Literal["saved", "duplicate", "photo_limit", "stale"]:
        if media_group:
            return "stale"
        if not body and not photo:
            return "stale"
        async with self.pool.acquire() as conn, conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock($1)", owner)
            row = await conn.fetchval(
                """SELECT id FROM part2_issues WHERE owner=$1 AND id=$2 AND NOT closed
                AND revision=$3 AND solution_viewed_at IS NULL
                AND ($4::bigint IS NULL OR prompt_message_id=$4)
                AND id=(SELECT id FROM part2_issues WHERE owner=$1 AND NOT closed
                        ORDER BY touched_at DESC,id DESC LIMIT 1) FOR UPDATE""",
                owner,
                issue,
                revision,
                condition_message,
            )
            if not row:
                return "stale"
            if await conn.fetchval(
                """SELECT EXISTS(SELECT 1 FROM part2_work w JOIN part2_issues i ON i.id=w.issue_id
                   WHERE i.owner=$1 AND w.message_id=$2)""",
                owner,
                message,
            ):
                return "duplicate"
            work = await conn.fetch(
                """SELECT message_id,photo FROM part2_work
                WHERE issue_id=$1 AND revision=$2 AND NOT superseded""",
                issue,
                revision,
            )
            replacing = bool(
                photo
                and any(item["photo"] and item["message_id"] == replace_photo for item in work)
            )
            if photo and replace_photo is not None and not replacing:
                return "stale"
            if photo and not replacing and any(item["photo"] for item in work):
                # Remember the rejected message without retaining student content.
                # A delayed redelivery must not become the first photo of the next draft.
                await conn.execute(
                    """INSERT INTO part2_work(issue_id,revision,message_id,media_group,superseded)
                    VALUES ($1,$2,$3,$4,true)""",
                    issue,
                    revision,
                    message,
                    media_group,
                )
                return "photo_limit"
            if len(work) >= 12 and not replacing:
                return "stale"
            if replacing:
                # Only this open draft is changed. Standalone text and past revisions survive.
                await conn.execute(
                    """UPDATE part2_work SET superseded=true, photo=NULL, body=NULL
                    WHERE issue_id=$1 AND revision=$2 AND photo IS NOT NULL""",
                    issue,
                    revision,
                )
            await conn.execute(
                """INSERT INTO part2_work(issue_id,revision,message_id,body,photo,media_group)
                VALUES ($1,$2,$3,$4,$5,$6)""",
                issue,
                revision,
                message,
                body,
                photo,
                media_group,
            )
            return "saved"
