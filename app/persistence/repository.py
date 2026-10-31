import json
from typing import Protocol, cast
from uuid import UUID

import asyncpg


class Repository(Protocol):
    async def register_user(self, telegram_user_id: int) -> None: ...

    async def save_user_state(self, telegram_user_id: int, screen: str) -> None: ...

    async def user_state(self, telegram_user_id: int) -> str | None: ...

    async def current_session(self, telegram_user_id: int) -> dict[str, object] | None: ...

    async def ensure_task6_session(self, telegram_user_id: int) -> str: ...

    async def issue_task6_problem(
        self, telegram_user_id: int, problem: dict[str, object]
    ) -> dict[str, object]: ...

    async def task6_state(self, telegram_user_id: int) -> dict[str, object] | None: ...

    async def task6_attempt(
        self, telegram_user_id: int, raw_answer: str, is_correct: bool
    ) -> dict[str, object] | None: ...

    async def task6_hint(self, telegram_user_id: int) -> str | None: ...

    async def task6_finish_problem(self, telegram_user_id: int, status: str) -> None: ...

    async def task6_progress(self, telegram_user_id: int) -> dict[str, int]: ...

    async def claim_update(self, update_id: int) -> bool: ...

    async def finish_update(self, update_id: int, *, failed: bool = False) -> None: ...


class PostgresRepository:
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
            "UPDATE users SET current_state = jsonb_build_object('screen', $2::text) "
            "WHERE telegram_user_id = $1",
            telegram_user_id,
            screen,
        )

    async def user_state(self, telegram_user_id: int) -> str | None:
        state = await self._pool.fetchval(
            "SELECT current_state ->> 'screen' FROM users WHERE telegram_user_id = $1",
            telegram_user_id,
        )
        return cast(str | None, state)

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

    async def issue_task6_problem(
        self, telegram_user_id: int, problem: dict[str, object]
    ) -> dict[str, object]:
        async with self._pool.acquire() as connection, connection.transaction():
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
            if row["active_problem_id"] is not None and state.get("status") == "active":
                current = await connection.fetchval(
                    "SELECT snapshot FROM issued_problems WHERE id = $1",
                    row["active_problem_id"],
                )
                if current is not None:
                    return _json_object(current)
            problem_id = UUID(str(problem["problem_id"]))
            await connection.execute(
                """INSERT INTO issued_problems
                   (id, user_id, session_id, family_id, generator_version, seed,
                    fingerprint, shape_fingerprint, snapshot)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb)
                   ON CONFLICT (id) DO NOTHING""",
                problem_id,
                row["user_id"],
                row["id"],
                problem["family_id"],
                problem["generator_version"],
                problem["seed"],
                problem["fingerprint"],
                problem["reference_structure_id"],
                json.dumps(problem, ensure_ascii=False),
            )
            await connection.execute(
                """UPDATE sessions SET active_problem_id = $2,
                   state = $3::jsonb WHERE id = $1""",
                row["id"],
                problem_id,
                json.dumps({"status": "active", "attempts": 0, "used_hint": False}),
            )
            return problem

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

    async def task6_attempt(
        self, telegram_user_id: int, raw_answer: str, is_correct: bool
    ) -> dict[str, object] | None:
        async with self._pool.acquire() as connection, connection.transaction():
            row = await connection.fetchrow(
                """SELECT s.id AS session_id, s.state, s.active_problem_id,
                          p.user_id, p.snapshot
                   FROM sessions s JOIN users u ON u.id = s.user_id
                   JOIN issued_problems p ON p.id = s.active_problem_id
                   WHERE u.telegram_user_id = $1 AND s.mode = 'task6'
                     AND s.finished_at IS NULL
                   ORDER BY s.started_at DESC LIMIT 1 FOR UPDATE OF s""",
                telegram_user_id,
            )
            if row is None:
                return None
            state = _json_object(row["state"])
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
                    is_correct, used_hint)
                   VALUES ($1, $2, $3, $4, $4, $5, $6)""",
                row["active_problem_id"],
                row["user_id"],
                attempt,
                raw_answer[:200],
                is_correct,
                bool(state.get("used_hint", False)),
            )
            state.update({"status": status, "attempts": attempt})
            await connection.execute(
                "UPDATE sessions SET state = $2::jsonb WHERE id = $1",
                row["session_id"],
                json.dumps(state),
            )
            return {"status": status, "attempt": attempt, "problem": snapshot}

    async def task6_hint(self, telegram_user_id: int) -> str | None:
        async with self._pool.acquire() as connection, connection.transaction():
            row = await connection.fetchrow(
                """SELECT s.id, s.state, p.snapshot FROM sessions s
                   JOIN users u ON u.id = s.user_id
                   JOIN issued_problems p ON p.id = s.active_problem_id
                   WHERE u.telegram_user_id = $1 AND s.mode = 'task6'
                     AND s.finished_at IS NULL
                   ORDER BY s.started_at DESC LIMIT 1 FOR UPDATE OF s""",
                telegram_user_id,
            )
            if row is None:
                return None
            state = _json_object(row["state"])
            problem = _json_object(row["snapshot"])
            if state.get("status") != "active":
                return None
            hints = problem.get("hints", [])
            state["used_hint"] = True
            await connection.execute(
                "UPDATE sessions SET state = $2::jsonb WHERE id = $1",
                row["id"],
                json.dumps(state),
            )
            return str(hints[0]) if isinstance(hints, list) and hints else None

    async def task6_finish_problem(self, telegram_user_id: int, status: str) -> None:
        if status not in {"skipped", "menu"}:
            raise ValueError("Invalid task-6 final state")
        await self._pool.execute(
            """UPDATE sessions s SET state = jsonb_set(s.state, '{status}', to_jsonb($2::text))
               FROM users u WHERE s.user_id = u.id AND u.telegram_user_id = $1
                 AND s.mode = 'task6' AND s.finished_at IS NULL
                 AND s.state ->> 'status' = 'active'""",
            telegram_user_id,
            status,
        )

    async def task6_progress(self, telegram_user_id: int) -> dict[str, int]:
        row = await self._pool.fetchrow(
            """SELECT count(DISTINCT p.id)::int AS issued,
                      count(DISTINCT p.id) FILTER (WHERE a.problem_id IS NOT NULL)::int AS answered,
                      count(DISTINCT p.id) FILTER (WHERE a.is_correct)::int AS correct,
                      count(a.id)::int AS attempts
               FROM users u
               LEFT JOIN issued_problems p ON p.user_id = u.id
               LEFT JOIN sessions s ON s.id = p.session_id AND s.mode = 'task6'
               LEFT JOIN attempts a ON a.problem_id = p.id
               WHERE u.telegram_user_id = $1 AND (p.id IS NULL OR s.id IS NOT NULL)""",
            telegram_user_id,
        )
        if row is None:
            return {"issued": 0, "answered": 0, "correct": 0, "attempts": 0}
        return {key: int(row[key]) for key in ("issued", "answered", "correct", "attempts")}

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
        self.updates: dict[int, str] = {}
        self.sessions: dict[int, dict[str, object]] = {}
        self.training: dict[int, dict[str, object]] = {}
        self.issued_history: dict[int, dict[str, dict[str, object]]] = {}
        self.attempt_history: dict[int, int] = {}
        self.answered_history: dict[int, set[str]] = {}
        self.solved_history: dict[int, set[str]] = {}

    async def register_user(self, telegram_user_id: int) -> None:
        self.users.add(telegram_user_id)

    async def save_user_state(self, telegram_user_id: int, screen: str) -> None:
        self.states[telegram_user_id] = screen

    async def user_state(self, telegram_user_id: int) -> str | None:
        return self.states.get(telegram_user_id)

    async def current_session(self, telegram_user_id: int) -> dict[str, object] | None:
        return self.sessions.get(telegram_user_id)

    async def ensure_task6_session(self, telegram_user_id: int) -> str:
        state = self.training.setdefault(
            telegram_user_id,
            {"session_id": f"memory-{telegram_user_id}", "state": {}, "problem": None},
        )
        return str(state["session_id"])

    async def issue_task6_problem(
        self, telegram_user_id: int, problem: dict[str, object]
    ) -> dict[str, object]:
        state = self.training[telegram_user_id]
        session_state = cast(dict[str, object], state["state"])
        if state.get("problem") is not None and session_state.get("status") == "active":
            return cast(dict[str, object], state["problem"])
        state["problem"] = problem
        state["state"] = {"status": "active", "attempts": 0, "used_hint": False}
        problem_id = str(problem.get("problem_id", ""))
        if problem_id:
            self.issued_history.setdefault(telegram_user_id, {})[problem_id] = problem
        return problem

    async def task6_state(self, telegram_user_id: int) -> dict[str, object] | None:
        state = self.training.get(telegram_user_id)
        return state

    async def task6_attempt(
        self, telegram_user_id: int, raw_answer: str, is_correct: bool
    ) -> dict[str, object] | None:
        del raw_answer
        state = self.training.get(telegram_user_id)
        if state is None or state.get("problem") is None:
            return None
        session_state = cast(dict[str, object], state["state"])
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
        problem_id = str(cast(dict[str, object], state["problem"]).get("problem_id", ""))
        self.attempt_history[telegram_user_id] = self.attempt_history.get(telegram_user_id, 0) + 1
        if problem_id:
            self.answered_history.setdefault(telegram_user_id, set()).add(problem_id)
            if is_correct:
                self.solved_history.setdefault(telegram_user_id, set()).add(problem_id)
        return {"status": status, "attempt": attempt, "problem": state["problem"]}

    async def task6_progress(self, telegram_user_id: int) -> dict[str, int]:
        issued = self.issued_history.get(telegram_user_id, {})
        return {
            "issued": len(issued),
            "answered": len(self.answered_history.get(telegram_user_id, set())),
            "correct": len(self.solved_history.get(telegram_user_id, set())),
            "attempts": self.attempt_history.get(telegram_user_id, 0),
        }

    async def task6_hint(self, telegram_user_id: int) -> str | None:
        state = self.training.get(telegram_user_id)
        if state is None or state.get("problem") is None:
            return None
        session_state = cast(dict[str, object], state["state"])
        if session_state.get("status") != "active":
            return None
        session_state["used_hint"] = True
        problem = cast(dict[str, object], state["problem"])
        hints = problem.get("hints", [])
        return str(hints[0]) if isinstance(hints, list) and hints else None

    async def task6_finish_problem(self, telegram_user_id: int, status: str) -> None:
        state = self.training.get(telegram_user_id)
        if state is not None:
            session_state = cast(dict[str, object], state["state"])
            if session_state.get("status") == "active":
                session_state["status"] = status

    async def claim_update(self, update_id: int) -> bool:
        state = self.updates.get(update_id)
        if state is None or state == "failed":
            self.updates[update_id] = "processing"
            return True
        return False

    async def finish_update(self, update_id: int, *, failed: bool = False) -> None:
        self.updates[update_id] = "failed" if failed else "processed"


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
