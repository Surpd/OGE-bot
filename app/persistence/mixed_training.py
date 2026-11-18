"""Durable identity and atomic transitions for the mixed first-part exercise."""

from __future__ import annotations

import json
import secrets
from hashlib import sha256
from typing import Any, cast
from uuid import UUID, uuid4


def _object(value: object) -> dict[str, object]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return dict(value) if isinstance(value, dict) else {}


def _digest(value: dict[str, object]) -> str:
    return sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _as_int(value: object, default: int = 0) -> int:
    return value if isinstance(value, int) else default


def _int_list(value: object) -> list[int]:
    return [item for item in value if isinstance(item, int)] if isinstance(value, list) else []


_AFTER_FIELDS = {
    "_family_queue_after": "family_queue",
    "_last_family_after": "last_family_id",
    "_last_group_after": "last_group",
    "_group_run_length_after": "group_run_length",
    "_recent_proposition_ids_after": "recent_proposition_ids",
    "_correct_position_counts_after": "correct_position_counts",
}


def _capture_scheduler_state(
    state: dict[str, object], number: int, snapshot: dict[str, object]
) -> dict[str, object]:
    generators = _object(state.get("generator_states"))
    current = _object(generators.get(str(number)))
    for source, target in _AFTER_FIELDS.items():
        if source in snapshot:
            current[target] = snapshot[source]
    fingerprint = snapshot.get("fingerprint")
    if isinstance(fingerprint, str):
        recent = current.get("recent_fingerprints", [])
        recent_values = (
            [item for item in recent if isinstance(item, str)]
            if isinstance(recent, list)
            else []
        )
        current["recent_fingerprints"] = [*recent_values, fingerprint][-30:]
    generators[str(number)] = current
    state["generator_states"] = generators
    return {
        key: value
        for key, value in snapshot.items()
        if key not in _AFTER_FIELDS
    }


class MixedTrainingRepository:
    """Stores mixed sessions separately from ordinary taskN sessions."""

    def __init__(self, repository: Any) -> None:
        self._repository = repository
        self._pool = getattr(repository, "_pool", None)
        if self._pool is None:
            if not hasattr(repository, "_mixed_training_sessions"):
                repository._mixed_training_sessions = {}
            if not hasattr(repository, "_mixed_training_records"):
                repository._mixed_training_records = {}

    async def start(self, user_id: int, available_numbers: list[int]) -> dict[str, object]:
        if self._pool is None:
            sessions = self._repository._mixed_training_sessions
            current = sessions.get(user_id)
            if current is not None and current["status"] != "completed":
                current["status"] = "active"
                await self._repository.save_user_state(user_id, "mixed")
                return cast(dict[str, object], current)
            numbers = list(available_numbers)
            secrets.SystemRandom().shuffle(numbers)
            if len(numbers) > 1 and current and numbers[0] == current.get("last_number"):
                numbers[0], numbers[1] = numbers[1], numbers[0]
            session = {
                "id": str(uuid4()),
                "status": "active",
                "revision": 0,
                "state": {
                    "available_numbers": available_numbers,
                    "queue": numbers,
                    "current_number": None,
                    "active_problem_id": None,
                    "scenario_snapshot": None,
                    "scenario_position": None,
                    "last_number": None,
                },
            }
            sessions[user_id] = session
            await self._repository.save_user_state(user_id, "mixed")
            return session
        async with self._pool.acquire() as connection, connection.transaction():
            user = await connection.fetchrow(
                """INSERT INTO users (telegram_user_id) VALUES ($1)
                   ON CONFLICT (telegram_user_id) DO UPDATE
                     SET telegram_user_id=EXCLUDED.telegram_user_id
                   RETURNING id""",
                user_id,
            )
            row = await connection.fetchrow(
                """SELECT id,status,revision,state FROM mixed_training_sessions
                   WHERE user_id=$1 AND status <> 'completed' FOR UPDATE""",
                user["id"],
            )
            if row is None:
                queue = list(available_numbers)
                secrets.SystemRandom().shuffle(queue)
                state = {
                    "available_numbers": available_numbers,
                    "queue": queue,
                    "current_number": None,
                    "active_problem_id": None,
                    "scenario_snapshot": None,
                    "scenario_position": None,
                    "last_number": None,
                }
                row = await connection.fetchrow(
                    """INSERT INTO mixed_training_sessions (user_id,state)
                       VALUES ($1,$2::jsonb) RETURNING id,status,revision,state""",
                    user["id"],
                    json.dumps(state, ensure_ascii=False),
                )
            else:
                await connection.execute(
                    """UPDATE mixed_training_sessions
                       SET status='active',updated_at=now() WHERE id=$1""",
                    row["id"],
                )
            await connection.execute(
                """UPDATE users SET current_state=jsonb_build_object(
                   'screen','mixed','resume_mode','mixed') WHERE id=$1""",
                user["id"],
            )
            return await self._load_row(connection, row["id"])

    async def state(self, user_id: int) -> dict[str, object] | None:
        if self._pool is None:
            return cast(dict[str, object] | None,
                        self._repository._mixed_training_sessions.get(user_id))
        row = await self._pool.fetchrow(
            """SELECT s.id,s.status,s.revision,s.state,p.id AS problem_id,p.number,
                      p.family_id,p.fingerprint,p.snapshot,p.snapshot_sha256,p.outcome,p.attempts,p.hints_used,
                      p.prompt_message_id
               FROM mixed_training_sessions s JOIN users u ON u.id=s.user_id
               LEFT JOIN mixed_training_problems p ON p.id=(s.state->>'active_problem_id')::uuid
               WHERE u.telegram_user_id=$1 AND s.status <> 'completed'""",
            user_id,
        )
        if row is None:
            return None
        result: dict[str, object] = {
            "id": str(row["id"]),
            "status": row["status"],
            "revision": int(row["revision"]),
            "state": _object(row["state"]),
        }
        if row["problem_id"] is not None:
            problem_snapshot = _object(row["snapshot"])
            result["problem"] = {
                "problem_id": str(row["problem_id"]),
                "number": int(row["number"]),
                "family_id": row["family_id"],
                "fingerprint": row["fingerprint"],
                **problem_snapshot,
                "outcome": row["outcome"],
                "attempts": int(row["attempts"]),
                "hints_used": int(row["hints_used"]),
                "prompt_message_id": row["prompt_message_id"],
            }
            if _digest(_object(row["snapshot"])) != str(row["snapshot_sha256"]).strip():
                raise ValueError("Mixed training snapshot hash mismatch")
            if int(row["number"]) <= 5:
                saved_scenario = _object(result["state"]).get("scenario_snapshot")
                if isinstance(saved_scenario, dict):
                    cast(dict[str, object], result["problem"])[
                        "scenario_snapshot"
                    ] = saved_scenario
        return result

    async def expected_number(self, user_id: int) -> tuple[int, int] | None:
        state = await self.state(user_id)
        if state is None:
            return None
        data = _object(state.get("state"))
        number = data.get("current_number")
        queue = data.get("queue")
        if number is None and isinstance(queue, list) and queue:
            return _as_int(queue[0]), _as_int(state.get("revision"))
        if isinstance(number, int):
            return _as_int(number), _as_int(state.get("revision"))
        return None

    async def issue_current(
        self,
        user_id: int,
        expected_revision: int,
        number: int,
        snapshot: dict[str, object],
        *,
        scenario_snapshot: dict[str, object] | None = None,
    ) -> dict[str, object] | None:
        if self._pool is None:
            session = self._repository._mixed_training_sessions.get(user_id)
            if (
                session is None
                or session["status"] != "active"
                or session["revision"] != expected_revision
            ):
                return None
            state = session["state"]
            if state.get("active_problem_id"):
                return cast(dict[str, object] | None, session.get("problem"))
            if state.get("current_number") is None:
                queue = state.get("queue", [])
                if not queue or _as_int(queue[0]) != number:
                    return None
                state["queue"] = queue[1:]
                state["current_number"] = number
            if state.get("current_number") != number:
                return None
            if scenario_snapshot is not None:
                state["scenario_snapshot"] = scenario_snapshot
                state["scenario_snapshot_sha256"] = _digest(scenario_snapshot)
                state["scenario_position"] = 1
            snapshot = _capture_scheduler_state(state, number, snapshot)
            problem_id = str(snapshot.get("problem_id") or uuid4())
            try:
                UUID(problem_id)
            except ValueError:
                problem_id = str(uuid4())
            snapshot = {**snapshot, "problem_id": problem_id, "mixed_number": number}
            session["problem"] = {
                **snapshot,
                "problem_id": problem_id,
                "number": number,
                "family_id": str(snapshot.get("family_id", f"OGE{number:02}-MIXED")),
                "fingerprint": str(snapshot.get("fingerprint", problem_id)),
                "outcome": "issued",
                "attempts": 0,
                "hints_used": 0,
            }
            session["problem"]["_snapshot_sha256"] = _digest(snapshot)
            record_snapshot = {
                key: value for key, value in snapshot.items() if key != "scenario_snapshot"
            }
            self._repository._mixed_training_records.setdefault(user_id, []).append(
                {
                    **{key: value for key, value in session["problem"].items()
                       if key != "scenario_snapshot"},
                    "id": problem_id,
                    "record_id": f"m:{problem_id}",
                    "attempt_records": [],
                    "issued_at": None,
                    "snapshot": record_snapshot,
                }
            )
            state["active_problem_id"] = problem_id
            session["revision"] += 1
            return cast(dict[str, object], session["problem"])
        async with self._pool.acquire() as connection, connection.transaction():
            row = await connection.fetchrow(
                """SELECT s.id,s.status,s.revision,s.state FROM mixed_training_sessions s
                   JOIN users u ON u.id=s.user_id WHERE u.telegram_user_id=$1 FOR UPDATE OF s""",
                user_id,
            )
            if (
                row is None
                or row["status"] != "active"
                or int(row["revision"]) != expected_revision
            ):
                return None
            state = _object(row["state"])
            scenario = state.get("scenario_snapshot")
            if isinstance(scenario, dict) and _digest(scenario) != state.get(
                "scenario_snapshot_sha256"
            ):
                raise ValueError("Mixed scenario snapshot hash mismatch")
            if state.get("active_problem_id"):
                return None
            if state.get("current_number") is None:
                queue = state.get("queue", [])
                if not isinstance(queue, list) or not queue or int(queue[0]) != number:
                    return None
                state["queue"] = queue[1:]
                state["current_number"] = number
            if state.get("current_number") != number:
                return None
            if scenario_snapshot is not None:
                state["scenario_snapshot"] = scenario_snapshot
                state["scenario_snapshot_sha256"] = _digest(scenario_snapshot)
                state["scenario_position"] = 1
            snapshot = _capture_scheduler_state(state, number, snapshot)
            try:
                problem_uuid = UUID(str(snapshot.get("problem_id") or uuid4()))
            except ValueError:
                problem_uuid = uuid4()
            problem_id_pg = problem_uuid
            family = str(snapshot.get("family_id", f"OGE{number:02}-MIXED"))
            fingerprint = str(snapshot.get("fingerprint", problem_id_pg))
            stored_snapshot = {
                key: value for key, value in snapshot.items() if key != "scenario_snapshot"
            }
            stored_snapshot.update(problem_id=str(problem_id_pg), mixed_number=number)
            await connection.execute(
                """INSERT INTO mixed_training_problems
                   (id,session_id,number,family_id,fingerprint,snapshot,snapshot_sha256)
                   VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7)""",
                problem_id_pg,
                row["id"],
                number,
                family,
                fingerprint,
                json.dumps(stored_snapshot, ensure_ascii=False),
                _digest(stored_snapshot),
            )
            state["active_problem_id"] = str(problem_id_pg)
            await connection.execute(
                """UPDATE mixed_training_sessions SET state=$2::jsonb,revision=revision+1,
                   updated_at=now() WHERE id=$1""",
                row["id"],
                json.dumps(state, ensure_ascii=False),
            )
            return {
                **stored_snapshot,
                "number": number,
                "family_id": family,
                "fingerprint": fingerprint,
                "outcome": "issued",
                "attempts": 0,
                "hints_used": 0,
                **(
                    {"scenario_snapshot": state["scenario_snapshot"]}
                    if number <= 5 and isinstance(state.get("scenario_snapshot"), dict)
                    else {}
                ),
            }

    async def set_prompt(self, user_id: int, problem_id: str, message_id: int) -> bool:
        if self._pool is None:
            session = self._repository._mixed_training_sessions.get(user_id)
            if (
                not session
                or not session.get("problem")
                or session["problem"]["problem_id"] != problem_id
            ):
                return False
            session["problem"]["prompt_message_id"] = message_id
            return True
        result = await self._pool.execute(
            """UPDATE mixed_training_problems p SET prompt_message_id=$3
               FROM mixed_training_sessions s,users u
               WHERE p.id=$2::uuid AND s.id=p.session_id AND u.id=s.user_id
                 AND u.telegram_user_id=$1 AND s.status='active'
                 AND s.state->>'active_problem_id'=p.id::text""",
            user_id,
            problem_id,
            message_id,
        )
        return bool(result.endswith(" 1"))

    async def answer(
        self,
        user_id: int,
        problem_id: str,
        raw: str,
        correct: bool,
        message_id: int,
        reply_to: int | None,
    ) -> dict[str, object] | None:
        if self._pool is None:
            session = self._repository._mixed_training_sessions.get(user_id)
            problem = session.get("problem") if session else None
            if not session or not problem or problem["problem_id"] != problem_id:
                return None
            if reply_to is not None and problem.get("prompt_message_id") != reply_to:
                return {"status": "stale"}
            if message_id in session.setdefault("message_ids", set()):
                return {"status": "duplicate"}
            session["message_ids"].add(message_id)
            if problem.get("outcome") != "issued":
                return {"status": str(problem.get("outcome")), "problem": problem}
            attempt = int(problem.get("attempts", 0)) + 1
            outcome = "solved" if correct else ("failed" if attempt >= 2 else "issued")
            problem.update(attempts=attempt, outcome=outcome)
            record = next(
                (
                    item
                    for item in reversed(self._repository._mixed_training_records[user_id])
                    if item.get("problem_id") == problem_id
                ),
                None,
            )
            if record is not None:
                record.update(attempts=attempt, outcome=outcome)
                attempts = record.setdefault("attempt_records", [])
                if isinstance(attempts, list):
                    attempts.append(
                        {
                            "problem_id": problem_id,
                            "attempt_no": attempt,
                            "is_correct": correct,
                            "used_hint": int(problem.get("hints_used", 0)) > 0,
                        }
                    )
            return {
                "status": "active" if outcome == "issued" else outcome,
                "attempt": attempt,
                "problem": problem,
            }
        async with self._pool.acquire() as connection, connection.transaction():
            session = await connection.fetchrow(
                """SELECT s.id,s.state FROM mixed_training_sessions s JOIN users u ON u.id=s.user_id
                   WHERE u.telegram_user_id=$1 AND s.status='active' FOR UPDATE OF s""",
                user_id,
            )
            if session is None or _object(session["state"]).get("active_problem_id") != problem_id:
                return {"status": "stale"}
            problem = await connection.fetchrow(
                "SELECT * FROM mixed_training_problems WHERE id=$1::uuid FOR UPDATE",
                problem_id,
            )
            if problem is None:
                return {"status": "stale"}
            if reply_to is not None and problem["prompt_message_id"] != reply_to:
                return {"status": "stale"}
            if problem["outcome"] != "issued":
                return {"status": str(problem["outcome"]), "problem": _object(problem["snapshot"])}
            try:
                attempt_no = int(problem["attempts"]) + 1
                status = "solved" if correct else ("failed" if attempt_no >= 2 else "issued")
                await connection.execute(
                    """INSERT INTO mixed_training_attempts
                       (problem_id,attempt_no,telegram_message_id,raw_answer,is_correct,used_hint)
                       VALUES ($1,$2,$3,$4,$5,$6)""",
                    problem_id,
                    attempt_no,
                    message_id,
                    raw[:200],
                    correct,
                    int(problem["hints_used"]) > 0,
                )
            except Exception as exc:
                if "unique" in str(exc).lower():
                    return {"status": "duplicate"}
                raise
            await connection.execute(
                """UPDATE mixed_training_problems SET attempts=$2,outcome=$3 WHERE id=$1""",
                problem_id,
                attempt_no,
                status,
            )
            snap = _object(problem["snapshot"])
            return {
                "status": "active" if status == "issued" else status,
                "attempt": attempt_no,
                "problem": {**snap, "problem_id": problem_id},
            }

    async def action(self, user_id: int, problem_id: str, action: str) -> bool:
        """Atomically record one hint, solution reveal, skip, or pause."""
        if self._pool is None:
            session = self._repository._mixed_training_sessions.get(user_id)
            problem = session.get("problem") if session else None
            if not problem or problem["problem_id"] != problem_id:
                return False
            if problem.get("outcome") != "issued" and action != "pause":
                return False
            if action == "hint":
                hints = problem.get("hints", [])
                used = int(problem.get("hints_used", 0))
                if not isinstance(hints, list) or used >= len(hints):
                    return False
                problem["hints_used"] = used + 1
                problem["last_hint"] = str(hints[used])
            elif action == "solution":
                problem["outcome"] = "solution_viewed"
            elif action == "skip":
                problem["outcome"] = "skipped"
            elif action == "pause":
                session["status"] = "paused"
            else:
                return False
            record = next(
                (
                    item
                    for item in reversed(self._repository._mixed_training_records[user_id])
                    if item.get("problem_id") == problem_id
                ),
                None,
            )
            if record is not None:
                record["outcome"] = problem.get("outcome")
                record["hints_used"] = problem.get("hints_used", 0)
                record["solution_viewed"] = action == "solution"
            return True
        async with self._pool.acquire() as connection, connection.transaction():
            row = await connection.fetchrow(
                """SELECT s.id,s.state,p.snapshot,p.outcome,p.hints_used
                   FROM mixed_training_sessions s JOIN users u ON u.id=s.user_id
                   JOIN mixed_training_problems p ON p.id=(s.state->>'active_problem_id')::uuid
                   WHERE u.telegram_user_id=$1 AND s.status='active' AND p.id=$2::uuid
                   FOR UPDATE OF s,p""",
                user_id,
                problem_id,
            )
            if row is None:
                return False
            if row["outcome"] != "issued" and action != "pause":
                return False
            snap = _object(row["snapshot"])
            if action == "hint":
                hints = snap.get("hints", [])
                used = int(row["hints_used"])
                if not isinstance(hints, list) or used >= len(hints):
                    return False
                await connection.execute(
                    "UPDATE mixed_training_problems SET hints_used=hints_used+1 WHERE id=$1",
                    problem_id,
                )
            elif action == "solution":
                await connection.execute(
                    """UPDATE mixed_training_problems SET outcome='solution_viewed',
                       solution_viewed_at=COALESCE(solution_viewed_at,now()) WHERE id=$1
                       AND outcome='issued'""",
                    problem_id,
                )
            elif action == "skip":
                await connection.execute(
                    """UPDATE mixed_training_problems SET outcome='skipped'
                       WHERE id=$1 AND outcome='issued'""",
                    problem_id,
                )
            elif action == "pause":
                await connection.execute(
                    "UPDATE mixed_training_sessions SET status='paused' WHERE id=$1",
                    row["id"],
                )
                return True
            else:
                return False
            return True

    async def advance(
        self,
        user_id: int,
        problem_id: str,
        next_snapshot: dict[str, object] | None,
        next_number: int | None,
        new_cycle: list[int] | None = None,
        scenario_snapshot: dict[str, object] | None = None,
    ) -> dict[str, object] | None:
        if self._pool is None:
            session = self._repository._mixed_training_sessions.get(user_id)
            problem = session.get("problem") if session else None
            if not session or not problem or problem["problem_id"] != problem_id:
                return None
            if problem.get("outcome") == "issued":
                return None
            state = session["state"]
            if (
                state.get("scenario_snapshot") is not None
                and _as_int(state.get("scenario_position"), 1) < 5
            ):
                pos = _as_int(state.get("scenario_position"), 1) + 1
                state["scenario_position"] = pos
                state["current_number"] = pos
                state["active_problem_id"] = None
                session["problem"] = None
                session["revision"] += 1
                snap = _scenario_question(state["scenario_snapshot"], pos)
                return await self.issue_current(user_id, session["revision"], pos, snap)
            if next_number is None or next_snapshot is None:
                return None
            state["last_number"] = problem.get("number")
            state["scenario_snapshot"] = None
            state["scenario_snapshot_sha256"] = None
            state["scenario_position"] = None
            queue = state.get("queue", [])
            if not isinstance(queue, list) or not queue:
                queue = list(new_cycle) if new_cycle else _int_list(state.get("available_numbers"))
                if len(queue) > 1 and queue[0] == state["last_number"]:
                    queue[0], queue[1] = queue[1], queue[0]
                state["queue"] = queue
            if int(queue[0]) != next_number:
                return None
            state["queue"] = queue[1:]
            state["current_number"] = next_number
            state["active_problem_id"] = None
            session["problem"] = None
            session["revision"] += 1
            return await self.issue_current(
                user_id,
                session["revision"],
                next_number,
                next_snapshot,
                scenario_snapshot=scenario_snapshot if next_number == 1 else None,
            )
        async with self._pool.acquire() as connection, connection.transaction():
            row = await connection.fetchrow(
                """SELECT s.id,s.status,s.revision,s.state,p.number,p.outcome
                   FROM mixed_training_sessions s
                   JOIN users u ON u.id=s.user_id JOIN mixed_training_problems p
                     ON p.id=(s.state->>'active_problem_id')::uuid
                   WHERE u.telegram_user_id=$1 AND s.status='active' AND p.id=$2::uuid
                   FOR UPDATE OF s,p""",
                user_id,
                problem_id,
            )
            if row is None:
                return None
            if row["outcome"] == "issued":
                return None
            state = _object(row["state"])
            scenario = state.get("scenario_snapshot")
            position = _as_int(state.get("scenario_position"), 1)
            if isinstance(scenario, dict) and position < 5:
                number = position + 1
                snap = _scenario_question(scenario, number)
                state["scenario_position"] = number
                state["current_number"] = number
                state["active_problem_id"] = None
                await connection.execute(
                    """UPDATE mixed_training_sessions SET state=$2::jsonb,
                       revision=revision+1 WHERE id=$1""",
                    row["id"],
                    json.dumps(state, ensure_ascii=False),
                )
                # The caller renders this immutable question; next request claims it.
                return {
                    "number": number,
                    "pending_snapshot": snap,
                    "expected_revision": int(row["revision"]) + 1,
                }
            queue = state.get("queue", [])
            if not isinstance(queue, list) or not queue:
                queue = list(new_cycle) if new_cycle else _int_list(
                    state.get("available_numbers")
                )
                if not new_cycle:
                    secrets.SystemRandom().shuffle(queue)
                previous = int(row["number"])
                if len(queue) > 1 and int(queue[0]) == previous:
                    queue[0], queue[1] = queue[1], queue[0]
            if not queue:
                await connection.execute(
                    """UPDATE mixed_training_sessions SET status='completed',
                       finished_at=now() WHERE id=$1""",
                    row["id"],
                )
                return None
            number = int(queue[0])
            state.update(
                {
                    "queue": queue[1:],
                    "current_number": number,
                    "active_problem_id": None,
                    "last_number": int(row["number"]),
                    "scenario_snapshot": None,
                    "scenario_snapshot_sha256": None,
                    "scenario_position": None,
                }
            )
            if number == 1 and scenario_snapshot is not None:
                state["scenario_snapshot"] = scenario_snapshot
                state["scenario_snapshot_sha256"] = _digest(scenario_snapshot)
                state["scenario_position"] = 1
            await connection.execute(
                """UPDATE mixed_training_sessions SET state=$2::jsonb,revision=revision+1,
                   updated_at=now() WHERE id=$1""",
                row["id"],
                json.dumps(state, ensure_ascii=False),
            )
            return {
                "number": number,
                "expected_revision": int(row["revision"]) + 1,
                "pending_snapshot": next_snapshot,
                "scenario_snapshot": scenario_snapshot if number == 1 else None,
            }

    async def pause(self, user_id: int) -> None:
        if self._pool is None:
            session = self._repository._mixed_training_sessions.get(user_id)
            if session:
                session["status"] = "paused"
            return
        await self._pool.execute(
            """UPDATE mixed_training_sessions s SET status='paused',updated_at=now()
               FROM users u WHERE u.id=s.user_id AND u.telegram_user_id=$1 AND s.status='active'""",
            user_id,
        )

    async def _load_row(self, connection: Any, session_id: UUID) -> dict[str, object]:
        row = await connection.fetchrow(
            """SELECT id,status,revision,state FROM mixed_training_sessions WHERE id=$1""",
            session_id,
        )
        return {
            "id": str(row["id"]),
            "status": row["status"],
            "revision": int(row["revision"]),
            "state": _object(row["state"]),
        }


def _scenario_question(snapshot: dict[str, object], position: int) -> dict[str, object]:
    from app.math.scenario_engine import ScenarioSnapshot

    restored = ScenarioSnapshot.from_snapshot(snapshot)
    question = restored.questions[position - 1]
    return {
        **question.to_snapshot(),
        "condition": question.condition,
        "correct_answer": question.canonical_answer,
        "solution": list(question.solution_steps),
        "hints": list(question.hints),
        "family_id": question.family_id,
        "fingerprint": f"{restored.story_code}:{restored.seed}:{position}",
        "problem_id": f"mixed-scenario-{restored.seed}-{position}",
        "shared_context": restored.shared_context,
        "story_code": restored.story_code,
        "scenario_seed": restored.seed,
        "scenario_snapshot": snapshot,
    }
