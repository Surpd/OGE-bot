"""A finite session uses normal issued problems/attempts and owns only its cursor."""

import json
from typing import Any
from uuid import UUID

import asyncpg


class Session:
    def __init__(self, repository: Any, learner: int) -> None:
        self.pool: asyncpg.Pool = repository._pool
        self.learner = learner

    async def start(self, skills: list[str]) -> None:
        async with self.pool.acquire() as conn, conn.transaction():
            owner = await conn.fetchval(
                "SELECT id FROM users WHERE telegram_user_id=$1 FOR UPDATE", self.learner
            )
            if skills:
                await conn.execute(
                    """INSERT INTO adaptive_sessions(owner,plan) VALUES($1,$2)
                    ON CONFLICT(owner) WHERE finished IS NULL DO NOTHING""",
                    owner,
                    json.dumps(skills),
                )
            await conn.execute(
                """UPDATE users SET current_state=current_state ||
                '{"screen":"adaptive"}'::jsonb WHERE id=$1""",
                owner,
            )

    async def current(self) -> Any:
        return await self.pool.fetchrow(
            """SELECT a.*,p.snapshot,p.outcome,p.hints_used,p.issued_at
            FROM adaptive_sessions a JOIN users u ON u.id=a.owner
            LEFT JOIN issued_problems p ON p.id=a.problem
            WHERE u.telegram_user_id=$1 AND a.finished IS NULL""",
            self.learner,
        )

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
            AND a.finished IS NULL RETURNING true""",
                self.learner,
                row["id"],
                row["position"],
                row["problem"],
                json.dumps(skills),
            )
        )

    async def totals(self, session_id: UUID) -> Any:
        return await self.pool.fetchrow(
            """SELECT count(*) issued,count(*) FILTER(WHERE p.outcome='solved') solved,
            count(*) FILTER(WHERE EXISTS(SELECT FROM attempts t WHERE t.problem_id=p.id
            AND t.attempt_no=1 AND t.is_correct AND t.used_hint IS FALSE
            AND (p.solution_viewed_at IS NULL OR p.solution_viewed_at>t.created_at))) independent
            FROM adaptive_slots s JOIN issued_problems p ON p.id=s.problem
            JOIN users u ON u.id=p.user_id
            WHERE s.session_id=$1 AND u.telegram_user_id=$2""",
            session_id,
            self.learner,
        )

    async def seen(self, owner: UUID, family: str) -> list[str]:
        return [
            r["variant"]
            for r in await self.pool.fetch(
                """SELECT DISTINCT variant
            FROM adaptive_evidence WHERE owner=$1 AND (skill=$2 OR number=19 AND $2 LIKE 'OGE19-%')
                AND outcome='issued'""",
                owner,
                family,
            )
        ]

    async def save(self, row: Any, family: str, candidate: dict[str, Any]) -> bool:
        pid = UUID(candidate["problem_id"])
        async with self.pool.acquire() as conn, conn.transaction():
            claimed = await conn.fetchval(
                """SELECT a.id FROM adaptive_sessions a JOIN users u
                ON u.id=a.owner WHERE a.id=$1 AND u.telegram_user_id=$2 AND a.position=$3
                AND a.problem IS NULL AND a.finished IS NULL AND a.plan->>a.position::int=$4
                AND u.current_state->>'screen'='adaptive'
                FOR UPDATE OF u,a""",
                row["id"],
                self.learner,
                row["position"],
                family,
            )
            if not claimed:
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
                "INSERT INTO adaptive_slots(session_id,position,problem) VALUES($1,$2,$3)",
                claimed,
                row["position"],
                pid,
            )
            await conn.execute(
                "UPDATE adaptive_sessions SET problem=$2,prompt=NULL WHERE id=$1", claimed, pid
            )
            return True

    async def set_prompt(self, user_id: int, problem_id: str, message_id: int) -> bool:
        return bool(
            await self.pool.fetchval(
                """UPDATE adaptive_sessions a SET prompt=$3 FROM users u
            WHERE a.owner=u.id AND u.telegram_user_id=$1 AND a.problem=$2 AND a.finished IS NULL
            AND (a.prompt IS NULL OR a.prompt<$3) RETURNING true""",
                user_id,
                UUID(problem_id),
                message_id,
            )
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
    ) -> str:
        async with self.pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                """SELECT a.*,p.outcome,p.hints_used,
                jsonb_array_length(p.snapshot->'hints') hint_count
                FROM users u JOIN adaptive_sessions a ON a.owner=u.id
                LEFT JOIN issued_problems p ON p.id=a.problem
                WHERE u.telegram_user_id=$1 AND u.current_state->>'screen'='adaptive'
                AND a.finished IS NULL FOR UPDATE OF u,a""",
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
            ):
                return "stale"
            if action in {"menu", "finish"}:
                await conn.execute(
                    """UPDATE users SET current_state=current_state ||
                    '{"screen":"main_menu"}'::jsonb WHERE id=$1""",
                    row["owner"],
                )
                if action == "menu":
                    return "paused"
                if row["outcome"] == "issued":
                    await conn.execute(
                        "UPDATE issued_problems SET outcome='skipped' WHERE id=$1", problem
                    )

                await conn.execute(
                    "UPDATE adaptive_sessions SET finished=now() WHERE id=$1", row["id"]
                )
                return "finished"
            advance = action == "next" and problem and row["outcome"] != "issued"
            if advance:
                done = row["position"] + 1 >= len(json.loads(row["plan"]))
                await conn.execute(
                    """UPDATE adaptive_sessions SET position=position+1,problem=NULL,
                    prompt=NULL,completed=$2,finished=CASE WHEN $2 THEN now() END WHERE id=$1""",
                    row["id"],
                    done,
                )
                if done:
                    await conn.execute(
                        """UPDATE users SET current_state=current_state ||
                        '{"screen":"main_menu"}'::jsonb WHERE id=$1""",
                        row["owner"],
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
                return action
            if action != "answer":
                return "stale"
            attempt = 1 + await conn.fetchval(
                "SELECT count(*) FROM attempts WHERE problem_id=$1", problem
            )
            saved = await conn.fetchval(
                """INSERT INTO attempts(user_id,problem_id,attempt_no,
                raw_answer,is_correct,used_hint,telegram_message_id) VALUES($1,$2,$3,$4,$5,$6,$7)
                ON CONFLICT DO NOTHING RETURNING true""",
                row["owner"],
                problem,
                attempt,
                raw[:200],
                correct,
                bool(row["hints_used"]),
                message_id,
            )
            if not saved:
                return "stale"
            outcome = "solved" if correct else "failed" if attempt == 2 else "issued"
            await conn.execute(
                "UPDATE issued_problems SET outcome=$2 WHERE id=$1", problem, outcome
            )
            return outcome
