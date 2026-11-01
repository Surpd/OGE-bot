import json
from typing import Protocol, cast
from uuid import UUID

import asyncpg


class Repository(Protocol):
    async def register_user(self, telegram_user_id: int) -> None: ...

    async def save_user_state(self, telegram_user_id: int, screen: str) -> None: ...

    async def transition_task_screen(
        self,
        telegram_user_id: int,
        mode: str,
        expected_problem_id: str,
        target_screen: str,
        expected_prompt_message_id: int | None = None,
    ) -> bool: ...

    async def user_state(self, telegram_user_id: int) -> str | None: ...

    async def last_training_mode(self, telegram_user_id: int) -> str | None: ...

    async def current_session(self, telegram_user_id: int) -> dict[str, object] | None: ...

    async def ensure_task6_session(self, telegram_user_id: int) -> str: ...

    async def advance_task6_problem(
        self,
        telegram_user_id: int,
        expected_problem_id: str | None,
        candidates: list[dict[str, object]],
        expected_screen: str | None = None,
        expected_prompt_message_id: int | None = None,
        skip_active: bool = False,
    ) -> dict[str, object]: ...

    async def task6_state(self, telegram_user_id: int) -> dict[str, object] | None: ...

    async def set_task6_prompt_message(
        self,
        telegram_user_id: int,
        expected_problem_id: str,
        message_id: int,
        expected_status: str | None = None,
    ) -> bool: ...

    async def set_task6_condition_message(
        self, telegram_user_id: int, expected_problem_id: str, message_id: int
    ) -> bool: ...

    async def task6_attempt(
        self,
        telegram_user_id: int,
        expected_problem_id: str,
        raw_answer: str,
        is_correct: bool,
        telegram_message_id: int | None = None,
        expected_prompt_message_id: int | None = None,
    ) -> dict[str, object] | None: ...

    async def task6_hint(
        self,
        telegram_user_id: int,
        expected_problem_id: str,
        expected_prompt_message_id: int | None = None,
    ) -> str | None: ...

    async def task6_reveal_solution(
        self,
        telegram_user_id: int,
        expected_problem_id: str,
        expected_prompt_message_id: int | None = None,
    ) -> dict[str, object] | None: ...

    async def task6_progress(self, telegram_user_id: int) -> dict[str, int]: ...

    async def claim_update(self, update_id: int) -> bool: ...

    async def finish_update(self, update_id: int, *, failed: bool = False) -> None: ...

    async def ensure_task9_session(self, telegram_user_id: int) -> str: ...

    async def advance_task9_problem(
        self,
        telegram_user_id: int,
        expected_problem_id: str | None,
        candidates: list[dict[str, object]],
        expected_screen: str | None = None,
        expected_prompt_message_id: int | None = None,
        skip_active: bool = False,
    ) -> dict[str, object]: ...

    async def task9_state(self, telegram_user_id: int) -> dict[str, object] | None: ...

    async def set_task9_prompt_message(
        self,
        telegram_user_id: int,
        expected_problem_id: str,
        message_id: int,
        expected_status: str | None = None,
    ) -> bool: ...

    async def set_task9_condition_message(
        self, telegram_user_id: int, expected_problem_id: str, message_id: int
    ) -> bool: ...

    async def task9_attempt(
        self,
        telegram_user_id: int,
        expected_problem_id: str,
        raw_answer: str,
        is_correct: bool,
        telegram_message_id: int | None = None,
        expected_prompt_message_id: int | None = None,
    ) -> dict[str, object] | None: ...

    async def task9_hint(
        self,
        telegram_user_id: int,
        expected_problem_id: str,
        expected_prompt_message_id: int | None = None,
    ) -> str | None: ...

    async def task9_reveal_solution(
        self,
        telegram_user_id: int,
        expected_problem_id: str,
        expected_prompt_message_id: int | None = None,
    ) -> dict[str, object] | None: ...

    async def task9_progress(self, telegram_user_id: int) -> dict[str, int]: ...

    async def ensure_task10_session(self, telegram_user_id: int) -> str: ...

    async def advance_task10_problem(
        self,
        telegram_user_id: int,
        expected_problem_id: str | None,
        candidates: list[dict[str, object]],
        expected_screen: str | None = None,
        expected_prompt_message_id: int | None = None,
        skip_active: bool = False,
    ) -> dict[str, object]: ...

    async def task10_state(self, telegram_user_id: int) -> dict[str, object] | None: ...

    async def set_task10_prompt_message(
        self,
        telegram_user_id: int,
        expected_problem_id: str,
        message_id: int,
        expected_status: str | None = None,
    ) -> bool: ...

    async def set_task10_condition_message(
        self, telegram_user_id: int, expected_problem_id: str, message_id: int
    ) -> bool: ...

    async def task10_attempt(
        self,
        telegram_user_id: int,
        expected_problem_id: str,
        raw_answer: str,
        is_correct: bool,
        telegram_message_id: int | None = None,
        expected_prompt_message_id: int | None = None,
    ) -> dict[str, object] | None: ...

    async def task10_hint(
        self,
        telegram_user_id: int,
        expected_problem_id: str,
        expected_prompt_message_id: int | None = None,
    ) -> str | None: ...

    async def task10_reveal_solution(
        self,
        telegram_user_id: int,
        expected_problem_id: str,
        expected_prompt_message_id: int | None = None,
    ) -> dict[str, object] | None: ...

    async def task10_progress(self, telegram_user_id: int) -> dict[str, int]: ...


    async def ensure_task14_session(self, telegram_user_id: int) -> str: ...

    async def advance_task14_problem(
        self,
        telegram_user_id: int,
        expected_problem_id: str | None,
        candidates: list[dict[str, object]],
        expected_screen: str | None = None,
        expected_prompt_message_id: int | None = None,
        skip_active: bool = False,
    ) -> dict[str, object]: ...

    async def task14_state(self, telegram_user_id: int) -> dict[str, object] | None: ...

    async def set_task14_prompt_message(
        self,
        telegram_user_id: int,
        expected_problem_id: str,
        message_id: int,
        expected_status: str | None = None,
    ) -> bool: ...

    async def set_task14_condition_message(
        self, telegram_user_id: int, expected_problem_id: str, message_id: int
    ) -> bool: ...

    async def task14_attempt(
        self,
        telegram_user_id: int,
        expected_problem_id: str,
        raw_answer: str,
        is_correct: bool,
        telegram_message_id: int | None = None,
        expected_prompt_message_id: int | None = None,
    ) -> dict[str, object] | None: ...

    async def task14_hint(
        self,
        telegram_user_id: int,
        expected_problem_id: str,
        expected_prompt_message_id: int | None = None,
    ) -> str | None: ...

    async def task14_reveal_solution(
        self,
        telegram_user_id: int,
        expected_problem_id: str,
        expected_prompt_message_id: int | None = None,
    ) -> dict[str, object] | None: ...

    async def task14_progress(self, telegram_user_id: int) -> dict[str, int]: ...


class _Task10PostgresMixin:
    _pool: asyncpg.Pool

    async def register_user(self, telegram_user_id: int) -> None:
        raise NotImplementedError

    async def ensure_task10_session(self, telegram_user_id: int) -> str:
        await self.register_user(telegram_user_id)
        async with self._pool.acquire() as connection, connection.transaction():
            user_id = await connection.fetchval(
                "SELECT id FROM users WHERE telegram_user_id = $1 FOR UPDATE", telegram_user_id
            )
            existing = await connection.fetchval(
                "SELECT id FROM sessions WHERE user_id = $1 AND mode = 'task10' "
                "AND finished_at IS NULL ORDER BY started_at DESC LIMIT 1",
                user_id,
            )
            if existing is not None:
                return str(existing)
            created = await connection.fetchval(
                "INSERT INTO sessions (user_id, mode, state) VALUES ($1, 'task10', '{}'::jsonb) "
                "RETURNING id",
                user_id,
            )
            return str(created)

    async def advance_task10_problem(
        self,
        telegram_user_id: int,
        expected_problem_id: str | None,
        candidates: list[dict[str, object]],
        expected_screen: str | None = None,
        expected_prompt_message_id: int | None = None,
        skip_active: bool = False,
    ) -> dict[str, object]:
        async with self._pool.acquire() as connection, connection.transaction():
            user = await connection.fetchrow(
                "SELECT id, current_state FROM users WHERE telegram_user_id = $1 FOR UPDATE",
                telegram_user_id,
            )
            if user is None:
                raise RuntimeError("Task-10 user does not exist")
            user_state = _json_object(user["current_state"])
            if expected_screen is not None and user_state.get("screen") != expected_screen:
                return {"_transitioned": False, "_stale_screen": True}
            session = await connection.fetchrow(
                """SELECT id, active_problem_id, state FROM sessions
                   WHERE user_id = $1 AND mode = 'task10' AND finished_at IS NULL
                   ORDER BY started_at DESC LIMIT 1 FOR UPDATE""",
                user["id"],
            )
            if session is None:
                raise RuntimeError("Task-10 session does not exist")
            state = _json_object(session["state"])
            if expected_prompt_message_id is not None and (
                state.get("input_prompt_message_id") != expected_prompt_message_id
            ):
                return {"_transitioned": False, "_stale_screen": True}
            active_id = str(session["active_problem_id"]) if session["active_problem_id"] else None
            if active_id is not None:
                current_row = await connection.fetchrow(
                    "SELECT snapshot FROM issued_problems WHERE id = $1",
                    session["active_problem_id"],
                )
                if current_row is None:
                    raise RuntimeError("Active task-10 snapshot is missing")
                current = _json_object(current_row["snapshot"])
                if expected_problem_id != active_id or skip_active != (
                    state.get("status") == "active"
                ):
                    return {**current, "_transitioned": False}
                if skip_active:
                    await connection.execute(
                        "UPDATE issued_problems SET outcome = 'skipped' WHERE id = $1",
                        session["active_problem_id"],
                    )
            elif expected_problem_id is not None:
                raise RuntimeError("Expected active task-10 problem is missing")
            if not candidates:
                raise RuntimeError("No task-10 candidates available")
            recent_value = state.get("recent_fingerprints", [])
            recent_order = (
                [x for x in recent_value if isinstance(x, str)]
                if isinstance(recent_value, list)
                else []
            )
            recent = set(recent_order)
            rejected = 0
            for candidate in candidates:
                fingerprint = str(candidate["fingerprint"])
                if fingerprint in recent:
                    rejected += 1
                    continue
                problem = dict(candidate)
                family_queue = problem.pop("_family_queue_after", [])
                last_family = problem.pop("_last_family_after", None)
                problem_id = UUID(str(problem["problem_id"]))
                await connection.execute(
                    """INSERT INTO issued_problems
                       (id, user_id, session_id, family_id, generator_version, seed,
                        fingerprint, shape_fingerprint, snapshot, selection_attempts, outcome)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10, 'issued')""",
                    problem_id,
                    user["id"],
                    session["id"],
                    problem["family_id"],
                    problem["generator_version"],
                    problem["seed"],
                    fingerprint,
                    problem["family_id"],
                    json.dumps(problem, ensure_ascii=False),
                    problem.get("selection_attempts", 1),
                )
                next_state = {
                    "status": "active",
                    "attempts": 0,
                    "hints_used": 0,
                    "used_hint": False,
                    "family_queue": family_queue if isinstance(family_queue, list) else [],
                    "last_family_id": last_family if isinstance(last_family, str) else None,
                    "recent_fingerprints": [*recent_order, fingerprint][-30:],
                    "selection_dedupe_rejections": _state_int(state, "selection_dedupe_rejections")
                    + rejected,
                }
                await connection.execute(
                    "UPDATE sessions SET active_problem_id = $2, state = $3::jsonb WHERE id = $1",
                    session["id"],
                    problem_id,
                    json.dumps(next_state, ensure_ascii=False),
                )
                return {**problem, "_transitioned": True}
            raise RuntimeError("Every task-10 candidate repeats a recent fingerprint")

    async def task10_state(self, telegram_user_id: int) -> dict[str, object] | None:
        row = await self._pool.fetchrow(
            """SELECT s.state, p.snapshot FROM sessions s JOIN users u ON u.id = s.user_id
               LEFT JOIN issued_problems p ON p.id = s.active_problem_id
               WHERE u.telegram_user_id = $1 AND s.mode = 'task10' AND s.finished_at IS NULL
               ORDER BY s.started_at DESC LIMIT 1""",
            telegram_user_id,
        )
        return (
            {"state": _json_object(row["state"]), "problem": _json_object(row["snapshot"])}
            if row and row["snapshot"]
            else None
        )

    async def set_task10_prompt_message(
        self,
        telegram_user_id: int,
        expected_problem_id: str,
        message_id: int,
        expected_status: str | None = None,
    ) -> bool:
        async with self._pool.acquire() as connection, connection.transaction():
            row = await connection.fetchrow(
                """SELECT s.id, s.state, s.active_problem_id
                   FROM sessions s JOIN users u ON u.id=s.user_id
                   WHERE u.telegram_user_id=$1 AND s.mode='task10' AND s.finished_at IS NULL
                   ORDER BY s.started_at DESC LIMIT 1 FOR UPDATE OF s""",
                telegram_user_id,
            )
            if row is None or str(row["active_problem_id"]) != expected_problem_id:
                return False
            state = _json_object(row["state"])
            if expected_status is not None and state.get("status") != expected_status:
                return False
            current = state.get("input_prompt_message_id")
            if isinstance(current, int) and message_id < current:
                return False
            state["input_prompt_message_id"] = message_id
            await connection.execute(
                "UPDATE sessions SET state=$2::jsonb WHERE id=$1", row["id"], json.dumps(state)
            )
            return True

    async def set_task10_condition_message(
        self, telegram_user_id: int, expected_problem_id: str, message_id: int
    ) -> bool:
        async with self._pool.acquire() as connection, connection.transaction():
            row = await connection.fetchrow(
                """SELECT s.id, s.state, s.active_problem_id
                   FROM sessions s JOIN users u ON u.id=s.user_id
                   WHERE u.telegram_user_id=$1 AND s.mode='task10' AND s.finished_at IS NULL
                   ORDER BY s.started_at DESC LIMIT 1 FOR UPDATE OF s""",
                telegram_user_id,
            )
            if row is None or str(row["active_problem_id"]) != expected_problem_id:
                return False
            state = _json_object(row["state"])
            state["problem_prompt_message_id"] = message_id
            state["input_prompt_message_id"] = message_id
            await connection.execute(
                "UPDATE sessions SET state=$2::jsonb WHERE id=$1", row["id"], json.dumps(state)
            )
            return True

    async def task10_attempt(
        self,
        telegram_user_id: int,
        expected_problem_id: str,
        raw_answer: str,
        is_correct: bool,
        telegram_message_id: int | None = None,
        expected_prompt_message_id: int | None = None,
    ) -> dict[str, object] | None:
        async with self._pool.acquire() as connection, connection.transaction():
            user = await connection.fetchrow(
                "SELECT id, current_state FROM users WHERE telegram_user_id=$1 FOR UPDATE",
                telegram_user_id,
            )
            if user is None:
                return None
            row = await connection.fetchrow(
                """SELECT s.id AS session_id, s.state, s.active_problem_id, p.user_id, p.snapshot
                   FROM sessions s JOIN issued_problems p ON p.id=s.active_problem_id
                   WHERE s.user_id=$1 AND s.mode='task10' AND s.finished_at IS NULL
                   ORDER BY s.started_at DESC LIMIT 1 FOR UPDATE OF s""",
                user["id"],
            )
            if row is None:
                return None
            if str(row["active_problem_id"]) != expected_problem_id:
                return {"status": "stale", "attempt": 0}
            state, user_state = _json_object(row["state"]), _json_object(user["current_state"])
            if user_state.get("screen") != "task10":
                return {"status": "stale", "attempt": 0}
            if (
                expected_prompt_message_id is not None
                and state.get("problem_prompt_message_id", state.get("input_prompt_message_id"))
                != expected_prompt_message_id
            ):
                return {"status": "stale", "attempt": 0}
            if (
                telegram_message_id is not None
                and expected_prompt_message_id is not None
                and telegram_message_id <= expected_prompt_message_id
            ):
                return {"status": "stale", "attempt": 0}
            if telegram_message_id is not None:
                duplicate = await connection.fetchval(
                    "SELECT 1 FROM attempts WHERE user_id=$1 AND telegram_message_id=$2",
                    row["user_id"],
                    telegram_message_id,
                )
                if duplicate is not None:
                    return {"status": "duplicate", "attempt": 0}
            if state.get("status") != "active":
                return {
                    "status": str(state.get("status", "finished")),
                    "attempt": 0,
                    "problem": _json_object(row["snapshot"]),
                }
            attempt = _state_int(state, "attempts") + 1
            if attempt > 2:
                return {
                    "status": "finished",
                    "attempt": 2,
                    "problem": _json_object(row["snapshot"]),
                }
            status = "solved" if is_correct else ("failed" if attempt == 2 else "active")
            await connection.execute(
                """INSERT INTO attempts
                   (problem_id,user_id,attempt_no,raw_answer,normalized_answer,is_correct,used_hint,telegram_message_id)
                   VALUES ($1,$2,$3,$4,$4,$5,$6,$7)""",
                row["active_problem_id"],
                row["user_id"],
                attempt,
                raw_answer[:200],
                is_correct,
                bool(state.get("used_hint", False)),
                telegram_message_id,
            )
            state.update({"status": status, "attempts": attempt})
            if status in {"solved", "failed"}:
                await connection.execute(
                    "UPDATE issued_problems SET outcome=$2 WHERE id=$1",
                    row["active_problem_id"],
                    status,
                )
            await connection.execute(
                "UPDATE sessions SET state=$2::jsonb WHERE id=$1",
                row["session_id"],
                json.dumps(state),
            )
            return {"status": status, "attempt": attempt, "problem": _json_object(row["snapshot"])}

    async def task10_hint(
        self,
        telegram_user_id: int,
        expected_problem_id: str,
        expected_prompt_message_id: int | None = None,
    ) -> str | None:
        async with self._pool.acquire() as connection, connection.transaction():
            user = await connection.fetchrow(
                "SELECT current_state FROM users WHERE telegram_user_id=$1 FOR UPDATE",
                telegram_user_id,
            )
            if user is None or _json_object(user["current_state"]).get("screen") != "task10":
                return None
            row = await connection.fetchrow(
                """SELECT s.id,s.state,s.active_problem_id,p.snapshot
                   FROM sessions s JOIN users u ON u.id=s.user_id
                   JOIN issued_problems p ON p.id=s.active_problem_id
                   WHERE u.telegram_user_id=$1 AND s.mode='task10' AND s.finished_at IS NULL
                   ORDER BY s.started_at DESC LIMIT 1 FOR UPDATE OF s""",
                telegram_user_id,
            )
            if row is None or str(row["active_problem_id"]) != expected_problem_id:
                return None
            state, problem = _json_object(row["state"]), _json_object(row["snapshot"])
            if (
                expected_prompt_message_id is not None
                and state.get("input_prompt_message_id") != expected_prompt_message_id
            ):
                return None
            hints = problem.get("hints", [])
            used = _state_int(state, "hints_used")
            if state.get("status") != "active" or not isinstance(hints, list) or used >= len(hints):
                return None
            state.update({"hints_used": used + 1, "used_hint": True})
            await connection.execute(
                "UPDATE sessions SET state=$2::jsonb WHERE id=$1", row["id"], json.dumps(state)
            )
            await connection.execute(
                "UPDATE issued_problems SET hints_used=$2 WHERE id=$1",
                row["active_problem_id"],
                used + 1,
            )
            return str(hints[used])

    async def task10_reveal_solution(
        self,
        telegram_user_id: int,
        expected_problem_id: str,
        expected_prompt_message_id: int | None = None,
    ) -> dict[str, object] | None:
        async with self._pool.acquire() as connection, connection.transaction():
            user = await connection.fetchrow(
                "SELECT current_state FROM users WHERE telegram_user_id=$1 FOR UPDATE",
                telegram_user_id,
            )
            if user is None or _json_object(user["current_state"]).get("screen") != "task10":
                return None
            row = await connection.fetchrow(
                """SELECT s.id,s.state,s.active_problem_id,p.snapshot
                   FROM sessions s JOIN users u ON u.id=s.user_id
                   JOIN issued_problems p ON p.id=s.active_problem_id
                   WHERE u.telegram_user_id=$1 AND s.mode='task10' AND s.finished_at IS NULL
                   ORDER BY s.started_at DESC LIMIT 1 FOR UPDATE OF s""",
                telegram_user_id,
            )
            if row is None or str(row["active_problem_id"]) != expected_problem_id:
                return None
            state, problem = _json_object(row["state"]), _json_object(row["snapshot"])
            if (
                expected_prompt_message_id is not None
                and state.get("input_prompt_message_id") != expected_prompt_message_id
            ):
                return None
            status = str(state.get("status", ""))
            if status == "active":
                state["status"] = "solution_viewed"
                await connection.execute(
                    "UPDATE sessions SET state=$2::jsonb WHERE id=$1", row["id"], json.dumps(state)
                )
                await connection.execute(
                    """UPDATE issued_problems SET outcome='solution_viewed',
                       solution_viewed_at=now() WHERE id=$1""",
                    row["active_problem_id"],
                )
            else:
                await connection.execute(
                    """UPDATE issued_problems SET solution_viewed_at=COALESCE(
                       solution_viewed_at,now()) WHERE id=$1""",
                    row["active_problem_id"],
                )
            return {"problem": problem, "status": status}

    async def task10_progress(self, telegram_user_id: int) -> dict[str, int]:
        row = await self._pool.fetchrow(
            """SELECT count(DISTINCT p.id)::int AS issued,
                      count(DISTINCT p.id) FILTER (WHERE a.problem_id IS NOT NULL)::int AS answered,
                      count(DISTINCT p.id) FILTER (WHERE p.outcome='solved')::int AS correct,
                      count(DISTINCT p.id) FILTER (WHERE p.outcome='solved' AND EXISTS
                          (SELECT 1 FROM attempts a1 WHERE a1.problem_id=p.id
                           AND a1.attempt_no=1 AND a1.is_correct))::int AS solved_first_try,
                      count(DISTINCT p.id) FILTER (WHERE p.outcome='solved' AND EXISTS
                          (SELECT 1 FROM attempts a2 WHERE a2.problem_id=p.id
                           AND a2.attempt_no=2 AND a2.is_correct))::int AS solved_second_try,
                      count(a.id)::int AS attempts,
                      count(a.id) FILTER (WHERE a.attempt_no=1)::int AS first_attempts,
                      count(a.id) FILTER (WHERE a.attempt_no=2)::int AS second_attempts,
                      COALESCE((SELECT sum(p2.hints_used) FROM issued_problems p2
                                JOIN sessions s2 ON s2.id=p2.session_id AND s2.mode='task10'
                                WHERE p2.user_id=u.id),0)::int AS hints_used,
                      count(DISTINCT p.id) FILTER
                          (WHERE p.solution_viewed_at IS NOT NULL)::int AS solutions_viewed,
                      count(DISTINCT p.id) FILTER (WHERE p.outcome='skipped')::int AS skipped
               FROM users u LEFT JOIN issued_problems p ON p.user_id=u.id
               LEFT JOIN attempts a ON a.problem_id=p.id
               WHERE u.telegram_user_id=$1 AND (p.id IS NULL OR EXISTS
                   (SELECT 1 FROM sessions s WHERE s.id=p.session_id AND s.mode='task10'))
               GROUP BY u.id""",
            telegram_user_id,
        )
        return (
            dict(row)
            if row
            else {
                key: 0
                for key in (
                    "issued",
                    "answered",
                    "correct",
                    "solved_first_try",
                    "solved_second_try",
                    "attempts",
                    "first_attempts",
                    "second_attempts",
                    "hints_used",
                    "solutions_viewed",
                    "skipped",
                )
            }
        )


class _Task14PostgresMixin:
    _pool: asyncpg.Pool

    async def register_user(self, telegram_user_id: int) -> None:
        raise NotImplementedError

    async def ensure_task14_session(self, telegram_user_id: int) -> str:
        await self.register_user(telegram_user_id)
        async with self._pool.acquire() as connection, connection.transaction():
            user_id = await connection.fetchval(
                "SELECT id FROM users WHERE telegram_user_id = $1 FOR UPDATE", telegram_user_id
            )
            existing = await connection.fetchval(
                "SELECT id FROM sessions WHERE user_id = $1 AND mode = 'task14' "
                "AND finished_at IS NULL ORDER BY started_at DESC LIMIT 1",
                user_id,
            )
            if existing is not None:
                return str(existing)
            created = await connection.fetchval(
                "INSERT INTO sessions (user_id, mode, state) VALUES ($1, 'task14', '{}'::jsonb) "
                "RETURNING id",
                user_id,
            )
            return str(created)

    async def advance_task14_problem(
        self,
        telegram_user_id: int,
        expected_problem_id: str | None,
        candidates: list[dict[str, object]],
        expected_screen: str | None = None,
        expected_prompt_message_id: int | None = None,
        skip_active: bool = False,
    ) -> dict[str, object]:
        async with self._pool.acquire() as connection, connection.transaction():
            user = await connection.fetchrow(
                "SELECT id, current_state FROM users WHERE telegram_user_id = $1 FOR UPDATE",
                telegram_user_id,
            )
            if user is None:
                raise RuntimeError("Task-14 user does not exist")
            user_state = _json_object(user["current_state"])
            if expected_screen is not None and user_state.get("screen") != expected_screen:
                return {"_transitioned": False, "_stale_screen": True}
            session = await connection.fetchrow(
                """SELECT id, active_problem_id, state FROM sessions
                   WHERE user_id = $1 AND mode = 'task14' AND finished_at IS NULL
                   ORDER BY started_at DESC LIMIT 1 FOR UPDATE""",
                user["id"],
            )
            if session is None:
                raise RuntimeError("Task-14 session does not exist")
            state = _json_object(session["state"])
            if expected_prompt_message_id is not None and (
                state.get("input_prompt_message_id") != expected_prompt_message_id
            ):
                return {"_transitioned": False, "_stale_screen": True}
            active_id = str(session["active_problem_id"]) if session["active_problem_id"] else None
            if active_id is not None:
                current_row = await connection.fetchrow(
                    "SELECT snapshot FROM issued_problems WHERE id = $1",
                    session["active_problem_id"],
                )
                if current_row is None:
                    raise RuntimeError("Active task-14 snapshot is missing")
                current = _json_object(current_row["snapshot"])
                if expected_problem_id != active_id or skip_active != (
                    state.get("status") == "active"
                ):
                    return {**current, "_transitioned": False}
                if skip_active:
                    await connection.execute(
                        "UPDATE issued_problems SET outcome = 'skipped' WHERE id = $1",
                        session["active_problem_id"],
                    )
            elif expected_problem_id is not None:
                raise RuntimeError("Expected active task-14 problem is missing")
            if not candidates:
                raise RuntimeError("No task-14 candidates available")
            recent_value = state.get("recent_fingerprints", [])
            recent_order = (
                [x for x in recent_value if isinstance(x, str)]
                if isinstance(recent_value, list)
                else []
            )
            recent = set(recent_order)
            rejected = 0
            for candidate in candidates:
                fingerprint = str(candidate["fingerprint"])
                if fingerprint in recent:
                    rejected += 1
                    continue
                problem = dict(candidate)
                family_queue = problem.pop("_family_queue_after", [])
                last_family = problem.pop("_last_family_after", None)
                problem_id = UUID(str(problem["problem_id"]))
                await connection.execute(
                    """INSERT INTO issued_problems
                       (id, user_id, session_id, family_id, generator_version, seed,
                        fingerprint, shape_fingerprint, snapshot, selection_attempts, outcome)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10, 'issued')""",
                    problem_id,
                    user["id"],
                    session["id"],
                    problem["family_id"],
                    problem["generator_version"],
                    problem["seed"],
                    fingerprint,
                    problem["family_id"],
                    json.dumps(problem, ensure_ascii=False),
                    problem.get("selection_attempts", 1),
                )
                next_state = {
                    "status": "active",
                    "attempts": 0,
                    "hints_used": 0,
                    "used_hint": False,
                    "family_queue": family_queue if isinstance(family_queue, list) else [],
                    "last_family_id": last_family if isinstance(last_family, str) else None,
                    "recent_fingerprints": [*recent_order, fingerprint][-30:],
                    "selection_dedupe_rejections": _state_int(state, "selection_dedupe_rejections")
                    + rejected,
                }
                await connection.execute(
                    "UPDATE sessions SET active_problem_id = $2, state = $3::jsonb WHERE id = $1",
                    session["id"],
                    problem_id,
                    json.dumps(next_state, ensure_ascii=False),
                )
                return {**problem, "_transitioned": True}
            raise RuntimeError("Every task-14 candidate repeats a recent fingerprint")

    async def task14_state(self, telegram_user_id: int) -> dict[str, object] | None:
        row = await self._pool.fetchrow(
            """SELECT s.state, p.snapshot FROM sessions s JOIN users u ON u.id = s.user_id
               LEFT JOIN issued_problems p ON p.id = s.active_problem_id
               WHERE u.telegram_user_id = $1 AND s.mode = 'task14' AND s.finished_at IS NULL
               ORDER BY s.started_at DESC LIMIT 1""",
            telegram_user_id,
        )
        return (
            {"state": _json_object(row["state"]), "problem": _json_object(row["snapshot"])}
            if row and row["snapshot"]
            else None
        )

    async def set_task14_prompt_message(
        self,
        telegram_user_id: int,
        expected_problem_id: str,
        message_id: int,
        expected_status: str | None = None,
    ) -> bool:
        async with self._pool.acquire() as connection, connection.transaction():
            row = await connection.fetchrow(
                """SELECT s.id, s.state, s.active_problem_id
                   FROM sessions s JOIN users u ON u.id=s.user_id
                   WHERE u.telegram_user_id=$1 AND s.mode='task14' AND s.finished_at IS NULL
                   ORDER BY s.started_at DESC LIMIT 1 FOR UPDATE OF s""",
                telegram_user_id,
            )
            if row is None or str(row["active_problem_id"]) != expected_problem_id:
                return False
            state = _json_object(row["state"])
            if expected_status is not None and state.get("status") != expected_status:
                return False
            current = state.get("input_prompt_message_id")
            if isinstance(current, int) and message_id < current:
                return False
            state["input_prompt_message_id"] = message_id
            await connection.execute(
                "UPDATE sessions SET state=$2::jsonb WHERE id=$1", row["id"], json.dumps(state)
            )
            return True

    async def set_task14_condition_message(
        self, telegram_user_id: int, expected_problem_id: str, message_id: int
    ) -> bool:
        async with self._pool.acquire() as connection, connection.transaction():
            row = await connection.fetchrow(
                """SELECT s.id, s.state, s.active_problem_id
                   FROM sessions s JOIN users u ON u.id=s.user_id
                   WHERE u.telegram_user_id=$1 AND s.mode='task14' AND s.finished_at IS NULL
                   ORDER BY s.started_at DESC LIMIT 1 FOR UPDATE OF s""",
                telegram_user_id,
            )
            if row is None or str(row["active_problem_id"]) != expected_problem_id:
                return False
            state = _json_object(row["state"])
            state["problem_prompt_message_id"] = message_id
            state["input_prompt_message_id"] = message_id
            await connection.execute(
                "UPDATE sessions SET state=$2::jsonb WHERE id=$1", row["id"], json.dumps(state)
            )
            return True

    async def task14_attempt(
        self,
        telegram_user_id: int,
        expected_problem_id: str,
        raw_answer: str,
        is_correct: bool,
        telegram_message_id: int | None = None,
        expected_prompt_message_id: int | None = None,
    ) -> dict[str, object] | None:
        async with self._pool.acquire() as connection, connection.transaction():
            user = await connection.fetchrow(
                "SELECT id, current_state FROM users WHERE telegram_user_id=$1 FOR UPDATE",
                telegram_user_id,
            )
            if user is None:
                return None
            row = await connection.fetchrow(
                """SELECT s.id AS session_id, s.state, s.active_problem_id, p.user_id, p.snapshot
                   FROM sessions s JOIN issued_problems p ON p.id=s.active_problem_id
                   WHERE s.user_id=$1 AND s.mode='task14' AND s.finished_at IS NULL
                   ORDER BY s.started_at DESC LIMIT 1 FOR UPDATE OF s""",
                user["id"],
            )
            if row is None:
                return None
            if str(row["active_problem_id"]) != expected_problem_id:
                return {"status": "stale", "attempt": 0}
            state, user_state = _json_object(row["state"]), _json_object(user["current_state"])
            if user_state.get("screen") != "task14":
                return {"status": "stale", "attempt": 0}
            if (
                expected_prompt_message_id is not None
                and state.get("problem_prompt_message_id", state.get("input_prompt_message_id"))
                != expected_prompt_message_id
            ):
                return {"status": "stale", "attempt": 0}
            if (
                telegram_message_id is not None
                and expected_prompt_message_id is not None
                and telegram_message_id <= expected_prompt_message_id
            ):
                return {"status": "stale", "attempt": 0}
            if telegram_message_id is not None:
                duplicate = await connection.fetchval(
                    "SELECT 1 FROM attempts WHERE user_id=$1 AND telegram_message_id=$2",
                    row["user_id"],
                    telegram_message_id,
                )
                if duplicate is not None:
                    return {"status": "duplicate", "attempt": 0}
            if state.get("status") != "active":
                return {
                    "status": str(state.get("status", "finished")),
                    "attempt": 0,
                    "problem": _json_object(row["snapshot"]),
                }
            attempt = _state_int(state, "attempts") + 1
            if attempt > 2:
                return {
                    "status": "finished",
                    "attempt": 2,
                    "problem": _json_object(row["snapshot"]),
                }
            status = "solved" if is_correct else ("failed" if attempt == 2 else "active")
            await connection.execute(
                """INSERT INTO attempts
                   (problem_id,user_id,attempt_no,raw_answer,normalized_answer,is_correct,used_hint,telegram_message_id)
                   VALUES ($1,$2,$3,$4,$4,$5,$6,$7)""",
                row["active_problem_id"],
                row["user_id"],
                attempt,
                raw_answer[:200],
                is_correct,
                bool(state.get("used_hint", False)),
                telegram_message_id,
            )
            state.update({"status": status, "attempts": attempt})
            if status in {"solved", "failed"}:
                await connection.execute(
                    "UPDATE issued_problems SET outcome=$2 WHERE id=$1",
                    row["active_problem_id"],
                    status,
                )
            await connection.execute(
                "UPDATE sessions SET state=$2::jsonb WHERE id=$1",
                row["session_id"],
                json.dumps(state),
            )
            return {"status": status, "attempt": attempt, "problem": _json_object(row["snapshot"])}

    async def task14_hint(
        self,
        telegram_user_id: int,
        expected_problem_id: str,
        expected_prompt_message_id: int | None = None,
    ) -> str | None:
        async with self._pool.acquire() as connection, connection.transaction():
            user = await connection.fetchrow(
                "SELECT current_state FROM users WHERE telegram_user_id=$1 FOR UPDATE",
                telegram_user_id,
            )
            if user is None or _json_object(user["current_state"]).get("screen") != "task14":
                return None
            row = await connection.fetchrow(
                """SELECT s.id,s.state,s.active_problem_id,p.snapshot
                   FROM sessions s JOIN users u ON u.id=s.user_id
                   JOIN issued_problems p ON p.id=s.active_problem_id
                   WHERE u.telegram_user_id=$1 AND s.mode='task14' AND s.finished_at IS NULL
                   ORDER BY s.started_at DESC LIMIT 1 FOR UPDATE OF s""",
                telegram_user_id,
            )
            if row is None or str(row["active_problem_id"]) != expected_problem_id:
                return None
            state, problem = _json_object(row["state"]), _json_object(row["snapshot"])
            if (
                expected_prompt_message_id is not None
                and state.get("input_prompt_message_id") != expected_prompt_message_id
            ):
                return None
            hints = problem.get("hints", [])
            used = _state_int(state, "hints_used")
            if state.get("status") != "active" or not isinstance(hints, list) or used >= len(hints):
                return None
            state.update({"hints_used": used + 1, "used_hint": True})
            await connection.execute(
                "UPDATE sessions SET state=$2::jsonb WHERE id=$1", row["id"], json.dumps(state)
            )
            await connection.execute(
                "UPDATE issued_problems SET hints_used=$2 WHERE id=$1",
                row["active_problem_id"],
                used + 1,
            )
            return str(hints[used])

    async def task14_reveal_solution(
        self,
        telegram_user_id: int,
        expected_problem_id: str,
        expected_prompt_message_id: int | None = None,
    ) -> dict[str, object] | None:
        async with self._pool.acquire() as connection, connection.transaction():
            user = await connection.fetchrow(
                "SELECT current_state FROM users WHERE telegram_user_id=$1 FOR UPDATE",
                telegram_user_id,
            )
            if user is None or _json_object(user["current_state"]).get("screen") != "task14":
                return None
            row = await connection.fetchrow(
                """SELECT s.id,s.state,s.active_problem_id,p.snapshot
                   FROM sessions s JOIN users u ON u.id=s.user_id
                   JOIN issued_problems p ON p.id=s.active_problem_id
                   WHERE u.telegram_user_id=$1 AND s.mode='task14' AND s.finished_at IS NULL
                   ORDER BY s.started_at DESC LIMIT 1 FOR UPDATE OF s""",
                telegram_user_id,
            )
            if row is None or str(row["active_problem_id"]) != expected_problem_id:
                return None
            state, problem = _json_object(row["state"]), _json_object(row["snapshot"])
            if (
                expected_prompt_message_id is not None
                and state.get("input_prompt_message_id") != expected_prompt_message_id
            ):
                return None
            status = str(state.get("status", ""))
            if status == "active":
                state["status"] = "solution_viewed"
                await connection.execute(
                    "UPDATE sessions SET state=$2::jsonb WHERE id=$1", row["id"], json.dumps(state)
                )
                await connection.execute(
                    """UPDATE issued_problems SET outcome='solution_viewed',
                       solution_viewed_at=now() WHERE id=$1""",
                    row["active_problem_id"],
                )
            else:
                await connection.execute(
                    """UPDATE issued_problems SET solution_viewed_at=COALESCE(
                       solution_viewed_at,now()) WHERE id=$1""",
                    row["active_problem_id"],
                )
            return {"problem": problem, "status": status}

    async def task14_progress(self, telegram_user_id: int) -> dict[str, int]:
        row = await self._pool.fetchrow(
            """SELECT count(DISTINCT p.id)::int AS issued,
                      count(DISTINCT p.id) FILTER (WHERE a.problem_id IS NOT NULL)::int AS answered,
                      count(DISTINCT p.id) FILTER (WHERE p.outcome='solved')::int AS correct,
                      count(DISTINCT p.id) FILTER (WHERE p.outcome='solved' AND EXISTS
                          (SELECT 1 FROM attempts a1 WHERE a1.problem_id=p.id
                           AND a1.attempt_no=1 AND a1.is_correct))::int AS solved_first_try,
                      count(DISTINCT p.id) FILTER (WHERE p.outcome='solved' AND EXISTS
                          (SELECT 1 FROM attempts a2 WHERE a2.problem_id=p.id
                           AND a2.attempt_no=2 AND a2.is_correct))::int AS solved_second_try,
                      count(a.id)::int AS attempts,
                      count(a.id) FILTER (WHERE a.attempt_no=1)::int AS first_attempts,
                      count(a.id) FILTER (WHERE a.attempt_no=2)::int AS second_attempts,
                      COALESCE((SELECT sum(p2.hints_used) FROM issued_problems p2
                                JOIN sessions s2 ON s2.id=p2.session_id AND s2.mode='task14'
                                WHERE p2.user_id=u.id),0)::int AS hints_used,
                      count(DISTINCT p.id) FILTER
                          (WHERE p.solution_viewed_at IS NOT NULL)::int AS solutions_viewed,
                      count(DISTINCT p.id) FILTER (WHERE p.outcome='skipped')::int AS skipped
               FROM users u LEFT JOIN issued_problems p ON p.user_id=u.id
               LEFT JOIN attempts a ON a.problem_id=p.id
               WHERE u.telegram_user_id=$1 AND (p.id IS NULL OR EXISTS
                   (SELECT 1 FROM sessions s WHERE s.id=p.session_id AND s.mode='task14'))
               GROUP BY u.id""",
            telegram_user_id,
        )
        return (
            dict(row)
            if row
            else {
                key: 0
                for key in (
                    "issued",
                    "answered",
                    "correct",
                    "solved_first_try",
                    "solved_second_try",
                    "attempts",
                    "first_attempts",
                    "second_attempts",
                    "hints_used",
                    "solutions_viewed",
                    "skipped",
                )
            }
        )


class PostgresRepository(_Task10PostgresMixin, _Task14PostgresMixin):
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def register_user(self, telegram_user_id: int) -> None:
        await self._pool.execute(
            """INSERT INTO users (telegram_user_id) VALUES ($1)
               ON CONFLICT (telegram_user_id) DO NOTHING""",
            telegram_user_id,
        )

    async def save_user_state(self, telegram_user_id: int, screen: str) -> None:
        await self._pool.execute(
            """UPDATE users SET current_state = CASE
                 WHEN $2 IN ('task6', 'task9', 'task10', 'task14') THEN jsonb_build_object(
                   'screen', $2::text, 'resume_mode', $2::text)
                 ELSE jsonb_set(COALESCE(current_state, '{}'::jsonb), '{screen}',
                                to_jsonb($2::text), true)
               END WHERE telegram_user_id = $1""",
            telegram_user_id,
            screen,
        )

    async def transition_task_screen(
        self,
        telegram_user_id: int,
        mode: str,
        expected_problem_id: str,
        target_screen: str,
        expected_prompt_message_id: int | None = None,
    ) -> bool:
        if mode not in {"task6", "task9", "task10", "task14"}:
            return False
        async with self._pool.acquire() as connection, connection.transaction():
            user = await connection.fetchrow(
                "SELECT id, current_state FROM users WHERE telegram_user_id = $1 FOR UPDATE",
                telegram_user_id,
            )
            if user is None or _json_object(user["current_state"]).get("screen") != mode:
                return False
            session = await connection.fetchrow(
                """SELECT id, active_problem_id, state FROM sessions
                   WHERE user_id = $1 AND mode = $2 AND finished_at IS NULL
                   ORDER BY started_at DESC LIMIT 1 FOR UPDATE""",
                user["id"],
                mode,
            )
            if (
                session is None
                or str(session["active_problem_id"]) != expected_problem_id
                or (
                    expected_prompt_message_id is not None
                    and _json_object(session["state"]).get("input_prompt_message_id")
                    != expected_prompt_message_id
                )
            ):
                return False
            await connection.execute(
                """UPDATE users SET current_state = jsonb_set(
                       COALESCE(current_state, '{}'::jsonb), '{screen}', to_jsonb($2::text), true)
                   WHERE id = $1""",
                user["id"],
                target_screen,
            )
            return True

    async def user_state(self, telegram_user_id: int) -> str | None:
        state = await self._pool.fetchval(
            "SELECT current_state ->> 'screen' FROM users WHERE telegram_user_id = $1",
            telegram_user_id,
        )
        return cast(str | None, state)

    async def last_training_mode(self, telegram_user_id: int) -> str | None:
        value = await self._pool.fetchval(
            "SELECT current_state ->> 'resume_mode' FROM users WHERE telegram_user_id = $1",
            telegram_user_id,
        )
        return cast(str | None, value)

    async def current_session(self, telegram_user_id: int) -> dict[str, object] | None:
        row = await self._pool.fetchrow(
            """SELECT s.id, s.mode, s.state FROM sessions s
               JOIN users u ON u.id = s.user_id
               WHERE u.telegram_user_id = $1 AND s.finished_at IS NULL
               ORDER BY s.started_at DESC LIMIT 1""",
            telegram_user_id,
        )
        return dict(row) if row is not None else None

    async def ensure_task6_session(self, telegram_user_id: int) -> str:
        await self.register_user(telegram_user_id)
        async with self._pool.acquire() as connection, connection.transaction():
            user = await connection.fetchrow(
                "SELECT id FROM users WHERE telegram_user_id = $1 FOR UPDATE",
                telegram_user_id,
            )
            existing = await connection.fetchval(
                """SELECT id FROM sessions
                   WHERE user_id = $1 AND mode = 'task6' AND finished_at IS NULL
                   ORDER BY started_at DESC LIMIT 1""",
                user["id"],
            )
            if existing is not None:
                return str(existing)
            created = await connection.fetchval(
                """INSERT INTO sessions (user_id, mode, state)
                   VALUES ($1, 'task6', '{}'::jsonb) RETURNING id""",
                user["id"],
            )
            return str(created)

    async def ensure_task9_session(self, telegram_user_id: int) -> str:
        await self.register_user(telegram_user_id)
        async with self._pool.acquire() as connection, connection.transaction():
            user_id = await connection.fetchval(
                "SELECT id FROM users WHERE telegram_user_id = $1 FOR UPDATE", telegram_user_id
            )
            existing = await connection.fetchval(
                "SELECT id FROM sessions WHERE user_id = $1 AND mode = 'task9' "
                "AND finished_at IS NULL ORDER BY started_at DESC LIMIT 1",
                user_id,
            )
            if existing is not None:
                return str(existing)
            created = await connection.fetchval(
                "INSERT INTO sessions (user_id, mode, state) VALUES ($1, 'task9', '{}'::jsonb) "
                "RETURNING id",
                user_id,
            )
            return str(created)

    async def advance_task9_problem(
        self,
        telegram_user_id: int,
        expected_problem_id: str | None,
        candidates: list[dict[str, object]],
        expected_screen: str | None = None,
        expected_prompt_message_id: int | None = None,
        skip_active: bool = False,
    ) -> dict[str, object]:
        async with self._pool.acquire() as connection, connection.transaction():
            user = await connection.fetchrow(
                "SELECT id, current_state FROM users WHERE telegram_user_id = $1 FOR UPDATE",
                telegram_user_id,
            )
            if user is None:
                raise RuntimeError("Task-9 user does not exist")
            if expected_screen is not None:
                if _json_object(user["current_state"]).get("screen") != expected_screen:
                    return {"_transitioned": False, "_stale_screen": True}
            row = await connection.fetchrow(
                """SELECT s.id, s.active_problem_id, s.state, u.id AS user_id
                   FROM sessions s JOIN users u ON u.id = s.user_id
                   WHERE u.telegram_user_id = $1 AND s.mode = 'task9'
                     AND s.finished_at IS NULL
                   ORDER BY s.started_at DESC LIMIT 1 FOR UPDATE OF s""",
                telegram_user_id,
            )
            if row is None:
                raise RuntimeError("Task-9 session does not exist")
            state = _json_object(row["state"])
            if (
                expected_prompt_message_id is not None
                and state.get("input_prompt_message_id") != expected_prompt_message_id
            ):
                return {"_transitioned": False, "_stale_screen": True}
            active_id = str(row["active_problem_id"]) if row["active_problem_id"] else None
            if active_id is not None:
                saved = await connection.fetchrow(
                    "SELECT snapshot FROM issued_problems WHERE id = $1", row["active_problem_id"]
                )
                if saved is None:
                    raise RuntimeError("Active task-9 snapshot is missing")
                current = _json_object(saved["snapshot"])
                if expected_problem_id != active_id:
                    return {**current, "_transitioned": False}
                if skip_active != (state.get("status") == "active"):
                    return {**current, "_transitioned": False}
            elif expected_problem_id is not None:
                raise RuntimeError("Expected active task-9 problem is missing")

            recent_value = state.get("recent_fingerprints", [])
            recent_order = (
                [value for value in recent_value if isinstance(value, str)]
                if isinstance(recent_value, list)
                else []
            )
            recent = set(recent_order)
            for candidate in candidates:
                fingerprint = str(candidate["fingerprint"])
                if fingerprint in recent:
                    continue
                problem = dict(candidate)
                queue_after = problem.pop("_family_queue_after", [])
                last_group = problem.pop("_last_group_after", None)
                group_run_length = problem.pop("_group_run_length_after", 0)
                problem_id = UUID(str(problem["problem_id"]))
                await connection.execute(
                    """INSERT INTO issued_problems
                       (id, user_id, session_id, family_id, generator_version, seed,
                        fingerprint, shape_fingerprint, snapshot, selection_attempts, outcome)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10, 'issued')""",
                    problem_id,
                    row["user_id"],
                    row["id"],
                    problem["family_id"],
                    problem["generator_version"],
                    problem["seed"],
                    fingerprint,
                    problem["reference_structure_id"],
                    json.dumps(problem, ensure_ascii=False),
                    _state_int(problem, "selection_attempts", 1),
                )
                if active_id is not None and skip_active:
                    await connection.execute(
                        "UPDATE issued_problems SET outcome = 'skipped' WHERE id = $1",
                        row["active_problem_id"],
                    )
                next_state = {
                    "status": "active",
                    "attempts": 0,
                    "hints_used": 0,
                    "used_hint": False,
                    "family_queue": queue_after,
                    "recent_fingerprints": [*recent_order, fingerprint][-30:],
                    "last_family_id": problem["family_id"],
                    "last_group": last_group,
                    "group_run_length": group_run_length,
                }
                await connection.execute(
                    "UPDATE sessions SET active_problem_id = $2, state = $3::jsonb WHERE id = $1",
                    row["id"],
                    problem_id,
                    json.dumps(next_state),
                )
                return {**problem, "_transitioned": True}
            raise RuntimeError("No distinct task-9 problem could be constructed")

    async def task9_state(self, telegram_user_id: int) -> dict[str, object] | None:
        row = await self._pool.fetchrow(
            """SELECT s.id, s.state, p.snapshot FROM sessions s
               JOIN users u ON u.id = s.user_id
               LEFT JOIN issued_problems p ON p.id = s.active_problem_id
               WHERE u.telegram_user_id = $1 AND s.mode = 'task9' AND s.finished_at IS NULL
               ORDER BY s.started_at DESC LIMIT 1""",
            telegram_user_id,
        )
        if row is None:
            return None
        return {
            "session_id": str(row["id"]),
            "state": _json_object(row["state"]),
            "problem": _json_object(row["snapshot"]) if row["snapshot"] is not None else None,
        }

    async def set_task9_prompt_message(
        self,
        telegram_user_id: int,
        expected_problem_id: str,
        message_id: int,
        expected_status: str | None = None,
    ) -> bool:
        async with self._pool.acquire() as connection, connection.transaction():
            row = await connection.fetchrow(
                """SELECT s.id, s.state, s.active_problem_id FROM sessions s
                   JOIN users u ON u.id = s.user_id
                   WHERE u.telegram_user_id = $1 AND s.mode = 'task9'
                     AND s.finished_at IS NULL
                   ORDER BY s.started_at DESC LIMIT 1 FOR UPDATE OF s""",
                telegram_user_id,
            )
            if row is None or str(row["active_problem_id"]) != expected_problem_id:
                return False
            state = _json_object(row["state"])
            if expected_status is not None and state.get("status") != expected_status:
                return False
            current_message_id = state.get("input_prompt_message_id")
            if isinstance(current_message_id, int) and message_id < current_message_id:
                return False
            state["input_prompt_message_id"] = message_id
            await connection.execute(
                "UPDATE sessions SET state = $2::jsonb WHERE id = $1",
                row["id"],
                json.dumps(state),
            )
            return True

    async def set_task9_condition_message(
        self, telegram_user_id: int, expected_problem_id: str, message_id: int
    ) -> bool:
        async with self._pool.acquire() as connection, connection.transaction():
            row = await connection.fetchrow(
                """SELECT s.id, s.state, s.active_problem_id FROM sessions s
                   JOIN users u ON u.id = s.user_id
                   WHERE u.telegram_user_id = $1 AND s.mode = 'task9'
                     AND s.finished_at IS NULL
                   ORDER BY s.started_at DESC LIMIT 1 FOR UPDATE OF s""",
                telegram_user_id,
            )
            if row is None or str(row["active_problem_id"]) != expected_problem_id:
                return False
            state = _json_object(row["state"])
            state["problem_prompt_message_id"] = message_id
            state["input_prompt_message_id"] = message_id
            await connection.execute(
                "UPDATE sessions SET state = $2::jsonb WHERE id = $1",
                row["id"],
                json.dumps(state),
            )
            return True

    async def task9_attempt(
        self,
        telegram_user_id: int,
        expected_problem_id: str,
        raw_answer: str,
        is_correct: bool,
        telegram_message_id: int | None = None,
        expected_prompt_message_id: int | None = None,
    ) -> dict[str, object] | None:
        async with self._pool.acquire() as connection, connection.transaction():
            user = await connection.fetchrow(
                "SELECT id, current_state FROM users WHERE telegram_user_id = $1 FOR UPDATE",
                telegram_user_id,
            )
            if user is None:
                return None
            row = await connection.fetchrow(
                """SELECT s.id AS session_id, s.state, s.active_problem_id, p.user_id,
                          p.snapshot
                   FROM sessions s JOIN issued_problems p ON p.id = s.active_problem_id
                   WHERE s.user_id = $1 AND s.mode = 'task9'
                     AND s.finished_at IS NULL
                   ORDER BY s.started_at DESC LIMIT 1 FOR UPDATE OF s""",
                user["id"],
            )
            if row is None:
                return None
            if str(row["active_problem_id"]) != expected_problem_id:
                return {"status": "stale", "attempt": 0}
            state = _json_object(row["state"])
            user_state = _json_object(user["current_state"])
            if user_state.get("screen") != "task9":
                return {"status": "stale", "attempt": 0}
            if expected_prompt_message_id is not None and (
                state.get("problem_prompt_message_id", state.get("input_prompt_message_id"))
                != expected_prompt_message_id
            ):
                return {"status": "stale", "attempt": 0}
            if telegram_message_id is not None and expected_prompt_message_id is not None:
                if telegram_message_id <= expected_prompt_message_id:
                    return {"status": "stale", "attempt": 0}
            if telegram_message_id is not None:
                duplicate = await connection.fetchval(
                    "SELECT 1 FROM attempts WHERE user_id = $1 AND telegram_message_id = $2",
                    row["user_id"],
                    telegram_message_id,
                )
                if duplicate is not None:
                    return {"status": "duplicate", "attempt": 0}
            if state.get("status") != "active":
                return {
                    "status": str(state.get("status", "finished")),
                    "attempt": 0,
                    "problem": _json_object(row["snapshot"]),
                }
            attempt = _state_int(state, "attempts") + 1
            if attempt > 2:
                return {
                    "status": "finished",
                    "attempt": 2,
                    "problem": _json_object(row["snapshot"]),
                }
            status = "solved" if is_correct else ("failed" if attempt == 2 else "active")
            await connection.execute(
                """INSERT INTO attempts
                   (problem_id, user_id, attempt_no, raw_answer, normalized_answer,
                    is_correct, used_hint, telegram_message_id)
                   VALUES ($1, $2, $3, $4, $4, $5, $6, $7)""",
                row["active_problem_id"],
                row["user_id"],
                attempt,
                raw_answer[:200],
                is_correct,
                bool(state.get("used_hint", False)),
                telegram_message_id,
            )
            state.update({"status": status, "attempts": attempt})
            if status in {"solved", "failed"}:
                await connection.execute(
                    "UPDATE issued_problems SET outcome = $2 WHERE id = $1",
                    row["active_problem_id"],
                    status,
                )
            await connection.execute(
                "UPDATE sessions SET state = $2::jsonb WHERE id = $1",
                row["session_id"],
                json.dumps(state),
            )
            return {"status": status, "attempt": attempt, "problem": _json_object(row["snapshot"])}

    async def task9_hint(
        self,
        telegram_user_id: int,
        expected_problem_id: str,
        expected_prompt_message_id: int | None = None,
    ) -> str | None:
        async with self._pool.acquire() as connection, connection.transaction():
            user = await connection.fetchrow(
                "SELECT current_state FROM users WHERE telegram_user_id = $1 FOR UPDATE",
                telegram_user_id,
            )
            if user is None or _json_object(user["current_state"]).get("screen") != "task9":
                return None
            row = await connection.fetchrow(
                """SELECT s.id, s.state, s.active_problem_id, p.snapshot FROM sessions s
                   JOIN users u ON u.id = s.user_id
                   JOIN issued_problems p ON p.id = s.active_problem_id
                   WHERE u.telegram_user_id = $1 AND s.mode = 'task9' AND s.finished_at IS NULL
                   ORDER BY s.started_at DESC LIMIT 1 FOR UPDATE OF s""",
                telegram_user_id,
            )
            if row is None or str(row["active_problem_id"]) != expected_problem_id:
                return None
            state, problem = _json_object(row["state"]), _json_object(row["snapshot"])
            if (
                expected_prompt_message_id is not None
                and state.get("input_prompt_message_id") != expected_prompt_message_id
            ):
                return None
            hints = problem.get("hints", [])
            used = _state_int(state, "hints_used")
            if state.get("status") != "active" or not isinstance(hints, list) or used >= len(hints):
                return None
            state.update({"hints_used": used + 1, "used_hint": True})
            await connection.execute(
                "UPDATE sessions SET state = $2::jsonb WHERE id = $1", row["id"], json.dumps(state)
            )
            await connection.execute(
                "UPDATE issued_problems SET hints_used = $2 WHERE id = $1",
                row["active_problem_id"],
                used + 1,
            )
            return str(hints[used])

    async def task9_reveal_solution(
        self,
        telegram_user_id: int,
        expected_problem_id: str,
        expected_prompt_message_id: int | None = None,
    ) -> dict[str, object] | None:
        async with self._pool.acquire() as connection, connection.transaction():
            user = await connection.fetchrow(
                "SELECT current_state FROM users WHERE telegram_user_id = $1 FOR UPDATE",
                telegram_user_id,
            )
            if user is None or _json_object(user["current_state"]).get("screen") != "task9":
                return None
            row = await connection.fetchrow(
                """SELECT s.id, s.state, s.active_problem_id, p.snapshot FROM sessions s
                   JOIN users u ON u.id = s.user_id
                   JOIN issued_problems p ON p.id = s.active_problem_id
                   WHERE u.telegram_user_id = $1 AND s.mode = 'task9' AND s.finished_at IS NULL
                   ORDER BY s.started_at DESC LIMIT 1 FOR UPDATE OF s""",
                telegram_user_id,
            )
            if row is None or str(row["active_problem_id"]) != expected_problem_id:
                return None
            state, problem = _json_object(row["state"]), _json_object(row["snapshot"])
            if (
                expected_prompt_message_id is not None
                and state.get("input_prompt_message_id") != expected_prompt_message_id
            ):
                return None
            status = str(state.get("status", ""))
            if status == "active":
                state["status"] = "solution_viewed"
                await connection.execute(
                    "UPDATE sessions SET state = $2::jsonb WHERE id = $1",
                    row["id"],
                    json.dumps(state),
                )
                await connection.execute(
                    "UPDATE issued_problems SET outcome = 'solution_viewed', "
                    "solution_viewed_at = now() WHERE id = $1",
                    row["active_problem_id"],
                )
            else:
                await connection.execute(
                    "UPDATE issued_problems SET solution_viewed_at = "
                    "COALESCE(solution_viewed_at, now()) WHERE id = $1",
                    row["active_problem_id"],
                )
            return {"problem": problem, "status": status}

    async def task9_progress(self, telegram_user_id: int) -> dict[str, int]:
        row = await self._pool.fetchrow(
            """SELECT count(DISTINCT p.id)::int AS issued,
                      count(DISTINCT p.id) FILTER (WHERE a.problem_id IS NOT NULL)::int AS answered,
                      count(DISTINCT p.id) FILTER (WHERE p.outcome = 'solved')::int AS correct,
                      count(DISTINCT p.id) FILTER (WHERE p.outcome = 'solved' AND EXISTS (
                        SELECT 1 FROM attempts a1 WHERE a1.problem_id = p.id
                          AND a1.attempt_no = 1 AND a1.is_correct
                      ))::int AS solved_first_try,
                      count(DISTINCT p.id) FILTER (WHERE p.outcome = 'solved' AND EXISTS (
                        SELECT 1 FROM attempts a2 WHERE a2.problem_id = p.id
                          AND a2.attempt_no = 2 AND a2.is_correct
                      ))::int AS solved_second_try,
                      count(a.id)::int AS attempts,
                      count(a.id) FILTER (WHERE a.attempt_no = 1)::int AS first_attempts,
                      count(a.id) FILTER (WHERE a.attempt_no = 2)::int AS second_attempts,
                      COALESCE((SELECT sum(p2.hints_used) FROM issued_problems p2
                        JOIN sessions s2 ON s2.id = p2.session_id AND s2.mode = 'task9'
                        WHERE p2.user_id = u.id), 0)::int AS hints_used,
                      count(DISTINCT p.id) FILTER (
                        WHERE p.solution_viewed_at IS NOT NULL)::int AS solutions_viewed,
                      count(DISTINCT p.id) FILTER (WHERE p.outcome = 'skipped')::int AS skipped
               FROM users u LEFT JOIN issued_problems p ON p.user_id = u.id
               LEFT JOIN attempts a ON a.problem_id = p.id
               WHERE u.telegram_user_id = $1 AND (p.id IS NULL OR EXISTS
                    (SELECT 1 FROM sessions s WHERE s.id = p.session_id AND s.mode = 'task9'))
               GROUP BY u.id""",
            telegram_user_id,
        )
        keys = (
            "issued",
            "answered",
            "correct",
            "solved_first_try",
            "solved_second_try",
            "attempts",
            "first_attempts",
            "second_attempts",
            "hints_used",
            "solutions_viewed",
            "skipped",
        )
        return {key: int(row[key]) for key in keys} if row is not None else {key: 0 for key in keys}

    async def advance_task6_problem(
        self,
        telegram_user_id: int,
        expected_problem_id: str | None,
        candidates: list[dict[str, object]],
        expected_screen: str | None = None,
        expected_prompt_message_id: int | None = None,
        skip_active: bool = False,
    ) -> dict[str, object]:
        async with self._pool.acquire() as connection, connection.transaction():
            user = await connection.fetchrow(
                "SELECT id, current_state FROM users WHERE telegram_user_id = $1 FOR UPDATE",
                telegram_user_id,
            )
            if user is None:
                raise RuntimeError("Task-6 user does not exist")
            if expected_screen is not None:
                if _json_object(user["current_state"]).get("screen") != expected_screen:
                    return {"_transitioned": False, "_stale_screen": True}
            row = await connection.fetchrow(
                """SELECT s.id, s.active_problem_id, s.state, u.id AS user_id
                   FROM sessions s JOIN users u ON u.id = s.user_id
                   WHERE u.telegram_user_id = $1 AND s.mode = 'task6'
                     AND s.finished_at IS NULL
                   ORDER BY s.started_at DESC LIMIT 1 FOR UPDATE OF s""",
                telegram_user_id,
            )
            if row is None:
                raise RuntimeError("Task-6 session does not exist")
            state = _json_object(row["state"])
            if (
                expected_prompt_message_id is not None
                and state.get("input_prompt_message_id") != expected_prompt_message_id
            ):
                return {"_transitioned": False, "_stale_screen": True}
            active_id = str(row["active_problem_id"]) if row["active_problem_id"] else None
            if active_id is not None:
                current_row = await connection.fetchrow(
                    "SELECT snapshot, fingerprint FROM issued_problems WHERE id = $1",
                    row["active_problem_id"],
                )
                if current_row is None:
                    raise RuntimeError("Active task-6 snapshot is missing")
                current = _json_object(current_row["snapshot"])
                if expected_problem_id is not None and active_id != expected_problem_id:
                    return {**current, "_transitioned": False}
                if skip_active != (state.get("status") == "active"):
                    return {**current, "_transitioned": False}
                if expected_problem_id is None and state.get("status") == "active":
                    return {**current, "_transitioned": False}
            elif expected_problem_id is not None:
                raise RuntimeError("Expected active task-6 problem is missing")

            if not candidates:
                raise RuntimeError("No distinct task-6 candidate could be constructed")

            previous_fingerprints = state.get("recent_fingerprints", [])
            recent_order = (
                [value for value in previous_fingerprints if isinstance(value, str)]
                if isinstance(previous_fingerprints, list)
                else []
            )
            recent = set(recent_order)
            rejected = 0
            for candidate in candidates:
                fingerprint = str(candidate["fingerprint"])
                if fingerprint in recent:
                    rejected += 1
                    continue
                problem = dict(candidate)
                queue_after = problem.pop("_family_queue_after", [])
                problem_id = UUID(str(problem["problem_id"]))
                selection_attempts_value = problem.get("selection_attempts", 1)
                selection_attempts = (
                    selection_attempts_value if isinstance(selection_attempts_value, int) else 1
                )
                await connection.execute(
                    """INSERT INTO issued_problems
                       (id, user_id, session_id, family_id, generator_version, seed,
                        fingerprint, shape_fingerprint, snapshot, selection_attempts,
                        outcome)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10, 'issued')""",
                    problem_id,
                    row["user_id"],
                    row["id"],
                    problem["family_id"],
                    problem["generator_version"],
                    problem["seed"],
                    fingerprint,
                    problem["reference_structure_id"],
                    json.dumps(problem, ensure_ascii=False),
                    selection_attempts,
                )
                if active_id is not None and skip_active:
                    await connection.execute(
                        "UPDATE issued_problems SET outcome = 'skipped' WHERE id = $1",
                        row["active_problem_id"],
                    )
                recent.add(fingerprint)
                ordered_recent = [*recent_order, fingerprint][-30:]
                next_state = {
                    "status": "active",
                    "attempts": 0,
                    "hints_used": 0,
                    "used_hint": False,
                    "family_queue": queue_after,
                    "recent_fingerprints": ordered_recent,
                    "selection_dedupe_rejections": (
                        _state_int(state, "selection_dedupe_rejections") + rejected
                    ),
                }
                await connection.execute(
                    "UPDATE sessions SET active_problem_id = $2, state = $3::jsonb WHERE id = $1",
                    row["id"],
                    problem_id,
                    json.dumps(next_state),
                )
                return {**problem, "_transitioned": True}
            raise RuntimeError("Every task-6 candidate repeats a recently issued fingerprint")

    async def task6_state(self, telegram_user_id: int) -> dict[str, object] | None:
        row = await self._pool.fetchrow(
            """SELECT s.id, s.state, s.active_problem_id, p.snapshot
               FROM sessions s JOIN users u ON u.id = s.user_id
               LEFT JOIN issued_problems p ON p.id = s.active_problem_id
               WHERE u.telegram_user_id = $1 AND s.mode = 'task6'
                 AND s.finished_at IS NULL
               ORDER BY s.started_at DESC LIMIT 1""",
            telegram_user_id,
        )
        if row is None:
            return None
        return {
            "session_id": str(row["id"]),
            "state": _json_object(row["state"]),
            "problem": _json_object(row["snapshot"]) if row["snapshot"] is not None else None,
        }

    async def set_task6_prompt_message(
        self,
        telegram_user_id: int,
        expected_problem_id: str,
        message_id: int,
        expected_status: str | None = None,
    ) -> bool:
        async with self._pool.acquire() as connection, connection.transaction():
            row = await connection.fetchrow(
                """SELECT s.id, s.state, s.active_problem_id FROM sessions s
                   JOIN users u ON u.id = s.user_id
                   WHERE u.telegram_user_id = $1 AND s.mode = 'task6'
                     AND s.finished_at IS NULL
                   ORDER BY s.started_at DESC LIMIT 1 FOR UPDATE OF s""",
                telegram_user_id,
            )
            if row is None or str(row["active_problem_id"]) != expected_problem_id:
                return False
            state = _json_object(row["state"])
            if expected_status is not None and state.get("status") != expected_status:
                return False
            current_message_id = state.get("input_prompt_message_id")
            if isinstance(current_message_id, int) and message_id < current_message_id:
                return False
            state["input_prompt_message_id"] = message_id
            await connection.execute(
                "UPDATE sessions SET state = $2::jsonb WHERE id = $1",
                row["id"],
                json.dumps(state),
            )
            return True

    async def set_task6_condition_message(
        self, telegram_user_id: int, expected_problem_id: str, message_id: int
    ) -> bool:
        async with self._pool.acquire() as connection, connection.transaction():
            row = await connection.fetchrow(
                """SELECT s.id, s.state, s.active_problem_id FROM sessions s
                   JOIN users u ON u.id = s.user_id
                   WHERE u.telegram_user_id = $1 AND s.mode = 'task6'
                     AND s.finished_at IS NULL
                   ORDER BY s.started_at DESC LIMIT 1 FOR UPDATE OF s""",
                telegram_user_id,
            )
            if row is None or str(row["active_problem_id"]) != expected_problem_id:
                return False
            state = _json_object(row["state"])
            state["problem_prompt_message_id"] = message_id
            state["input_prompt_message_id"] = message_id
            await connection.execute(
                "UPDATE sessions SET state = $2::jsonb WHERE id = $1",
                row["id"],
                json.dumps(state),
            )
            return True

    async def task6_attempt(
        self,
        telegram_user_id: int,
        expected_problem_id: str,
        raw_answer: str,
        is_correct: bool,
        telegram_message_id: int | None = None,
        expected_prompt_message_id: int | None = None,
    ) -> dict[str, object] | None:
        async with self._pool.acquire() as connection, connection.transaction():
            user = await connection.fetchrow(
                "SELECT id, current_state FROM users WHERE telegram_user_id = $1 FOR UPDATE",
                telegram_user_id,
            )
            if user is None:
                return None
            row = await connection.fetchrow(
                """SELECT s.id AS session_id, s.state, s.active_problem_id,
                          p.user_id, p.snapshot
                   FROM sessions s JOIN issued_problems p ON p.id = s.active_problem_id
                   WHERE s.user_id = $1 AND s.mode = 'task6'
                     AND s.finished_at IS NULL
                   ORDER BY s.started_at DESC LIMIT 1 FOR UPDATE OF s""",
                user["id"],
            )
            if row is None:
                return None
            if str(row["active_problem_id"]) != expected_problem_id:
                return {"status": "stale", "attempt": 0}
            state = _json_object(row["state"])
            user_state = _json_object(user["current_state"])
            if user_state.get("screen") != "task6":
                return {"status": "stale", "attempt": 0}
            if expected_prompt_message_id is not None and (
                state.get("problem_prompt_message_id", state.get("input_prompt_message_id"))
                != expected_prompt_message_id
            ):
                return {"status": "stale", "attempt": 0}
            if telegram_message_id is not None and expected_prompt_message_id is not None:
                if telegram_message_id <= expected_prompt_message_id:
                    return {"status": "stale", "attempt": 0}
            if telegram_message_id is not None:
                duplicate = await connection.fetchval(
                    "SELECT 1 FROM attempts WHERE user_id = $1 AND telegram_message_id = $2",
                    row["user_id"],
                    telegram_message_id,
                )
                if duplicate is not None:
                    return {"status": "duplicate", "attempt": 0}
            if state.get("status") != "active":
                return {
                    "status": str(state.get("status", "finished")),
                    "attempt": 0,
                    "problem": _json_object(row["snapshot"]),
                }
            previous_attempts = state.get("attempts", 0)
            attempt = (previous_attempts if isinstance(previous_attempts, int) else 0) + 1
            if attempt > 2:
                return {
                    "status": "finished",
                    "attempt": 2,
                    "problem": _json_object(row["snapshot"]),
                }
            status = "solved" if is_correct else ("failed" if attempt == 2 else "active")
            snapshot = _json_object(row["snapshot"])
            await connection.execute(
                """INSERT INTO attempts
                   (problem_id, user_id, attempt_no, raw_answer, normalized_answer,
                    is_correct, used_hint, telegram_message_id)
                   VALUES ($1, $2, $3, $4, $4, $5, $6, $7)""",
                row["active_problem_id"],
                row["user_id"],
                attempt,
                raw_answer[:200],
                is_correct,
                bool(state.get("used_hint", False)),
                telegram_message_id,
            )
            state.update({"status": status, "attempts": attempt})
            if status in {"solved", "failed"}:
                await connection.execute(
                    "UPDATE issued_problems SET outcome = $2 WHERE id = $1",
                    row["active_problem_id"],
                    status,
                )
            await connection.execute(
                "UPDATE sessions SET state = $2::jsonb WHERE id = $1",
                row["session_id"],
                json.dumps(state),
            )
            return {"status": status, "attempt": attempt, "problem": snapshot}

    async def task6_hint(
        self,
        telegram_user_id: int,
        expected_problem_id: str,
        expected_prompt_message_id: int | None = None,
    ) -> str | None:
        async with self._pool.acquire() as connection, connection.transaction():
            user = await connection.fetchrow(
                "SELECT current_state FROM users WHERE telegram_user_id = $1 FOR UPDATE",
                telegram_user_id,
            )
            if user is None or _json_object(user["current_state"]).get("screen") != "task6":
                return None
            row = await connection.fetchrow(
                """SELECT s.id, s.state, s.active_problem_id, p.snapshot FROM sessions s
                   JOIN users u ON u.id = s.user_id
                   JOIN issued_problems p ON p.id = s.active_problem_id
                   WHERE u.telegram_user_id = $1 AND s.mode = 'task6'
                     AND s.finished_at IS NULL
                   ORDER BY s.started_at DESC LIMIT 1 FOR UPDATE OF s""",
                telegram_user_id,
            )
            if row is None:
                return None
            if str(row["active_problem_id"]) != expected_problem_id:
                return None
            state = _json_object(row["state"])
            problem = _json_object(row["snapshot"])
            if (
                expected_prompt_message_id is not None
                and state.get("input_prompt_message_id") != expected_prompt_message_id
            ):
                return None
            if state.get("status") != "active":
                return None
            hints = problem.get("hints", [])
            hints_used = state.get("hints_used", 0)
            hints_used = hints_used if isinstance(hints_used, int) else 0
            if not isinstance(hints, list) or hints_used >= len(hints):
                return None
            hints_used += 1
            state["hints_used"] = hints_used
            state["used_hint"] = True
            await connection.execute(
                "UPDATE sessions SET state = $2::jsonb WHERE id = $1",
                row["id"],
                json.dumps(state),
            )
            await connection.execute(
                "UPDATE issued_problems SET hints_used = $2 WHERE id = $1",
                row["active_problem_id"],
                hints_used,
            )
            return str(hints[hints_used - 1])

    async def task6_reveal_solution(
        self,
        telegram_user_id: int,
        expected_problem_id: str,
        expected_prompt_message_id: int | None = None,
    ) -> dict[str, object] | None:
        async with self._pool.acquire() as connection, connection.transaction():
            user = await connection.fetchrow(
                "SELECT current_state FROM users WHERE telegram_user_id = $1 FOR UPDATE",
                telegram_user_id,
            )
            if user is None or _json_object(user["current_state"]).get("screen") != "task6":
                return None
            row = await connection.fetchrow(
                """SELECT s.id, s.state, s.active_problem_id, p.snapshot
                   FROM sessions s JOIN users u ON u.id = s.user_id
                   JOIN issued_problems p ON p.id = s.active_problem_id
                   WHERE u.telegram_user_id = $1 AND s.mode = 'task6'
                     AND s.finished_at IS NULL
                   ORDER BY s.started_at DESC LIMIT 1 FOR UPDATE OF s""",
                telegram_user_id,
            )
            if row is None or str(row["active_problem_id"]) != expected_problem_id:
                return None
            state = _json_object(row["state"])
            problem = _json_object(row["snapshot"])
            if (
                expected_prompt_message_id is not None
                and state.get("input_prompt_message_id") != expected_prompt_message_id
            ):
                return None
            status = str(state.get("status", ""))
            if status == "active":
                state["status"] = "solution_viewed"
                await connection.execute(
                    "UPDATE issued_problems SET outcome = 'solution_viewed', "
                    "solution_viewed_at = now() WHERE id = $1",
                    row["active_problem_id"],
                )
                await connection.execute(
                    "UPDATE sessions SET state = $2::jsonb WHERE id = $1",
                    row["id"],
                    json.dumps(state),
                )
            else:
                await connection.execute(
                    "UPDATE issued_problems SET solution_viewed_at = "
                    "COALESCE(solution_viewed_at, now()) "
                    "WHERE id = $1",
                    row["active_problem_id"],
                )
            return {"problem": problem, "status": status}

    async def task6_progress(self, telegram_user_id: int) -> dict[str, int]:
        row = await self._pool.fetchrow(
            """SELECT count(DISTINCT p.id)::int AS issued,
                      count(DISTINCT p.id) FILTER (WHERE a.problem_id IS NOT NULL)::int AS answered,
                      count(DISTINCT p.id) FILTER (WHERE p.outcome = 'solved')::int AS correct,
                      count(a.id)::int AS attempts,
                      count(a.id) FILTER (WHERE a.attempt_no = 1)::int AS first_attempts,
                      count(a.id) FILTER (WHERE a.attempt_no = 2)::int AS second_attempts,
                      count(DISTINCT p.id) FILTER (WHERE p.outcome = 'solved' AND EXISTS (
                          SELECT 1 FROM attempts a1 WHERE a1.problem_id = p.id
                            AND a1.attempt_no = 1 AND a1.is_correct
                      ))::int AS solved_first_try,
                      count(DISTINCT p.id) FILTER (WHERE p.outcome = 'solved' AND EXISTS (
                          SELECT 1 FROM attempts a2 WHERE a2.problem_id = p.id
                            AND a2.attempt_no = 2 AND a2.is_correct
                      ))::int AS solved_second_try,
                      COALESCE((
                          SELECT sum(p2.hints_used) FROM issued_problems p2
                          JOIN sessions s2 ON s2.id = p2.session_id AND s2.mode = 'task6'
                          JOIN users u2 ON u2.id = p2.user_id
                          WHERE u2.telegram_user_id = $1
                      ), 0)::int AS hints_used,
                      count(DISTINCT p.id) FILTER (
                          WHERE p.solution_viewed_at IS NOT NULL
                      )::int AS solutions_viewed,
                      count(DISTINCT p.id) FILTER (WHERE p.outcome = 'skipped')::int AS skipped
               FROM users u
               LEFT JOIN issued_problems p ON p.user_id = u.id
               LEFT JOIN sessions s ON s.id = p.session_id AND s.mode = 'task6'
               LEFT JOIN attempts a ON a.problem_id = p.id
               WHERE u.telegram_user_id = $1 AND (p.id IS NULL OR s.id IS NOT NULL)""",
            telegram_user_id,
        )
        keys = (
            "issued",
            "answered",
            "correct",
            "attempts",
            "first_attempts",
            "second_attempts",
            "solved_first_try",
            "solved_second_try",
            "hints_used",
            "solutions_viewed",
            "skipped",
        )
        if row is None:
            return dict.fromkeys(keys, 0)
        return {key: int(row[key]) for key in keys}

    async def claim_update(self, update_id: int) -> bool:
        async with self._pool.acquire() as connection:
            inserted = await connection.fetchval(
                """INSERT INTO telegram_updates (update_id, status, claimed_at)
                   VALUES ($1, 'processing', now())
                   ON CONFLICT (update_id) DO NOTHING RETURNING update_id""",
                update_id,
            )
            if inserted is not None:
                return True
            reclaimed = await connection.fetchval(
                """UPDATE telegram_updates SET status = 'processing', claimed_at = now()
                   WHERE update_id = $1 AND (
                     status = 'failed' OR
                     (status = 'processing' AND claimed_at < now() - interval '5 minutes')
                   )
                   RETURNING update_id""",
                update_id,
            )
            return reclaimed is not None

    async def finish_update(self, update_id: int, *, failed: bool = False) -> None:
        await self._pool.execute(
            """UPDATE telegram_updates SET status = $2, processed_at = now()
               WHERE update_id = $1""",
            update_id,
            "failed" if failed else "processed",
        )


class MemoryRepository:
    """Small adapter for isolated handler tests; production always uses PostgreSQL."""

    def __init__(self) -> None:
        self.users: set[int] = set()
        self.states: dict[int, str] = {}
        self.resume_modes: dict[int, str] = {}
        self.updates: dict[int, str] = {}
        self.sessions: dict[int, dict[str, object]] = {}
        self.training: dict[int, dict[str, object]] = {}
        self.issued_history: dict[int, dict[str, dict[str, object]]] = {}
        self.attempt_history: dict[int, list[dict[str, object]]] = {}
        self.outcomes: dict[int, dict[str, str]] = {}
        self.hints_history: dict[int, dict[str, int]] = {}
        self.solutions_viewed: dict[int, set[str]] = {}
        self.processed_message_ids: set[tuple[int, int]] = set()
        self.training9: dict[int, dict[str, object]] = {}
        self.issued9: dict[int, dict[str, dict[str, object]]] = {}
        self.attempts9: dict[int, list[dict[str, object]]] = {}
        self.outcomes9: dict[int, dict[str, str]] = {}
        self.hints9: dict[int, dict[str, int]] = {}
        self.solutions9: dict[int, set[str]] = {}
        self.training10: dict[int, dict[str, object]] = {}
        self.training14: dict[int, dict[str, object]] = {}
        self.issued10: dict[int, dict[str, dict[str, object]]] = {}
        self.issued14: dict[int, dict[str, dict[str, object]]] = {}
        self.attempts10: dict[int, list[dict[str, object]]] = {}
        self.attempts14: dict[int, list[dict[str, object]]] = {}
        self.outcomes10: dict[int, dict[str, str]] = {}
        self.outcomes14: dict[int, dict[str, str]] = {}
        self.hints10: dict[int, dict[str, int]] = {}
        self.hints14: dict[int, dict[str, int]] = {}
        self.solutions10: dict[int, set[str]] = {}
        self.solutions14: dict[int, set[str]] = {}

    async def register_user(self, telegram_user_id: int) -> None:
        self.users.add(telegram_user_id)

    async def save_user_state(self, telegram_user_id: int, screen: str) -> None:
        self.states[telegram_user_id] = screen
        if screen in {"task6", "task9", "task10", "task14"}:
            self.resume_modes[telegram_user_id] = screen

    async def transition_task_screen(
        self,
        telegram_user_id: int,
        mode: str,
        expected_problem_id: str,
        target_screen: str,
        expected_prompt_message_id: int | None = None,
    ) -> bool:
        if self.states.get(telegram_user_id) != mode:
            return False
        saved = (
            self.training.get(telegram_user_id)
            if mode == "task6"
            else self.training9.get(telegram_user_id)
            if mode == "task9"
            else self.training10.get(telegram_user_id)
            if mode == "task10"
            else self.training14.get(telegram_user_id)
        )
        problem = saved.get("problem") if saved is not None else None
        state = saved.get("state") if saved is not None else None
        if (
            not isinstance(problem, dict)
            or str(problem.get("problem_id", "")) != expected_problem_id
        ):
            return False
        if expected_prompt_message_id is not None and (
            not isinstance(state, dict)
            or state.get("input_prompt_message_id") != expected_prompt_message_id
        ):
            return False
        self.states[telegram_user_id] = target_screen
        return True

    async def user_state(self, telegram_user_id: int) -> str | None:
        return self.states.get(telegram_user_id)

    async def last_training_mode(self, telegram_user_id: int) -> str | None:
        return self.resume_modes.get(telegram_user_id)

    async def current_session(self, telegram_user_id: int) -> dict[str, object] | None:
        return self.sessions.get(telegram_user_id)

    async def ensure_task6_session(self, telegram_user_id: int) -> str:
        state = self.training.setdefault(
            telegram_user_id,
            {"session_id": f"memory-{telegram_user_id}", "state": {}, "problem": None},
        )
        return str(state["session_id"])

    async def advance_task6_problem(
        self,
        telegram_user_id: int,
        expected_problem_id: str | None,
        candidates: list[dict[str, object]],
        expected_screen: str | None = None,
        expected_prompt_message_id: int | None = None,
        skip_active: bool = False,
    ) -> dict[str, object]:
        state = self.training[telegram_user_id]
        if expected_screen is not None and self.states.get(telegram_user_id) != expected_screen:
            current = state.get("problem")
            return (
                {**current, "_transitioned": False, "_stale_screen": True}
                if isinstance(current, dict)
                else {"_transitioned": False, "_stale_screen": True}
            )
        session_state = cast(dict[str, object], state["state"])
        current = state.get("problem")
        if (
            expected_prompt_message_id is not None
            and session_state.get("input_prompt_message_id") != expected_prompt_message_id
        ):
            return (
                {**current, "_transitioned": False}
                if isinstance(current, dict)
                else {"_transitioned": False}
            )
        active_id = str(current.get("problem_id", "")) if isinstance(current, dict) else None
        status = session_state.get("status")
        if active_id is not None:
            if expected_problem_id is not None and active_id != expected_problem_id:
                return {**cast(dict[str, object], current), "_transitioned": False}
            if expected_problem_id is None and status == "active":
                return {**cast(dict[str, object], current), "_transitioned": False}
            if skip_active != (status == "active"):
                return {**cast(dict[str, object], current), "_transitioned": False}
            if skip_active:
                self.outcomes.setdefault(telegram_user_id, {})[active_id] = "skipped"
        elif expected_problem_id is not None:
            raise RuntimeError("Expected active task-6 problem is missing")
        if not candidates:
            raise RuntimeError("No distinct task-6 candidate could be constructed")
        recent = session_state.get("recent_fingerprints", [])
        recent_fingerprints = (
            [item for item in recent if isinstance(item, str)] if isinstance(recent, list) else []
        )
        queue_after: list[str] = []
        rejected = 0
        for candidate in candidates:
            if str(candidate.get("fingerprint", "")) in recent_fingerprints:
                rejected += 1
                continue
            problem = dict(candidate)
            raw_queue = problem.pop("_family_queue_after", [])
            queue_after = (
                [item for item in raw_queue if isinstance(item, str)]
                if isinstance(raw_queue, list)
                else []
            )
            problem_id = str(problem["problem_id"])
            state["problem"] = problem
            next_recent = [*recent_fingerprints, str(problem["fingerprint"])][-30:]
            state["state"] = {
                "status": "active",
                "attempts": 0,
                "hints_used": 0,
                "used_hint": False,
                "family_queue": queue_after,
                "recent_fingerprints": next_recent,
                "selection_dedupe_rejections": (
                    _state_int(session_state, "selection_dedupe_rejections") + rejected
                ),
            }
            self.issued_history.setdefault(telegram_user_id, {})[problem_id] = problem
            self.outcomes.setdefault(telegram_user_id, {})[problem_id] = "issued"
            return {**problem, "_transitioned": True}
        raise RuntimeError("Every task-6 candidate repeats a recently issued fingerprint")

    async def task6_state(self, telegram_user_id: int) -> dict[str, object] | None:
        state = self.training.get(telegram_user_id)
        return state

    async def set_task6_prompt_message(
        self,
        telegram_user_id: int,
        expected_problem_id: str,
        message_id: int,
        expected_status: str | None = None,
    ) -> bool:
        state = self.training.get(telegram_user_id)
        if state is None or not isinstance(state.get("problem"), dict):
            return False
        problem = cast(dict[str, object], state["problem"])
        if str(problem.get("problem_id", "")) != expected_problem_id:
            return False
        session_state = cast(dict[str, object], state["state"])
        if expected_status is not None and session_state.get("status") != expected_status:
            return False
        current_message_id = session_state.get("input_prompt_message_id")
        if isinstance(current_message_id, int) and message_id < current_message_id:
            return False
        session_state["input_prompt_message_id"] = message_id
        return True

    async def set_task6_condition_message(
        self, telegram_user_id: int, expected_problem_id: str, message_id: int
    ) -> bool:
        state = self.training.get(telegram_user_id)
        if state is None or not isinstance(state.get("problem"), dict):
            return False
        problem = cast(dict[str, object], state["problem"])
        if str(problem.get("problem_id", "")) != expected_problem_id:
            return False
        session_state = cast(dict[str, object], state["state"])
        session_state["problem_prompt_message_id"] = message_id
        session_state["input_prompt_message_id"] = message_id
        return True

    async def task6_attempt(
        self,
        telegram_user_id: int,
        expected_problem_id: str,
        raw_answer: str,
        is_correct: bool,
        telegram_message_id: int | None = None,
        expected_prompt_message_id: int | None = None,
    ) -> dict[str, object] | None:
        state = self.training.get(telegram_user_id)
        if state is None or state.get("problem") is None:
            return None
        problem = cast(dict[str, object], state["problem"])
        problem_id = str(problem.get("problem_id", ""))
        if problem_id != expected_problem_id:
            return {"status": "stale", "attempt": 0}
        session_state = cast(dict[str, object], state["state"])
        if self.states.get(telegram_user_id) != "task6":
            return {"status": "stale", "attempt": 0}
        if expected_prompt_message_id is not None and (
            session_state.get(
                "problem_prompt_message_id", session_state.get("input_prompt_message_id")
            )
            != expected_prompt_message_id
        ):
            return {"status": "stale", "attempt": 0}
        if telegram_message_id is not None and expected_prompt_message_id is not None:
            if telegram_message_id <= expected_prompt_message_id:
                return {"status": "stale", "attempt": 0}
        if telegram_message_id is not None:
            message_key = (telegram_user_id, telegram_message_id)
            if message_key in self.processed_message_ids:
                return {"status": "duplicate", "attempt": 0}
            self.processed_message_ids.add(message_key)
        if session_state.get("status") != "active":
            return {
                "status": session_state.get("status", "finished"),
                "attempt": 0,
                "problem": state["problem"],
            }
        previous_attempts = session_state.get("attempts", 0)
        attempt = (previous_attempts if isinstance(previous_attempts, int) else 0) + 1
        status = "solved" if is_correct else ("failed" if attempt == 2 else "active")
        session_state.update({"status": status, "attempts": attempt})
        self.attempt_history.setdefault(telegram_user_id, []).append(
            {
                "problem_id": problem_id,
                "attempt_no": attempt,
                "is_correct": is_correct,
                "raw": raw_answer,
                "telegram_message_id": telegram_message_id,
            }
        )
        if status in {"solved", "failed"}:
            self.outcomes.setdefault(telegram_user_id, {})[problem_id] = status
        return {"status": status, "attempt": attempt, "problem": problem}

    async def task6_progress(self, telegram_user_id: int) -> dict[str, int]:
        issued = self.issued_history.get(telegram_user_id, {})
        outcomes = self.outcomes.get(telegram_user_id, {})
        records = self.attempt_history.get(telegram_user_id, [])
        by_problem: dict[str, list[dict[str, object]]] = {}
        for record in records:
            by_problem.setdefault(str(record["problem_id"]), []).append(record)
        solved_first = sum(
            1
            for problem_id, values in by_problem.items()
            if outcomes.get(problem_id) == "solved"
            and any(value["attempt_no"] == 1 and value["is_correct"] for value in values)
        )
        solved_second = sum(
            1
            for problem_id, values in by_problem.items()
            if outcomes.get(problem_id) == "solved"
            and any(value["attempt_no"] == 2 and value["is_correct"] for value in values)
        )
        return {
            "issued": len(issued),
            "answered": len(by_problem),
            "correct": sum(value == "solved" for value in outcomes.values()),
            "attempts": len(records),
            "first_attempts": sum(record["attempt_no"] == 1 for record in records),
            "second_attempts": sum(record["attempt_no"] == 2 for record in records),
            "solved_first_try": solved_first,
            "solved_second_try": solved_second,
            "hints_used": sum(self.hints_history.get(telegram_user_id, {}).values()),
            "solutions_viewed": len(self.solutions_viewed.get(telegram_user_id, set())),
            "skipped": sum(value == "skipped" for value in outcomes.values()),
        }

    async def task6_hint(
        self,
        telegram_user_id: int,
        expected_problem_id: str,
        expected_prompt_message_id: int | None = None,
    ) -> str | None:
        state = self.training.get(telegram_user_id)
        if state is None or state.get("problem") is None:
            return None
        problem = cast(dict[str, object], state["problem"])
        problem_id = str(problem.get("problem_id", ""))
        if self.states.get(telegram_user_id) != "task6" or problem_id != expected_problem_id:
            return None
        session_state = cast(dict[str, object], state["state"])
        if (
            expected_prompt_message_id is not None
            and session_state.get("input_prompt_message_id") != expected_prompt_message_id
        ):
            return None
        if session_state.get("status") != "active":
            return None
        hints = problem.get("hints", [])
        hints_used = session_state.get("hints_used", 0)
        hints_used = hints_used if isinstance(hints_used, int) else 0
        if not isinstance(hints, list) or hints_used >= len(hints):
            return None
        hints_used += 1
        session_state["hints_used"] = hints_used
        session_state["used_hint"] = True
        self.hints_history.setdefault(telegram_user_id, {})[problem_id] = hints_used
        return str(hints[hints_used - 1])

    async def task6_reveal_solution(
        self,
        telegram_user_id: int,
        expected_problem_id: str,
        expected_prompt_message_id: int | None = None,
    ) -> dict[str, object] | None:
        state = self.training.get(telegram_user_id)
        if state is None or not isinstance(state.get("problem"), dict):
            return None
        problem = cast(dict[str, object], state["problem"])
        problem_id = str(problem.get("problem_id", ""))
        if self.states.get(telegram_user_id) != "task6" or problem_id != expected_problem_id:
            return None
        session_state = cast(dict[str, object], state["state"])
        if (
            expected_prompt_message_id is not None
            and session_state.get("input_prompt_message_id") != expected_prompt_message_id
        ):
            return None
        previous_status = str(session_state.get("status", ""))
        if previous_status == "active":
            session_state["status"] = "solution_viewed"
            self.outcomes.setdefault(telegram_user_id, {})[problem_id] = "solution_viewed"
        self.solutions_viewed.setdefault(telegram_user_id, set()).add(problem_id)
        return {"problem": problem, "status": previous_status}

    async def claim_update(self, update_id: int) -> bool:
        state = self.updates.get(update_id)
        if state is None or state == "failed":
            self.updates[update_id] = "processing"
            return True
        return False

    async def finish_update(self, update_id: int, *, failed: bool = False) -> None:
        self.updates[update_id] = "failed" if failed else "processed"

    async def ensure_task9_session(self, telegram_user_id: int) -> str:
        return str(
            self.training9.setdefault(
                telegram_user_id,
                {"session_id": f"memory9-{telegram_user_id}", "state": {}, "problem": None},
            )["session_id"]
        )

    async def advance_task9_problem(
        self,
        telegram_user_id: int,
        expected_problem_id: str | None,
        candidates: list[dict[str, object]],
        expected_screen: str | None = None,
        expected_prompt_message_id: int | None = None,
        skip_active: bool = False,
    ) -> dict[str, object]:
        saved = self.training9[telegram_user_id]
        if expected_screen is not None and self.states.get(telegram_user_id) != expected_screen:
            current = saved.get("problem")
            return (
                {**current, "_transitioned": False, "_stale_screen": True}
                if isinstance(current, dict)
                else {"_transitioned": False, "_stale_screen": True}
            )
        state = cast(dict[str, object], saved["state"])
        if (
            expected_prompt_message_id is not None
            and state.get("input_prompt_message_id") != expected_prompt_message_id
        ):
            return (
                {**cast(dict[str, object], saved["problem"]), "_transitioned": False}
                if isinstance(saved.get("problem"), dict)
                else {"_transitioned": False}
            )
        current = saved.get("problem")
        current_id = str(current.get("problem_id", "")) if isinstance(current, dict) else None
        if current_id is not None:
            if current_id != expected_problem_id:
                return {**cast(dict[str, object], current), "_transitioned": False}
            if skip_active != (state.get("status") == "active"):
                return {**cast(dict[str, object], current), "_transitioned": False}
            if skip_active:
                self.outcomes9.setdefault(telegram_user_id, {})[current_id] = "skipped"
        recent_value = state.get("recent_fingerprints", [])
        recent = (
            [value for value in recent_value if isinstance(value, str)]
            if isinstance(recent_value, list)
            else []
        )
        seen = set(recent)
        for candidate in candidates:
            fingerprint = str(candidate["fingerprint"])
            if fingerprint in seen:
                continue
            problem = dict(candidate)
            queue = problem.pop("_family_queue_after", [])
            last_group = problem.pop("_last_group_after", None)
            group_run_length = problem.pop("_group_run_length_after", 0)
            problem["problem_id"] = str(problem["problem_id"])
            next_state = {
                "status": "active",
                "attempts": 0,
                "hints_used": 0,
                "used_hint": False,
                "family_queue": queue,
                "recent_fingerprints": [*recent, fingerprint][-30:],
                "last_family_id": problem["family_id"],
                "last_group": last_group,
                "group_run_length": group_run_length,
            }
            saved["problem"], saved["state"] = problem, next_state
            self.issued9.setdefault(telegram_user_id, {})[str(problem["problem_id"])] = problem
            self.outcomes9.setdefault(telegram_user_id, {})[str(problem["problem_id"])] = "issued"
            return {**problem, "_transitioned": True}
        raise RuntimeError("No distinct task-9 problem could be constructed")

    async def task9_state(self, telegram_user_id: int) -> dict[str, object] | None:
        saved = self.training9.get(telegram_user_id)
        if saved is None:
            return None
        return {
            "session_id": saved["session_id"],
            "state": dict(cast(dict[str, object], saved["state"])),
            "problem": saved.get("problem"),
        }

    async def set_task9_prompt_message(
        self,
        telegram_user_id: int,
        expected_problem_id: str,
        message_id: int,
        expected_status: str | None = None,
    ) -> bool:
        saved = self.training9.get(telegram_user_id)
        if saved is None or not isinstance(saved.get("problem"), dict):
            return False
        problem = cast(dict[str, object], saved["problem"])
        if str(problem.get("problem_id")) != expected_problem_id:
            return False
        state = cast(dict[str, object], saved["state"])
        if expected_status is not None and state.get("status") != expected_status:
            return False
        current_message_id = state.get("input_prompt_message_id")
        if isinstance(current_message_id, int) and message_id < current_message_id:
            return False
        state["input_prompt_message_id"] = message_id
        return True

    async def set_task9_condition_message(
        self, telegram_user_id: int, expected_problem_id: str, message_id: int
    ) -> bool:
        saved = self.training9.get(telegram_user_id)
        if saved is None or not isinstance(saved.get("problem"), dict):
            return False
        problem = cast(dict[str, object], saved["problem"])
        if str(problem.get("problem_id", "")) != expected_problem_id:
            return False
        state = cast(dict[str, object], saved["state"])
        state["problem_prompt_message_id"] = message_id
        state["input_prompt_message_id"] = message_id
        return True

    async def task9_attempt(
        self,
        telegram_user_id: int,
        expected_problem_id: str,
        raw_answer: str,
        is_correct: bool,
        telegram_message_id: int | None = None,
        expected_prompt_message_id: int | None = None,
    ) -> dict[str, object] | None:
        saved = self.training9.get(telegram_user_id)
        if saved is None or not isinstance(saved.get("problem"), dict):
            return None
        problem = cast(dict[str, object], saved["problem"])
        if str(problem.get("problem_id")) != expected_problem_id:
            return {"status": "stale", "attempt": 0}
        state = cast(dict[str, object], saved["state"])
        if self.states.get(telegram_user_id) != "task9":
            return {"status": "stale", "attempt": 0}
        if expected_prompt_message_id is not None and (
            state.get("problem_prompt_message_id", state.get("input_prompt_message_id"))
            != expected_prompt_message_id
        ):
            return {"status": "stale", "attempt": 0}
        if telegram_message_id is not None and expected_prompt_message_id is not None:
            if telegram_message_id <= expected_prompt_message_id:
                return {"status": "stale", "attempt": 0}
        if telegram_message_id is not None:
            key = (telegram_user_id, telegram_message_id)
            if key in self.processed_message_ids:
                return {"status": "duplicate", "attempt": 0}
            self.processed_message_ids.add(key)
        if state.get("status") != "active":
            return {
                "status": str(state.get("status", "finished")),
                "attempt": 0,
                "problem": problem,
            }
        attempt = _state_int(state, "attempts") + 1
        status = "solved" if is_correct else ("failed" if attempt == 2 else "active")
        state.update({"status": status, "attempts": attempt})
        self.attempts9.setdefault(telegram_user_id, []).append(
            {
                "problem_id": expected_problem_id,
                "attempt_no": attempt,
                "is_correct": is_correct,
                "raw_answer": raw_answer,
            }
        )
        if status in {"solved", "failed"}:
            self.outcomes9.setdefault(telegram_user_id, {})[expected_problem_id] = status
        return {"status": status, "attempt": attempt, "problem": problem}

    async def task9_hint(
        self,
        telegram_user_id: int,
        expected_problem_id: str,
        expected_prompt_message_id: int | None = None,
    ) -> str | None:
        saved = self.training9.get(telegram_user_id)
        if saved is None or not isinstance(saved.get("problem"), dict):
            return None
        problem = cast(dict[str, object], saved["problem"])
        state = cast(dict[str, object], saved["state"])
        if (
            expected_prompt_message_id is not None
            and state.get("input_prompt_message_id") != expected_prompt_message_id
        ):
            return None
        if (
            self.states.get(telegram_user_id) != "task9"
            or str(problem.get("problem_id")) != expected_problem_id
            or state.get("status") != "active"
        ):
            return None
        hints = problem.get("hints", [])
        used = _state_int(state, "hints_used")
        if not isinstance(hints, list) or used >= len(hints):
            return None
        state.update({"hints_used": used + 1, "used_hint": True})
        self.hints9.setdefault(telegram_user_id, {})[expected_problem_id] = used + 1
        return str(hints[used])

    async def task9_reveal_solution(
        self,
        telegram_user_id: int,
        expected_problem_id: str,
        expected_prompt_message_id: int | None = None,
    ) -> dict[str, object] | None:
        saved = self.training9.get(telegram_user_id)
        if saved is None or not isinstance(saved.get("problem"), dict):
            return None
        problem = cast(dict[str, object], saved["problem"])
        if (
            self.states.get(telegram_user_id) != "task9"
            or str(problem.get("problem_id")) != expected_problem_id
        ):
            return None
        state = cast(dict[str, object], saved["state"])
        if (
            expected_prompt_message_id is not None
            and state.get("input_prompt_message_id") != expected_prompt_message_id
        ):
            return None
        old_status = str(state.get("status", ""))
        if old_status == "active":
            state["status"] = "solution_viewed"
            self.outcomes9.setdefault(telegram_user_id, {})[expected_problem_id] = "solution_viewed"
        self.solutions9.setdefault(telegram_user_id, set()).add(expected_problem_id)
        return {"problem": problem, "status": old_status}

    async def task9_progress(self, telegram_user_id: int) -> dict[str, int]:
        issued = self.issued9.get(telegram_user_id, {})
        attempts = self.attempts9.get(telegram_user_id, [])
        outcomes = self.outcomes9.get(telegram_user_id, {})
        return {
            "issued": len(issued),
            "answered": len({str(item["problem_id"]) for item in attempts}),
            "correct": sum(value == "solved" for value in outcomes.values()),
            "solved_first_try": sum(
                value == "solved"
                and any(
                    str(attempt["problem_id"]) == problem_id
                    and attempt["attempt_no"] == 1
                    and attempt.get("is_correct") is True
                    for attempt in attempts
                )
                for problem_id, value in outcomes.items()
            ),
            "solved_second_try": sum(
                value == "solved"
                and any(
                    str(attempt["problem_id"]) == problem_id
                    and attempt["attempt_no"] == 2
                    and attempt.get("is_correct") is True
                    for attempt in attempts
                )
                for problem_id, value in outcomes.items()
            ),
            "attempts": len(attempts),
            "first_attempts": sum(item["attempt_no"] == 1 for item in attempts),
            "second_attempts": sum(item["attempt_no"] == 2 for item in attempts),
            "hints_used": sum(self.hints9.get(telegram_user_id, {}).values()),
            "solutions_viewed": len(self.solutions9.get(telegram_user_id, set())),
            "skipped": sum(value == "skipped" for value in outcomes.values()),
        }

    async def ensure_task10_session(self, telegram_user_id: int) -> str:
        saved = self.training10.setdefault(
            telegram_user_id,
            {"session_id": f"memory10-{telegram_user_id}", "state": {}, "problem": None},
        )
        return str(saved["session_id"])

    async def advance_task10_problem(
        self,
        telegram_user_id: int,
        expected_problem_id: str | None,
        candidates: list[dict[str, object]],
        expected_screen: str | None = None,
        expected_prompt_message_id: int | None = None,
        skip_active: bool = False,
    ) -> dict[str, object]:
        saved = self.training10[telegram_user_id]
        state = cast(dict[str, object], saved["state"])
        current = saved.get("problem")
        if expected_screen is not None and self.states.get(telegram_user_id) != expected_screen:
            return {"_transitioned": False, "_stale_screen": True}
        if (
            expected_prompt_message_id is not None
            and state.get("input_prompt_message_id") != expected_prompt_message_id
        ):
            return {"_transitioned": False, "_stale_screen": True}
        current_id = str(current.get("problem_id", "")) if isinstance(current, dict) else None
        if current_id is not None:
            if current_id != expected_problem_id or skip_active != (
                state.get("status") == "active"
            ):
                return {**cast(dict[str, object], current), "_transitioned": False}
            if skip_active:
                self.outcomes10.setdefault(telegram_user_id, {})[current_id] = "skipped"
        elif expected_problem_id is not None:
            raise RuntimeError("Expected active task-10 problem is missing")
        recent = state.get("recent_fingerprints", [])
        recent_order = (
            [item for item in recent if isinstance(item, str)] if isinstance(recent, list) else []
        )
        for candidate in candidates:
            fingerprint = str(candidate.get("fingerprint", ""))
            if fingerprint in recent_order:
                continue
            problem = dict(candidate)
            queue = problem.pop("_family_queue_after", [])
            last_family = problem.pop("_last_family_after", None)
            problem_id = str(problem["problem_id"])
            saved["problem"] = problem
            saved["state"] = {
                "status": "active",
                "attempts": 0,
                "hints_used": 0,
                "used_hint": False,
                "family_queue": queue if isinstance(queue, list) else [],
                "last_family_id": last_family,
                "recent_fingerprints": [*recent_order, fingerprint][-30:],
            }
            self.issued10.setdefault(telegram_user_id, {})[problem_id] = problem
            self.outcomes10.setdefault(telegram_user_id, {})[problem_id] = "issued"
            return {**problem, "_transitioned": True}
        raise RuntimeError("Every task-10 candidate repeats a recent fingerprint")

    async def task10_state(self, telegram_user_id: int) -> dict[str, object] | None:
        return self.training10.get(telegram_user_id)

    async def set_task10_prompt_message(
        self,
        telegram_user_id: int,
        expected_problem_id: str,
        message_id: int,
        expected_status: str | None = None,
    ) -> bool:
        saved = self.training10.get(telegram_user_id)
        problem = saved.get("problem") if saved else None
        if (
            saved is None
            or not isinstance(problem, dict)
            or str(problem.get("problem_id")) != expected_problem_id
        ):
            return False
        state = cast(dict[str, object], saved["state"])
        if expected_status is not None and state.get("status") != expected_status:
            return False
        current = state.get("input_prompt_message_id")
        if isinstance(current, int) and message_id < current:
            return False
        state["input_prompt_message_id"] = message_id
        return True

    async def set_task10_condition_message(
        self, telegram_user_id: int, expected_problem_id: str, message_id: int
    ) -> bool:
        saved = self.training10.get(telegram_user_id)
        problem = saved.get("problem") if saved else None
        if (
            saved is None
            or not isinstance(problem, dict)
            or str(problem.get("problem_id")) != expected_problem_id
        ):
            return False
        state = cast(dict[str, object], saved["state"])
        state["problem_prompt_message_id"] = message_id
        state["input_prompt_message_id"] = message_id
        return True

    async def task10_attempt(
        self,
        telegram_user_id: int,
        expected_problem_id: str,
        raw_answer: str,
        is_correct: bool,
        telegram_message_id: int | None = None,
        expected_prompt_message_id: int | None = None,
    ) -> dict[str, object] | None:
        saved = self.training10.get(telegram_user_id)
        problem = saved.get("problem") if saved else None
        if saved is None or not isinstance(problem, dict):
            return None
        if (
            str(problem.get("problem_id")) != expected_problem_id
            or self.states.get(telegram_user_id) != "task10"
        ):
            return {"status": "stale", "attempt": 0}
        state = cast(dict[str, object], saved["state"])
        if (
            expected_prompt_message_id is not None
            and state.get("problem_prompt_message_id", state.get("input_prompt_message_id"))
            != expected_prompt_message_id
        ):
            return {"status": "stale", "attempt": 0}
        if (
            telegram_message_id is not None
            and expected_prompt_message_id is not None
            and telegram_message_id <= expected_prompt_message_id
        ):
            return {"status": "stale", "attempt": 0}
        if telegram_message_id is not None:
            key = (telegram_user_id, telegram_message_id)
            if key in self.processed_message_ids:
                return {"status": "duplicate", "attempt": 0}
            self.processed_message_ids.add(key)
        if state.get("status") != "active":
            return {
                "status": str(state.get("status", "finished")),
                "attempt": 0,
                "problem": problem,
            }
        attempt = _state_int(state, "attempts") + 1
        status = "solved" if is_correct else ("failed" if attempt == 2 else "active")
        state.update({"status": status, "attempts": attempt})
        self.attempts10.setdefault(telegram_user_id, []).append(
            {
                "problem_id": expected_problem_id,
                "attempt_no": attempt,
                "is_correct": is_correct,
                "raw_answer": raw_answer,
            }
        )
        if status in {"solved", "failed"}:
            self.outcomes10.setdefault(telegram_user_id, {})[expected_problem_id] = status
        return {"status": status, "attempt": attempt, "problem": problem}

    async def task10_hint(
        self,
        telegram_user_id: int,
        expected_problem_id: str,
        expected_prompt_message_id: int | None = None,
    ) -> str | None:
        saved = self.training10.get(telegram_user_id)
        problem = saved.get("problem") if saved else None
        if (
            saved is None
            or not isinstance(problem, dict)
            or self.states.get(telegram_user_id) != "task10"
        ):
            return None
        if str(problem.get("problem_id")) != expected_problem_id:
            return None
        state = cast(dict[str, object], saved["state"])
        if (
            expected_prompt_message_id is not None
            and state.get("input_prompt_message_id") != expected_prompt_message_id
        ):
            return None
        hints = problem.get("hints", [])
        used = _state_int(state, "hints_used")
        if state.get("status") != "active" or not isinstance(hints, list) or used >= len(hints):
            return None
        state.update({"hints_used": used + 1, "used_hint": True})
        self.hints10.setdefault(telegram_user_id, {})[expected_problem_id] = used + 1
        return str(hints[used])

    async def task10_reveal_solution(
        self,
        telegram_user_id: int,
        expected_problem_id: str,
        expected_prompt_message_id: int | None = None,
    ) -> dict[str, object] | None:
        saved = self.training10.get(telegram_user_id)
        problem = saved.get("problem") if saved else None
        if (
            saved is None
            or not isinstance(problem, dict)
            or self.states.get(telegram_user_id) != "task10"
        ):
            return None
        if str(problem.get("problem_id")) != expected_problem_id:
            return None
        state = cast(dict[str, object], saved["state"])
        if (
            expected_prompt_message_id is not None
            and state.get("input_prompt_message_id") != expected_prompt_message_id
        ):
            return None
        status = str(state.get("status", ""))
        if status == "active":
            state["status"] = "solution_viewed"
            self.outcomes10.setdefault(telegram_user_id, {})[expected_problem_id] = (
                "solution_viewed"
            )
        self.solutions10.setdefault(telegram_user_id, set()).add(expected_problem_id)
        return {"problem": problem, "status": status}

    async def task10_progress(self, telegram_user_id: int) -> dict[str, int]:
        issued = self.issued10.get(telegram_user_id, {})
        outcomes = self.outcomes10.get(telegram_user_id, {})
        attempts = self.attempts10.get(telegram_user_id, [])
        by_problem: dict[str, list[dict[str, object]]] = {}
        for attempt in attempts:
            by_problem.setdefault(str(attempt["problem_id"]), []).append(attempt)
        solved_first = sum(
            outcomes.get(pid) == "solved"
            and any(a["attempt_no"] == 1 and a["is_correct"] for a in values)
            for pid, values in by_problem.items()
        )
        solved_second = sum(
            outcomes.get(pid) == "solved"
            and any(a["attempt_no"] == 2 and a["is_correct"] for a in values)
            for pid, values in by_problem.items()
        )
        return {
            "issued": len(issued),
            "answered": len(by_problem),
            "correct": sum(outcome == "solved" for outcome in outcomes.values()),
            "solved_first_try": int(solved_first),
            "solved_second_try": int(solved_second),
            "attempts": len(attempts),
            "first_attempts": sum(attempt["attempt_no"] == 1 for attempt in attempts),
            "second_attempts": sum(attempt["attempt_no"] == 2 for attempt in attempts),
            "hints_used": sum(self.hints10.get(telegram_user_id, {}).values()),
            "solutions_viewed": len(self.solutions10.get(telegram_user_id, set())),
            "skipped": sum(outcome == "skipped" for outcome in outcomes.values()),
        }


    async def ensure_task14_session(self, telegram_user_id: int) -> str:
        saved = self.training14.setdefault(
            telegram_user_id,
            {"session_id": f"memory12-{telegram_user_id}", "state": {}, "problem": None},
        )
        return str(saved["session_id"])

    async def advance_task14_problem(
        self,
        telegram_user_id: int,
        expected_problem_id: str | None,
        candidates: list[dict[str, object]],
        expected_screen: str | None = None,
        expected_prompt_message_id: int | None = None,
        skip_active: bool = False,
    ) -> dict[str, object]:
        saved = self.training14[telegram_user_id]
        state = cast(dict[str, object], saved["state"])
        current = saved.get("problem")
        if expected_screen is not None and self.states.get(telegram_user_id) != expected_screen:
            return {"_transitioned": False, "_stale_screen": True}
        if (
            expected_prompt_message_id is not None
            and state.get("input_prompt_message_id") != expected_prompt_message_id
        ):
            return {"_transitioned": False, "_stale_screen": True}
        current_id = str(current.get("problem_id", "")) if isinstance(current, dict) else None
        if current_id is not None:
            if current_id != expected_problem_id or skip_active != (
                state.get("status") == "active"
            ):
                return {**cast(dict[str, object], current), "_transitioned": False}
            if skip_active:
                self.outcomes14.setdefault(telegram_user_id, {})[current_id] = "skipped"
        elif expected_problem_id is not None:
            raise RuntimeError("Expected active task-14 problem is missing")
        recent = state.get("recent_fingerprints", [])
        recent_order = (
            [item for item in recent if isinstance(item, str)] if isinstance(recent, list) else []
        )
        for candidate in candidates:
            fingerprint = str(candidate.get("fingerprint", ""))
            if fingerprint in recent_order:
                continue
            problem = dict(candidate)
            queue = problem.pop("_family_queue_after", [])
            last_family = problem.pop("_last_family_after", None)
            problem_id = str(problem["problem_id"])
            saved["problem"] = problem
            saved["state"] = {
                "status": "active",
                "attempts": 0,
                "hints_used": 0,
                "used_hint": False,
                "family_queue": queue if isinstance(queue, list) else [],
                "last_family_id": last_family,
                "recent_fingerprints": [*recent_order, fingerprint][-30:],
            }
            self.issued14.setdefault(telegram_user_id, {})[problem_id] = problem
            self.outcomes14.setdefault(telegram_user_id, {})[problem_id] = "issued"
            return {**problem, "_transitioned": True}
        raise RuntimeError("Every task-14 candidate repeats a recent fingerprint")

    async def task14_state(self, telegram_user_id: int) -> dict[str, object] | None:
        return self.training14.get(telegram_user_id)

    async def set_task14_prompt_message(
        self,
        telegram_user_id: int,
        expected_problem_id: str,
        message_id: int,
        expected_status: str | None = None,
    ) -> bool:
        saved = self.training14.get(telegram_user_id)
        problem = saved.get("problem") if saved else None
        if (
            saved is None
            or not isinstance(problem, dict)
            or str(problem.get("problem_id")) != expected_problem_id
        ):
            return False
        state = cast(dict[str, object], saved["state"])
        if expected_status is not None and state.get("status") != expected_status:
            return False
        current = state.get("input_prompt_message_id")
        if isinstance(current, int) and message_id < current:
            return False
        state["input_prompt_message_id"] = message_id
        return True

    async def set_task14_condition_message(
        self, telegram_user_id: int, expected_problem_id: str, message_id: int
    ) -> bool:
        saved = self.training14.get(telegram_user_id)
        problem = saved.get("problem") if saved else None
        if (
            saved is None
            or not isinstance(problem, dict)
            or str(problem.get("problem_id")) != expected_problem_id
        ):
            return False
        state = cast(dict[str, object], saved["state"])
        state["problem_prompt_message_id"] = message_id
        state["input_prompt_message_id"] = message_id
        return True

    async def task14_attempt(
        self,
        telegram_user_id: int,
        expected_problem_id: str,
        raw_answer: str,
        is_correct: bool,
        telegram_message_id: int | None = None,
        expected_prompt_message_id: int | None = None,
    ) -> dict[str, object] | None:
        saved = self.training14.get(telegram_user_id)
        problem = saved.get("problem") if saved else None
        if saved is None or not isinstance(problem, dict):
            return None
        if (
            str(problem.get("problem_id")) != expected_problem_id
            or self.states.get(telegram_user_id) != "task14"
        ):
            return {"status": "stale", "attempt": 0}
        state = cast(dict[str, object], saved["state"])
        if (
            expected_prompt_message_id is not None
            and state.get("problem_prompt_message_id", state.get("input_prompt_message_id"))
            != expected_prompt_message_id
        ):
            return {"status": "stale", "attempt": 0}
        if (
            telegram_message_id is not None
            and expected_prompt_message_id is not None
            and telegram_message_id <= expected_prompt_message_id
        ):
            return {"status": "stale", "attempt": 0}
        if telegram_message_id is not None:
            key = (telegram_user_id, telegram_message_id)
            if key in self.processed_message_ids:
                return {"status": "duplicate", "attempt": 0}
            self.processed_message_ids.add(key)
        if state.get("status") != "active":
            return {
                "status": str(state.get("status", "finished")),
                "attempt": 0,
                "problem": problem,
            }
        attempt = _state_int(state, "attempts") + 1
        status = "solved" if is_correct else ("failed" if attempt == 2 else "active")
        state.update({"status": status, "attempts": attempt})
        self.attempts14.setdefault(telegram_user_id, []).append(
            {
                "problem_id": expected_problem_id,
                "attempt_no": attempt,
                "is_correct": is_correct,
                "raw_answer": raw_answer,
            }
        )
        if status in {"solved", "failed"}:
            self.outcomes14.setdefault(telegram_user_id, {})[expected_problem_id] = status
        return {"status": status, "attempt": attempt, "problem": problem}

    async def task14_hint(
        self,
        telegram_user_id: int,
        expected_problem_id: str,
        expected_prompt_message_id: int | None = None,
    ) -> str | None:
        saved = self.training14.get(telegram_user_id)
        problem = saved.get("problem") if saved else None
        if (
            saved is None
            or not isinstance(problem, dict)
            or self.states.get(telegram_user_id) != "task14"
        ):
            return None
        if str(problem.get("problem_id")) != expected_problem_id:
            return None
        state = cast(dict[str, object], saved["state"])
        if (
            expected_prompt_message_id is not None
            and state.get("input_prompt_message_id") != expected_prompt_message_id
        ):
            return None
        hints = problem.get("hints", [])
        used = _state_int(state, "hints_used")
        if state.get("status") != "active" or not isinstance(hints, list) or used >= len(hints):
            return None
        state.update({"hints_used": used + 1, "used_hint": True})
        self.hints14.setdefault(telegram_user_id, {})[expected_problem_id] = used + 1
        return str(hints[used])

    async def task14_reveal_solution(
        self,
        telegram_user_id: int,
        expected_problem_id: str,
        expected_prompt_message_id: int | None = None,
    ) -> dict[str, object] | None:
        saved = self.training14.get(telegram_user_id)
        problem = saved.get("problem") if saved else None
        if (
            saved is None
            or not isinstance(problem, dict)
            or self.states.get(telegram_user_id) != "task14"
        ):
            return None
        if str(problem.get("problem_id")) != expected_problem_id:
            return None
        state = cast(dict[str, object], saved["state"])
        if (
            expected_prompt_message_id is not None
            and state.get("input_prompt_message_id") != expected_prompt_message_id
        ):
            return None
        status = str(state.get("status", ""))
        if status == "active":
            state["status"] = "solution_viewed"
            self.outcomes14.setdefault(telegram_user_id, {})[expected_problem_id] = (
                "solution_viewed"
            )
        self.solutions14.setdefault(telegram_user_id, set()).add(expected_problem_id)
        return {"problem": problem, "status": status}

    async def task14_progress(self, telegram_user_id: int) -> dict[str, int]:
        issued = self.issued14.get(telegram_user_id, {})
        outcomes = self.outcomes14.get(telegram_user_id, {})
        attempts = self.attempts14.get(telegram_user_id, [])
        by_problem: dict[str, list[dict[str, object]]] = {}
        for attempt in attempts:
            by_problem.setdefault(str(attempt["problem_id"]), []).append(attempt)
        solved_first = sum(
            outcomes.get(pid) == "solved"
            and any(a["attempt_no"] == 1 and a["is_correct"] for a in values)
            for pid, values in by_problem.items()
        )
        solved_second = sum(
            outcomes.get(pid) == "solved"
            and any(a["attempt_no"] == 2 and a["is_correct"] for a in values)
            for pid, values in by_problem.items()
        )
        return {
            "issued": len(issued),
            "answered": len(by_problem),
            "correct": sum(outcome == "solved" for outcome in outcomes.values()),
            "solved_first_try": int(solved_first),
            "solved_second_try": int(solved_second),
            "attempts": len(attempts),
            "first_attempts": sum(attempt["attempt_no"] == 1 for attempt in attempts),
            "second_attempts": sum(attempt["attempt_no"] == 2 for attempt in attempts),
            "hints_used": sum(self.hints14.get(telegram_user_id, {}).values()),
            "solutions_viewed": len(self.solutions14.get(telegram_user_id, set())),
            "skipped": sum(outcome == "skipped" for outcome in outcomes.values()),
        }


async def read_migration(path: str) -> str:
    from pathlib import Path

    return Path(path).read_text(encoding="utf-8")


def _json_object(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return cast(dict[str, object], value)
    if isinstance(value, str):
        decoded = json.loads(value)
        if isinstance(decoded, dict):
            return cast(dict[str, object], decoded)
    raise TypeError("Expected a JSON object from PostgreSQL")


def _state_int(state: dict[str, object], key: str, default: int = 0) -> int:
    value = state.get(key, default)
    return value if isinstance(value, int) else default
