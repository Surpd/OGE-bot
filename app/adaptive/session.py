"""Training sessions use ordinary issued problems and attempts."""

import json
from random import Random
from typing import Any
from uuid import UUID

import asyncpg

from app.adaptive.mixed_rotation import preview_plan, reserve_number

OPEN_PRACTICE = {"number", "family"}
BLOCK_SIZE = 5


def at_checkpoint(row: Any) -> bool:
    return (
        row.get("strategy") in OPEN_PRACTICE
        and row["problem"] is not None
        and row["outcome"] != "issued"
        and row["position"] + 1 == len(json.loads(row["plan"]))
    )


class Session:
    def __init__(self, repository: Any, learner: int) -> None:
        self.pool: asyncpg.Pool = repository._pool
        self.learner = learner
        self.bot_id: int = getattr(repository, "bot_id", 0)

    async def start(
        self,
        skills: list[str],
        *,
        strategy: str = "personal",
        scope: dict[str, Any] | None = None,
        mixed_catalog: dict[str, int] | None = None,
    ) -> None:
        if strategy not in {"personal", "mixed", "number", "family"}:
            raise ValueError("unknown short-training strategy")
        if skills and len(skills) != BLOCK_SIZE:
            raise ValueError("a training block must contain exactly five positions")
        scope = scope or {}
        if strategy == "number" and not isinstance(scope.get("number"), int):
            raise ValueError("number strategy requires scope.number")
        if strategy == "family" and not isinstance(scope.get("family"), str):
            raise ValueError("family strategy requires scope.family")
        async with self.pool.acquire() as conn, conn.transaction():
            user = await conn.fetchrow(
                "SELECT id,current_state FROM users WHERE telegram_user_id=$1 FOR UPDATE",
                self.learner,
            )
            owner = user["id"]
            state = user["current_state"] or {}
            if isinstance(state, str):
                state = json.loads(state)
            fallback = state.get("resume_mode")
            if strategy == "mixed" and mixed_catalog:
                previous_rotation = await conn.fetchval(
                    """SELECT scope->'mixed_rotation' FROM adaptive_sessions
                       WHERE owner=$1 AND strategy='mixed' AND scope ? 'mixed_rotation'
                       ORDER BY finished DESC NULLS FIRST,id DESC LIMIT 1""",
                    owner,
                )
                rotation = (
                    json.loads(previous_rotation) if previous_rotation
                    else {"seed": str(scope["plan_seed"])}
                )
                scope = {**scope, "mixed_rotation": rotation, "mixed_batch": []}
                skills = preview_plan(mixed_catalog, rotation, BLOCK_SIZE)
            if skills:
                if fallback and fallback != "adaptive":
                    scope["resume_fallback"] = fallback
                await conn.execute(
                    """INSERT INTO adaptive_sessions(owner,plan,strategy,scope)
                    VALUES($1,$2,$3,$4)
                    ON CONFLICT(owner) WHERE finished IS NULL DO NOTHING""",
                    owner,
                    json.dumps(skills),
                    strategy,
                    json.dumps(scope),
                )
            elif fallback and fallback != "adaptive":
                await conn.execute(
                    """UPDATE adaptive_sessions SET scope=scope ||
                    jsonb_build_object('resume_fallback',$2::text)
                    WHERE owner=$1 AND finished IS NULL""",
                    owner, fallback,
                )
            await conn.execute(
                """UPDATE users SET current_state=
                (current_state-'navigation_message_id'-'navigation_revision') ||
                '{"screen":"adaptive","resume_mode":"adaptive"}'::jsonb WHERE id=$1""",
                owner,
            )

    async def current(self) -> Any:
        return await self.pool.fetchrow(
            """SELECT a.*,p.snapshot,p.outcome,p.hints_used,p.issued_at,
            (SELECT count(*) FROM attempts t WHERE t.problem_id=p.id) AS attempt_count
            FROM adaptive_sessions a JOIN users u ON u.id=a.owner
            LEFT JOIN issued_problems p ON p.id=a.problem
            WHERE u.telegram_user_id=$1 AND a.finished IS NULL""",
            self.learner,
        )

    async def finish_disabled_personal(
        self,
        session_id: UUID,
        position: int,
        problem: UUID | None,
        *,
        revision: int,
    ) -> str:
        """Close a disabled personal session only for an explicit mode switch."""
        async with self.pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                """SELECT a.*,p.outcome FROM adaptive_sessions a
                JOIN users u ON u.id=a.owner LEFT JOIN issued_problems p ON p.id=a.problem
                WHERE a.id=$1 AND u.telegram_user_id=$2 AND a.position=$3
                AND a.problem IS NOT DISTINCT FROM $4 AND a.revision=$5
                AND a.finished IS NULL AND a.strategy='personal'
                AND u.preferences->>'personal_training'='false' FOR UPDATE OF u,a""",
                session_id,
                self.learner,
                position,
                problem,
                revision,
            )
            if not row:
                return "stale"
            if problem is not None and row["outcome"] == "issued":
                await conn.execute(
                    "UPDATE issued_problems SET outcome='skipped' WHERE id=$1", problem
                )
            await conn.execute(
                """UPDATE adaptive_sessions SET finished=now(),revision=revision+1
                WHERE id=$1""",
                session_id,
            )
            scope = row["scope"] or {}
            if isinstance(scope, str):
                scope = json.loads(scope)
            fallback = scope.get("resume_fallback")
            await conn.execute(
                """UPDATE users SET current_state=CASE WHEN $2::text IS NULL THEN
                (current_state || '{"screen":"trainings"}'::jsonb)-'resume_mode'
                ELSE current_state || '{"screen":"trainings"}'::jsonb ||
                jsonb_build_object('resume_mode',$2::text) END WHERE id=$1""",
                row["owner"],
                fallback,
            )
            return "finished"

    async def excluded_for_learner(self) -> list[str]:
        return [
            r["skill"]
            for r in await self.pool.fetch(
                """SELECT skill FROM adaptive_unavailable a JOIN users u ON u.id=a.owner
            WHERE u.telegram_user_id=$1 AND retry_after>now()""",
                self.learner,
            )
        ]

    async def unavailable(self, owner: UUID, skill: str) -> None:
        await self.pool.execute(
            """INSERT INTO adaptive_unavailable VALUES($1,$2,now()+interval '1 hour')
            ON CONFLICT(owner,skill) DO UPDATE SET retry_after=excluded.retry_after""",
            owner,
            skill,
        )

    async def refresh(self, row: Any, skills: list[str]) -> bool:
        return bool(
            await self.pool.fetchval(
                """UPDATE adaptive_sessions a SET plan=$5 FROM users u WHERE a.owner=u.id
            AND u.telegram_user_id=$1 AND u.current_state->>'screen'='adaptive'
            AND a.id=$2 AND a.position=$3 AND a.problem IS NOT DISTINCT FROM $4
            AND a.revision=$6 AND a.finished IS NULL RETURNING true""",
                self.learner,
                row["id"],
                row["position"],
                row["problem"],
                json.dumps(skills),
                row["revision"],
            )
        )

    async def totals(self, session_id: UUID, *, from_position: int = 0) -> Any:
        return await self.pool.fetchrow(
            """WITH problems AS (
              SELECT p.*,s.selection<>'repeat'
              AND NOT EXISTS(SELECT FROM issued_problems old WHERE old.user_id=p.user_id
              AND old.id<>p.id AND old.fingerprint=p.fingerprint AND old.issued_at<=p.issued_at
              AND (old.family_id=p.family_id OR p.family_id LIKE 'OGE19-%'
                AND old.family_id LIKE 'OGE19-%'))
              AND NOT EXISTS(SELECT FROM adaptive_evidence e
                JOIN adaptive_evidence old ON old.owner=e.owner
                  AND old.skill=e.skill AND old.variant=e.variant AND old.outcome='issued'
                  AND old.occurred<=e.occurred AND (old.source,old.task)<>(e.source,e.task)
                WHERE e.owner=p.user_id AND e.source='personal' AND e.task=p.id::text
                  AND e.outcome='issued' AND e.variant<>'') AS fresh
              FROM adaptive_slots s JOIN issued_problems p ON p.id=s.problem
              JOIN users u ON u.id=p.user_id
              WHERE s.session_id=$1 AND u.telegram_user_id=$2 AND s.position >= $3
            )
            SELECT count(*) issued, count(*) FILTER(WHERE p.outcome<>'issued') completed,
            count(*) FILTER(WHERE EXISTS(SELECT FROM attempts a WHERE a.problem_id=p.id)) attempted,
            count(*) FILTER(WHERE p.outcome='solved') solved,
            count(*) FILTER(WHERE p.outcome='skipped') skipped,
            count(*) FILTER(WHERE p.hints_used>0) hinted,
            count(*) FILTER(WHERE p.solution_viewed_at IS NOT NULL) reviewed,
            count(*) FILTER(WHERE p.fresh AND EXISTS(SELECT FROM attempts t WHERE t.problem_id=p.id
              AND t.attempt_no=1 AND t.is_correct AND t.used_hint IS FALSE
              AND (p.solution_viewed_at IS NULL OR p.solution_viewed_at>t.created_at))
              AND NOT EXISTS(SELECT FROM adaptive_evidence e
                JOIN adaptive_evidence old ON old.owner=e.owner
                  AND old.skill=e.skill AND old.variant=e.variant AND old.outcome='issued'
                  AND old.occurred<=e.occurred AND (old.source,old.task)<>(e.source,e.task)
                WHERE e.owner=p.user_id AND e.source='personal' AND e.task=p.id::text
                  AND e.outcome='correct' AND e.ordinal=1 AND e.variant<>'')) independent,
            count(*) FILTER(WHERE p.fresh) fresh FROM problems p""",
            session_id,
            self.learner,
            from_position,
        )

    async def seen(self, owner: UUID, family: str) -> list[str]:
        from app.adaptive.store import sync

        async with self.pool.acquire() as conn, conn.transaction():
            if await conn.fetchval(
                "SELECT EXISTS(SELECT FROM adaptive_dirty WHERE owner=$1)", owner,
            ):
                await sync(conn, owner)
            rows = await conn.fetch(
                """SELECT DISTINCT fingerprint variant FROM issued_problems
                WHERE user_id=$1 AND (family_id=$2 OR $2 LIKE 'OGE19-%'
                AND family_id LIKE 'OGE19-%')
                UNION SELECT DISTINCT e.variant FROM adaptive_evidence e
                WHERE e.owner=$1 AND (e.skill=$2 OR e.number=19 AND $2 LIKE 'OGE19-%')
                AND e.outcome='issued'""",
                owner,
                family,
            )
        return [row["variant"] for row in rows if row["variant"]]

    async def mixed_choices(
        self, row: Any, catalog: dict[str, int], scope: dict[str, Any],
    ) -> tuple[int, list[str], dict[str, Any]]:
        number, rotation = reserve_number(
            scope["mixed_rotation"], set(catalog.values()), scope["mixed_batch"],
        )
        families = sorted(family for family, value in catalog.items() if value == number)
        Random(f"{scope['plan_seed']}:{number}:{row['position']}").shuffle(families)
        records = await self.pool.fetch(
            """WITH issues AS (
                 SELECT family_id,issued_at FROM issued_problems
                   WHERE user_id=$1 AND family_id=ANY($2::text[])
                 UNION ALL
                 SELECT p.family_id,p.issued_at FROM mixed_training_problems p
                   JOIN mixed_training_sessions s ON s.id=p.session_id
                   WHERE s.user_id=$1 AND p.number=$3 AND p.family_id=ANY($2::text[])
                 UNION ALL
                 SELECT sc.snapshot->'questions'->(q.position::int-1)->>'family_id',
                        coalesce(q.adaptive_issued_at,s.started_at)
                   FROM oge15_sessions s JOIN oge15_scenarios sc ON sc.id=s.scenario_id
                   JOIN oge15_question_progress q ON q.session_id=s.id
                   WHERE s.user_id=$1 AND q.position=$3 AND q.status<>'pending'
                     AND sc.snapshot->'questions'->(q.position::int-1)->>'family_id'
                         =ANY($2::text[])
               )
               SELECT family_id,max(issued_at) AS latest FROM issues GROUP BY family_id""",
            row["owner"], families, number,
        )
        issued = {record["family_id"]: record["latest"] for record in records}
        families.sort(key=lambda family: (family in issued, issued.get(family)))
        return number, families, rotation

    async def save(
        self, row: Any, family: str, candidate: dict[str, Any], *, repeat: bool = False,
        mixed_claim: tuple[int, dict[str, Any]] | None = None,
    ) -> bool:
        pid = UUID(candidate["problem_id"])
        async with self.pool.acquire() as conn, conn.transaction():
            claimed = await conn.fetchval(
                """SELECT a.id FROM adaptive_sessions a JOIN users u
                ON u.id=a.owner WHERE a.id=$1 AND u.telegram_user_id=$2 AND a.position=$3
                AND a.problem IS NULL AND a.finished IS NULL AND a.plan->>a.position::int=$4
                AND a.revision=$5 AND a.prompt IS NOT DISTINCT FROM $6
                AND u.current_state->>'screen'='adaptive'
                AND (a.strategy<>'personal' OR
                  u.preferences->>'personal_training' IS DISTINCT FROM 'false')
                FOR UPDATE OF u,a""",
                row["id"],
                self.learner,
                row["position"],
                family,
                row["revision"],
                row["prompt"],
            )
            if not claimed:
                return False
            if await conn.fetchval(
                "SELECT EXISTS(SELECT FROM adaptive_dirty WHERE owner=$1)", row["owner"]
            ):
                from app.adaptive.store import sync

                await sync(conn, row["owner"])
            duplicate = await conn.fetchval(
                """SELECT EXISTS(
                  SELECT FROM issued_problems p WHERE p.user_id=$1 AND p.fingerprint=$3
                  AND (p.family_id=$2 OR $2 LIKE 'OGE19-%' AND p.family_id LIKE 'OGE19-%')
                  UNION ALL SELECT FROM mixed_training_problems p
                  JOIN mixed_training_sessions s ON s.id=p.session_id
                  WHERE s.user_id=$1 AND p.fingerprint=$3
                  AND (p.family_id=$2 OR $2 LIKE 'OGE19-%' AND p.family_id LIKE 'OGE19-%')
                  UNION ALL SELECT FROM adaptive_evidence e WHERE e.owner=$1 AND e.variant=$3
                  AND (e.skill=$2 OR e.number=19 AND $2 LIKE 'OGE19-%')
                )""",
                row["owner"], family, candidate["fingerprint"],
            )
            if duplicate != repeat:
                return False
            await conn.execute(
                """INSERT INTO issued_problems(id,user_id,family_id,generator_version,
                seed,fingerprint,snapshot) VALUES($1,$2,$3,$4,$5,$6,$7)""",
                pid,
                row["owner"],
                family,
                candidate["generator_version"],
                candidate.get("seed"),
                candidate["fingerprint"],
                json.dumps(candidate, ensure_ascii=False),
            )
            await conn.execute(
                """INSERT INTO adaptive_slots(session_id,position,problem,selection)
                SELECT $1,$2,$3,CASE WHEN $4 THEN 'repeat'
                WHEN a.scope->>'similar_position'=a.position::text
                THEN 'similar' ELSE 'strategy' END FROM adaptive_sessions a WHERE a.id=$1""",
                claimed,
                row["position"],
                pid,
                repeat,
            )
            await conn.execute(
                """UPDATE adaptive_sessions SET problem=$2,prompt=NULL,
                scope=(scope-'similar_position'-'similar_replaced_family') || $3::jsonb
                WHERE id=$1""",
                claimed, pid, json.dumps(
                    {"mixed_pending": {"number": mixed_claim[0], "rotation": mixed_claim[1]}}
                    if mixed_claim else {}
                ),
            )
            return True

    async def choose_similar(
        self, session_id: UUID, position: int, problem: UUID, *, revision: int | None = None,
        prompt: int | None = None,
    ) -> str:
        """Reserve the next real slot for a fresh variant of the completed family."""
        async with self.pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                """SELECT a.*,p.family_id,p.outcome FROM adaptive_sessions a
                JOIN users u ON u.id=a.owner JOIN issued_problems p ON p.id=a.problem
                WHERE a.id=$1 AND u.telegram_user_id=$2 AND a.position=$3 AND a.problem=$4
                AND a.finished IS NULL AND u.current_state->>'screen'='adaptive'
                AND ($5::bigint IS NULL OR a.prompt=$5)
                AND (a.strategy<>'personal' OR
                  u.preferences->>'personal_training' IS DISTINCT FROM 'false')
                FOR UPDATE OF a""",
                session_id, self.learner, position, problem, prompt,
            )
            if not row or revision is not None and row["revision"] != revision:
                return "stale"
            if row["outcome"] == "issued":
                return "unfinished"
            plan = json.loads(row["plan"])
            next_position = position + 1
            if next_position >= len(plan):
                return "full"
            plan[next_position] = row["family_id"]
            scope = row["scope"] or {}
            if isinstance(scope, str):
                scope = json.loads(scope)
            scope["similar_position"] = next_position
            scope["similar_replaced_family"] = json.loads(row["plan"])[next_position]
            await conn.execute(
                """UPDATE adaptive_sessions SET position=$2,problem=NULL,prompt=NULL,plan=$3,
                scope=$4,
                revision=revision+1 WHERE id=$1""",
                session_id, next_position, json.dumps(plan), json.dumps(scope),
            )
            return "next"

    async def cancel_similar(
        self, session_id: UUID, position: int, *, revision: int, prompt: int | None = None,
    ) -> str:
        """Roll back an exhausted similar reservation without consuming its slot."""
        async with self.pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                """SELECT a.* FROM adaptive_sessions a JOIN users u ON u.id=a.owner
                WHERE a.id=$1 AND u.telegram_user_id=$2 AND a.position=$3
                AND a.problem IS NULL AND a.revision=$4 AND a.finished IS NULL
                AND ($5::bigint IS NULL OR a.prompt=$5) AND u.current_state->>'screen'='adaptive'
                AND (a.strategy<>'personal' OR
                  u.preferences->>'personal_training' IS DISTINCT FROM 'false')
                FOR UPDATE OF a""",
                session_id, self.learner, position, revision, prompt,
            )
            if not row:
                return "stale"
            scope = row["scope"] or {}
            if isinstance(scope, str):
                scope = json.loads(scope)
            if scope.get("similar_position") != position:
                return "stale"
            previous = position - 1
            problem = await conn.fetchval(
                "SELECT problem FROM adaptive_slots WHERE session_id=$1 AND position=$2",
                session_id, previous,
            )
            plan = json.loads(row["plan"])
            plan[position] = scope.pop("similar_replaced_family")
            scope.pop("similar_position", None)
            await conn.execute(
                """UPDATE adaptive_sessions SET position=$2,problem=$3,plan=$4,scope=$5,prompt=NULL,
                revision=revision+1 WHERE id=$1""",
                session_id, previous, problem, json.dumps(plan), json.dumps(scope),
            )
            return "exhausted"

    async def difficulties(self, session_id: UUID) -> dict[str, int]:
        rows = await self.pool.fetch(
            """SELECT p.family_id,count(*) AS total
            FROM adaptive_slots sl JOIN issued_problems p ON p.id=sl.problem
            JOIN users u ON u.id=p.user_id
            WHERE sl.session_id=$1 AND u.telegram_user_id=$2
            AND (p.outcome IN ('failed','solution_viewed') OR EXISTS(
                SELECT FROM attempts t WHERE t.problem_id=p.id
                AND (NOT t.is_correct OR t.used_hint IS TRUE)
            ))
            GROUP BY p.family_id""", session_id, self.learner,
        )
        return {row["family_id"]: row["total"] for row in rows}

    async def answer_delta(self, session_id: UUID, message_id: int) -> Any:
        from app.adaptive.store import sync

        async with self.pool.acquire() as conn, conn.transaction():
            owner = await conn.fetchval(
                """SELECT s.owner FROM adaptive_sessions s JOIN users u ON u.id=s.owner
                WHERE s.id=$1 AND u.telegram_user_id=$2""", session_id, self.learner,
            )
            if owner is None:
                return None
            await sync(conn, owner)
            return await conn.fetchrow(
                """SELECT d.reason,d.after_state,sl.selection FROM adaptive_session_deltas d
                JOIN adaptive_slots sl USING (session_id,position)
                JOIN attempts a ON a.problem_id=sl.problem AND a.attempt_no=d.ordinal
                WHERE d.session_id=$1 AND a.telegram_message_id=$2 AND a.bot_id=$3 AND d.reason IN
                ('independent_success','skill_confirmed','gap_closed','independent_review')""",
                session_id, message_id, self.bot_id,
            )

    async def summary_deltas(self, session_id: UUID, *, from_position: int = 0) -> list[Any]:
        """Persist and return only projection changes caused by the requested session slots."""
        from app.adaptive.store import sync

        async with self.pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                """SELECT a.owner FROM adaptive_sessions a JOIN users u ON u.id=a.owner
                WHERE a.id=$1 AND u.telegram_user_id=$2""",
                session_id, self.learner,
            )
            if not row:
                return []
            await sync(conn, row["owner"])
            rows: list[Any] = await conn.fetch(
                """SELECT position,ordinal,skill,before_state,after_state,reason
                FROM adaptive_session_deltas WHERE session_id=$1 AND position >= $2
                ORDER BY position,ordinal""",
                session_id, from_position,
            )
            return rows

    async def set_prompt(self, user_id: int, problem_id: str, message_id: int) -> bool:
        return bool(
            await self.pool.fetchval(
                """UPDATE adaptive_sessions a SET prompt=$3,
            scope=CASE WHEN a.scope ? 'mixed_pending' THEN
              (a.scope-'mixed_pending') || jsonb_build_object(
                'mixed_rotation',a.scope->'mixed_pending'->'rotation',
                'mixed_batch',(a.scope->'mixed_batch') ||
                    jsonb_build_array(a.scope->'mixed_pending'->'number'))
              ELSE a.scope END
            FROM users u
            WHERE a.owner=u.id AND u.telegram_user_id=$1 AND a.problem=$2 AND a.finished IS NULL
            AND (a.prompt IS NULL OR a.prompt<$3) RETURNING true""",
                user_id,
                UUID(problem_id),
                message_id,
            )
        )

    async def set_pending_prompt(self, row: Any, message_id: int) -> None:
        await self.pool.execute(
            """UPDATE adaptive_sessions a SET prompt=$5 FROM users u WHERE a.owner=u.id
            AND u.telegram_user_id=$1 AND u.current_state->>'screen'='adaptive'
            AND a.id=$2 AND a.position=$3 AND a.revision=$4 AND a.problem IS NULL
            AND a.finished IS NULL AND (a.prompt IS NULL OR a.prompt<$5)""",
            self.learner, row["id"], row["position"], row["revision"], message_id,
        )

    async def act(
        self,
        problem: UUID | None,
        prompt: int | None,
        action: str,
        *,
        raw: str = "",
        correct: bool = False,
        message_id: int = 0,
        session_id: UUID | None = None,
        position: int | None = None,
        revision: int | None = None,
        next_block: list[str] | None = None,
    ) -> str:
        async with self.pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                """SELECT a.*,p.outcome,p.hints_used,
                jsonb_array_length(p.snapshot->'hints') hint_count
                FROM users u JOIN adaptive_sessions a ON a.owner=u.id
                LEFT JOIN issued_problems p ON p.id=a.problem
                WHERE u.telegram_user_id=$1 AND u.current_state->>'screen'='adaptive'
                AND a.finished IS NULL AND (a.strategy<>'personal' OR
                  u.preferences->>'personal_training' IS DISTINCT FROM 'false')
                FOR UPDATE OF u,a""",
                self.learner,
            )
            if (
                not row
                or row["problem"] != problem
                or prompt is not None
                and prompt != row["prompt"]
                or position is not None
                and row["position"] != position
                or session_id is not None
                and session_id != row["id"]
                or revision is not None
                and revision != row["revision"]
            ):
                return "stale"
            if action in {"menu", "finish"}:
                scope = row["scope"] or {}
                if isinstance(scope, str):
                    scope = json.loads(scope)
                fallback = scope.get("resume_fallback")
                if action == "menu":
                    await conn.execute(
                        """UPDATE users SET current_state=
                        (current_state-'navigation_message_id'-'navigation_revision') ||
                        '{"screen":"main_menu"}'::jsonb WHERE id=$1""", row["owner"]
                    )
                else:
                    await conn.execute(
                        """UPDATE users SET current_state=CASE WHEN $2::text IS NULL THEN
                        (current_state-'navigation_message_id'-'navigation_revision'-'resume_mode')
                        || '{"screen":"main_menu"}'::jsonb
                        ELSE (current_state-'navigation_message_id'-'navigation_revision')
                        || '{"screen":"main_menu"}'::jsonb ||
                        jsonb_build_object('resume_mode',$2::text) END WHERE id=$1""",
                        row["owner"], fallback,
                    )
                if action == "menu":
                    return "paused"
                if row["outcome"] == "issued":
                    await conn.execute(
                        "UPDATE issued_problems SET outcome='skipped' WHERE id=$1", problem
                    )

                await conn.execute(
                    """UPDATE adaptive_sessions SET finished=now(),revision=revision+1
                    WHERE id=$1""",
                    row["id"],
                )
                return "finished"
            if at_checkpoint(row):
                if action != "continue" or not next_block or len(next_block) != BLOCK_SIZE:
                    return "stale"
                await conn.execute(
                    """UPDATE adaptive_sessions SET position=position+1,problem=NULL,prompt=NULL,
                    plan=plan || $2::jsonb,revision=revision+1 WHERE id=$1""",
                    row["id"], json.dumps(next_block),
                )
                return "next"
            advance = action == "next" and problem and row["outcome"] != "issued"
            if advance:
                done = row["position"] + 1 >= len(json.loads(row["plan"]))
                await conn.execute(
                    """UPDATE adaptive_sessions SET position=position+1,problem=NULL,
                    prompt=NULL,completed=$2,finished=CASE WHEN $2 THEN now() END,
                    revision=revision+1 WHERE id=$1""",
                    row["id"],
                    done,
                )
                if done:
                    scope = row["scope"] or {}
                    if isinstance(scope, str):
                        scope = json.loads(scope)
                    await conn.execute(
                        """UPDATE users SET current_state=CASE WHEN $2::text IS NULL THEN
                        (current_state || '{"screen":"main_menu"}'::jsonb)-'resume_mode'
                        ELSE current_state || '{"screen":"main_menu"}'::jsonb ||
                        jsonb_build_object('resume_mode',$2::text) END WHERE id=$1""",
                        row["owner"],
                        scope.get("resume_fallback"),
                    )
                return "completed" if done else "next"
            if row["outcome"] != "issued":
                return "stale"
            if action == "hint":
                if row["hints_used"] >= (row["hint_count"] or 0):
                    return "no_hint"
                await conn.execute(
                    "UPDATE issued_problems SET hints_used=hints_used+1 WHERE id=$1", problem
                )
                return "hint"
            if action in {"skip", "solution"}:
                await conn.execute(
                    """UPDATE issued_problems SET outcome=$2,
                    solution_viewed_at=CASE WHEN $2='solution_viewed' THEN now() END WHERE id=$1""",
                    problem,
                    "skipped" if action == "skip" else "solution_viewed",
                )
                if (
                    row["strategy"] not in OPEN_PRACTICE
                    and row["position"] + 1 >= len(json.loads(row["plan"]))
                ):
                    await conn.execute(
                        """UPDATE adaptive_sessions SET completed=true,finished=now(),
                        revision=revision+1 WHERE id=$1""", row["id"]
                    )
                    scope = row["scope"] or {}
                    if isinstance(scope, str):
                        scope = json.loads(scope)
                    await conn.execute(
                        """UPDATE users SET current_state=CASE WHEN $2::text IS NULL THEN
                        (current_state || '{"screen":"main_menu"}'::jsonb)-'resume_mode'
                        ELSE current_state || '{"screen":"main_menu"}'::jsonb ||
                        jsonb_build_object('resume_mode',$2::text) END WHERE id=$1""",
                        row["owner"], scope.get("resume_fallback")
                    )
                    return f"completed_{action}"
                return action
            if action != "answer":
                return "stale"
            attempt = 1 + await conn.fetchval(
                "SELECT count(*) FROM attempts WHERE problem_id=$1", problem
            )
            saved = await conn.fetchval(
                """INSERT INTO attempts(user_id,problem_id,attempt_no,
                raw_answer,is_correct,used_hint,telegram_message_id,bot_id)
                VALUES($1,$2,$3,$4,$5,$6,$7,$8)
                ON CONFLICT DO NOTHING RETURNING true""",
                row["owner"],
                problem,
                attempt,
                raw[:200],
                correct,
                bool(row["hints_used"]),
                message_id,
                self.bot_id,
            )
            if not saved:
                return "stale"
            outcome = "solved" if correct else "failed" if attempt == 2 else "issued"
            await conn.execute(
                """UPDATE issued_problems SET outcome=$2,
                solution_viewed_at=CASE WHEN $2='failed' THEN now() ELSE solution_viewed_at END
                WHERE id=$1""",
                problem,
                outcome,
            )
            if (
                outcome != "issued" and row["strategy"] not in OPEN_PRACTICE
                and row["position"] + 1 >= len(json.loads(row["plan"]))
            ):
                await conn.execute(
                    """UPDATE adaptive_sessions SET completed=true,finished=now(),
                    revision=revision+1 WHERE id=$1""", row["id"]
                )
                scope = row["scope"] or {}
                if isinstance(scope, str):
                    scope = json.loads(scope)
                await conn.execute(
                    """UPDATE users SET current_state=CASE WHEN $2::text IS NULL THEN
                    (current_state || '{"screen":"main_menu"}'::jsonb)-'resume_mode'
                    ELSE current_state || '{"screen":"main_menu"}'::jsonb ||
                    jsonb_build_object('resume_mode',$2::text) END WHERE id=$1""",
                    row["owner"], scope.get("resume_fallback")
                )
                return f"completed_{outcome}"
            return outcome
