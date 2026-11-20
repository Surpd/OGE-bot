"""One-time, reference-only practice replays for confirmed mistakes.

This module deliberately stores no task snapshot or image payload. Original
conditions are resolved from their owning training repository on each open.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
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


@dataclass(frozen=True, slots=True)
class ReplaySource:
    source_type: str
    source_id: UUID
    source_position: int
    number: int
    snapshot: dict[str, object]
    scenario_snapshot: dict[str, object] | None = None

    @property
    def condition(self) -> str:
        return str(self.snapshot.get("condition", ""))

    @property
    def correct_answer(self) -> str:
        return str(self.snapshot.get("correct_answer", self.snapshot.get("canonical_answer", "")))


class ReplayAlreadyActive(RuntimeError):
    """A user's existing replay must be completed or resumed first."""


def parse_record_ref(record_id: str) -> tuple[str, UUID, int]:
    """Translate existing progress IDs into a normalized, owner-scoped source ref."""
    parts = record_id.split(":")
    try:
        if len(parts) == 2 and parts[0] == "o":
            return "ordinary", UUID(parts[1]), 0
        if len(parts) == 2 and parts[0] == "m":
            return "mixed", UUID(parts[1]), 0
        if len(parts) == 3 and parts[0] == "s" and parts[2].isascii() and parts[2].isdigit():
            position = int(parts[2])
            if position in range(1, 6):
                return "scenario", UUID(parts[1]), position
    except ValueError:
        pass
    raise ValueError("Unknown original task reference")


async def load_replay_source(
    repository: Any, telegram_user_id: int, record_id: str
) -> ReplaySource:
    """Load a confirmed mistake for a scored replay."""
    return await load_original_source(repository, telegram_user_id, record_id, require_error=True)


async def load_original_source(
    repository: Any, telegram_user_id: int, record_id: str, *, require_error: bool = False,
) -> ReplaySource:
    """Prove that the owner can still see the exact issued question and materials."""
    source_type, source_id, position = parse_record_ref(record_id)
    if not hasattr(repository, "_pool"):
        return await _load_memory_source(repository, telegram_user_id, record_id, source_type,
                                         source_id, position, require_error=require_error)
    pool = repository._pool
    if source_type == "ordinary":
        row = await pool.fetchrow(
            """SELECT p.family_id,p.generator_version,p.seed,p.fingerprint,p.snapshot,
                      p.outcome,COALESCE(bool_or(NOT a.is_correct),false) AS has_error,
                      max(CASE WHEN s.mode ~ '^task[0-9]{1,2}$'
                           THEN substring(s.mode from 5)::int END) AS number
               FROM issued_problems p JOIN users u ON u.id=p.user_id
               LEFT JOIN attempts a ON a.problem_id=p.id
               LEFT JOIN sessions s ON s.id=p.session_id
               WHERE u.telegram_user_id=$1 AND p.id=$2
               GROUP BY p.id""",
            telegram_user_id, source_id,
        )
        if row is None or (require_error and not (row["has_error"] or row["outcome"] == "failed")):
            raise ValueError("Only confirmed incorrect answers can be repeated")
        snapshot = _object(row["snapshot"])
        snapshot = await asyncio.to_thread(
            _restore_and_validate,
            snapshot,
            str(row["family_id"]),
            str(row["generator_version"]),
            row["seed"],
            str(row["fingerprint"]),
            str(source_id),
        )
        number = int(row["number"] or _number_from_snapshot(snapshot))
        return ReplaySource(source_type, source_id, 0, number, snapshot)

    if source_type == "mixed":
        row = await pool.fetchrow(
            """SELECT p.number,p.family_id,p.fingerprint,p.snapshot,p.snapshot_sha256,p.outcome,
                      COALESCE(bool_or(NOT a.is_correct),false) AS has_error,
                      COALESCE(p.snapshot->'_original_scenario_snapshot',
                        (SELECT first.snapshot->'_original_scenario_snapshot'
                         FROM mixed_training_problems first
                         WHERE first.session_id=p.session_id AND first.number=1
                           AND first.snapshot->>'scenario_seed'=p.snapshot->>'scenario_seed'
                           AND first.snapshot->>'story_code'=p.snapshot->>'story_code'
                           AND first.snapshot ? '_original_scenario_snapshot'
                         ORDER BY first.issued_at,first.id LIMIT 1),
                        s.state->'scenario_snapshot') AS scenario_snapshot,
                      COALESCE(p.snapshot->>'_original_scenario_snapshot_sha256',
                        (SELECT first.snapshot->>'_original_scenario_snapshot_sha256'
                         FROM mixed_training_problems first
                         WHERE first.session_id=p.session_id AND first.number=1
                           AND first.snapshot->>'scenario_seed'=p.snapshot->>'scenario_seed'
                           AND first.snapshot->>'story_code'=p.snapshot->>'story_code'
                           AND first.snapshot ? '_original_scenario_snapshot'
                         ORDER BY first.issued_at,first.id LIMIT 1),
                        s.state->>'scenario_snapshot_sha256') AS scenario_sha256
               FROM mixed_training_problems p
               JOIN mixed_training_sessions s ON s.id=p.session_id
               JOIN users u ON u.id=s.user_id
               LEFT JOIN mixed_training_attempts a ON a.problem_id=p.id
               WHERE u.telegram_user_id=$1 AND p.id=$2
               GROUP BY p.id,s.id""",
            telegram_user_id, source_id,
        )
        if row is None or (require_error and not (row["has_error"] or row["outcome"] == "failed")):
            raise ValueError("Only confirmed incorrect answers can be repeated")
        snapshot = _object(row["snapshot"])
        if _digest(snapshot) != str(row["snapshot_sha256"]).strip():
            raise ValueError("The original mixed snapshot failed its integrity check")
        if snapshot.get("fingerprint") != row["fingerprint"]:
            raise ValueError("The original mixed fingerprint does not match its record")
        number = int(row["number"])
        scenario_snapshot = _object(row["scenario_snapshot"]) if number <= 5 else None
        if number <= 5:
            if scenario_snapshot is None:
                raise ValueError("The original mixed scenario is unavailable")
            await asyncio.to_thread(
                _check_scenario_snapshot, scenario_snapshot, row["scenario_sha256"]
            )
            question = await asyncio.to_thread(_scenario_question, scenario_snapshot, number)
            await asyncio.to_thread(_same_question, question, snapshot)
            question["problem_id"] = str(source_id)
            snapshot = question
        snapshot = await asyncio.to_thread(
            _restore_and_validate,
            snapshot,
            str(row["family_id"]),
            str(snapshot.get("generator_version", "")),
            snapshot.get("seed"),
            str(snapshot.get("fingerprint", "")),
            str(source_id),
        )
        return ReplaySource(source_type, source_id, 0, number, snapshot,
                            scenario_snapshot if number <= 5 else None)

    row = await pool.fetchrow(
        """SELECT session.scenario_id, progress.status, progress.position,
                  scenario.story_code, scenario.snapshot, scenario.snapshot_sha256,
                  EXISTS (SELECT 1 FROM oge15_attempts a WHERE a.session_id=session.id
                          AND a.position=progress.position AND NOT a.is_correct) AS has_error
           FROM oge15_sessions session
           JOIN oge15_question_progress progress ON progress.session_id=session.id
           JOIN oge15_scenarios scenario ON scenario.id=session.scenario_id
           JOIN users u ON u.id=session.user_id
           WHERE u.telegram_user_id=$1 AND session.id=$2 AND progress.position=$3
             AND progress.status <> 'pending'""",
        telegram_user_id, source_id, position,
    )
    if row is None or (require_error and not (row["has_error"] or row["status"] == "failed")):
        raise ValueError("Only confirmed incorrect answers can be repeated")
    scenario_snapshot = _object(row["snapshot"])
    await asyncio.to_thread(_check_scenario_snapshot, scenario_snapshot, row["snapshot_sha256"])
    question = await asyncio.to_thread(_scenario_question, scenario_snapshot, position)
    return ReplaySource("scenario", source_id, position, position, question, scenario_snapshot)


async def _load_memory_source(
    repository: Any,
    user_id: int,
    record_id: str,
    source_type: str,
    source_id: UUID,
    position: int,
    *,
    require_error: bool,
) -> ReplaySource:
    from app.persistence.training_insights import training_record_detail

    detail = await training_record_detail(repository, user_id, record_id)
    attempt_records = detail.get("attempt_records", []) if detail else []
    has_error = isinstance(attempt_records, list) and any(
        isinstance(attempt, dict) and attempt.get("is_correct") is False
        for attempt in attempt_records
    )
    if not detail or (
        require_error and not (
            detail.get("has_error") or has_error or detail.get("outcome") == "failed"
        )
    ):
        raise ValueError("Only confirmed incorrect answers can be repeated")
    snapshot = detail.get("snapshot")
    if not isinstance(snapshot, dict):
        if source_type == "mixed":
            for record in getattr(repository, "_mixed_training_records", {}).get(user_id, []):
                if record.get("record_id") == record_id and isinstance(
                    record.get("snapshot"), dict
                ):
                    snapshot = record["snapshot"]
                    break
        elif source_type == "ordinary":
            for number in range(6, 20):
                attr = "issued_history" if number == 6 else f"issued{number}"
                issued = getattr(repository, attr, {})
                candidate = issued.get(user_id, {}).get(str(source_id))
                if isinstance(candidate, dict):
                    snapshot = candidate
                    break
    if not isinstance(snapshot, dict):
        raise ValueError("The original snapshot is unavailable")
    number = int(detail.get("number", 0))
    scenario_snapshot: dict[str, object] | None = None
    if source_type == "mixed" and number <= 5:
        session = getattr(repository, "_mixed_training_sessions", {}).get(user_id)
        state = session.get("state", {}) if isinstance(session, dict) else {}
        candidate = snapshot.get("_original_scenario_snapshot")
        scenario_digest = snapshot.get("_original_scenario_snapshot_sha256")
        if not isinstance(candidate, dict):
            scenario_seed = snapshot.get("scenario_seed")
            story_code = snapshot.get("story_code")
            for record in reversed(
                getattr(repository, "_mixed_training_records", {}).get(user_id, [])
            ):
                saved = record.get("snapshot")
                if (
                    isinstance(saved, dict)
                    and record.get("number") == 1
                    and saved.get("scenario_seed") == scenario_seed
                    and saved.get("story_code") == story_code
                    and isinstance(saved.get("_original_scenario_snapshot"), dict)
                ):
                    candidate = saved["_original_scenario_snapshot"]
                    scenario_digest = saved.get("_original_scenario_snapshot_sha256")
                    break
        if not isinstance(candidate, dict) and isinstance(state, dict):
            candidate = state.get("scenario_snapshot")
            scenario_digest = state.get("scenario_snapshot_sha256")
        if not isinstance(candidate, dict):
            raise ValueError("The original mixed scenario is unavailable")
        scenario_snapshot = candidate
        await asyncio.to_thread(_check_scenario_snapshot, candidate, scenario_digest)
        question = await asyncio.to_thread(_scenario_question, candidate, number)
        await asyncio.to_thread(_same_question, question, snapshot)
        snapshot = {**question, "problem_id": str(source_id)}
    if source_type == "scenario":
        raise ValueError("MemoryRepository does not store OGE 1–5 source sessions")
    snapshot = cast(dict[str, object], snapshot)
    snapshot = cast(
        dict[str, object],
        await asyncio.to_thread(
            _restore_and_validate,
            snapshot,
            str(detail.get("family_id", "")),
            str(snapshot.get("generator_version", "")),
            snapshot.get("seed"),
            str(snapshot.get("fingerprint", "")),
            str(source_id),
        ),
    )
    return ReplaySource(source_type, source_id, position, number, snapshot, scenario_snapshot)


def _number_from_snapshot(snapshot: dict[str, object]) -> int:
    for key in ("number", "exam_number", "mixed_number"):
        value = snapshot.get(key)
        if isinstance(value, int) and 1 <= value <= 19:
            return value
    family = str(snapshot.get("family_id", ""))
    if family.startswith("OGE"):
        digits = "".join(char for char in family[3:].split("-")[0] if char.isdigit())
        if digits.isdigit():
            return int(digits)
    raise ValueError("Cannot determine the original task number")


def _restore_and_validate(
    snapshot: dict[str, object], family_id: str, version: str, seed: object,
    fingerprint: str, problem_id: str,
) -> dict[str, object]:
    if not snapshot or snapshot.get("family_id") != family_id:
        raise ValueError("Original task identity does not match its snapshot")
    if snapshot.get("generator_version") != version:
        raise ValueError("Original task generator version does not match its snapshot")
    if snapshot.get("fingerprint") != fingerprint or not fingerprint:
        raise ValueError("Original task fingerprint cannot be verified")
    if snapshot.get("problem_id") not in {None, problem_id}:
        raise ValueError("Original task ID does not match its snapshot")
    if not family_id.startswith("OGE15:") and snapshot.get("problem_id") != problem_id:
        raise ValueError("Original task identity is incomplete")
    if not isinstance(snapshot.get("condition"), str) or not snapshot.get("condition"):
        raise ValueError("Original task condition is unavailable")
    if not (snapshot.get("correct_answer") or snapshot.get("canonical_answer")):
        raise ValueError("Original answer is unavailable")
    from app.persistence.image_retention import image_payload_keys, is_graphic_snapshot

    if is_graphic_snapshot(snapshot) and not image_payload_keys(snapshot):
        from app.persistence.image_retention import restore_graphic_snapshot

        restored = restore_graphic_snapshot(snapshot)
        if restored is None:
            raise ValueError("The original graphic cannot be restored exactly")
        snapshot = restored
    _validate_known_snapshot(snapshot, family_id, problem_id)
    if seed is not None and snapshot.get("seed") != seed:
        raise ValueError("Original seed does not match its snapshot")
    return snapshot


def _validate_known_snapshot(snapshot: dict[str, object], family_id: str, problem_id: str) -> None:
    if family_id.startswith("OGE07-"):
        from app.math.oge07_validation import validate_task7_snapshot

        if not validate_task7_snapshot(snapshot):
            raise ValueError("The original №7 task failed validation")
        _assert_regenerated(snapshot, problem_id)
    elif family_id.startswith("OGE06-"):
        _assert_regenerated(snapshot, problem_id)
    elif family_id.startswith("OGE08-"):
        _assert_regenerated(snapshot, problem_id)
    elif family_id.startswith("OGE09-"):
        _assert_regenerated(snapshot, problem_id)
    elif family_id.startswith("OGE10-"):
        _assert_regenerated(snapshot, problem_id)
    elif family_id.startswith("OGE11-"):
        from app.math.oge11 import from_snapshot as restore_oge11

        restore_oge11(snapshot)
        _assert_regenerated(snapshot, problem_id)
    elif family_id.startswith("OGE12-"):
        _assert_regenerated(snapshot, problem_id)
    elif family_id.startswith("OGE13-"):
        from app.math.inequalities import validate_snapshot as validate_inequality

        if not validate_inequality(snapshot):
            raise ValueError("The original №13 task failed validation")
        _assert_regenerated(snapshot, problem_id)
    elif family_id.startswith("OGE14-"):
        _assert_regenerated(snapshot, problem_id)
    elif family_id.startswith("OGE15-"):
        from app.math.oge15_triangles import from_snapshot as restore_oge15

        restore_oge15(snapshot)
    elif family_id.startswith("OGE16-"):
        from app.math.oge16_circles import from_snapshot as restore_oge16

        restore_oge16(snapshot)
    elif family_id.startswith("OGE17-"):
        from app.math.oge17_generator import from_snapshot as restore_oge17

        restore_oge17(snapshot, expected_problem_id=problem_id)
    elif family_id.startswith("OGE18-"):
        from app.math.oge18 import from_snapshot as restore_oge18

        restore_oge18(snapshot)
    elif family_id.startswith("OGE19-"):
        from app.math.oge19 import validate_snapshot as validate_task19

        validate_task19(snapshot)
        if snapshot.get("correct_answer") != snapshot.get("answer_mask"):
            raise ValueError("The original №19 answer differs from the verified answer mask")


def _assert_regenerated(snapshot: dict[str, object], problem_id: str) -> None:
    """Compare every deterministic source field to its versioned generator."""
    family_id = str(snapshot.get("family_id", ""))
    version = str(snapshot.get("generator_version", ""))
    seed = snapshot.get("seed")
    if type(seed) is not int or snapshot.get("problem_id") != problem_id:
        raise ValueError("The original task lacks a trusted seed/problem identity")
    if family_id.startswith("OGE06-"):
        from app.math.generator import generate as generate_task6

        expected = generate_task6(family_id, seed, version).to_snapshot()
    elif family_id.startswith("OGE07-N"):
        from app.math.oge07_graph import generate_graph_problem

        expected = generate_graph_problem(family_id, seed, version).to_snapshot()
    elif family_id.startswith("OGE07-"):
        from app.math.numbers import generate as generate_task7

        expected = generate_task7(family_id, seed, version).to_snapshot()
    elif family_id.startswith("OGE08-"):
        from app.math.oge8 import generate as generate_task8

        expected = generate_task8(family_id, seed, version).to_snapshot()
    elif family_id.startswith("OGE09-"):
        from app.math.equations import generate_equation

        expected = generate_equation(family_id, seed, version).to_snapshot()
    elif family_id.startswith("OGE10-"):
        from app.math.probability import generate as generate_task10

        expected = generate_task10(family_id, seed, version).to_snapshot()
    elif family_id.startswith("OGE11-"):
        from app.math.oge11 import generate as generate_task11

        expected = generate_task11(family_id, seed, version).to_snapshot()
    elif family_id.startswith("OGE12-"):
        from app.math.formulas import generate as generate_task12

        expected = generate_task12(family_id, seed, version).to_snapshot()
    elif family_id.startswith("OGE13-"):
        from app.math.inequalities import generate as generate_task13

        expected = generate_task13(family_id, seed, version).to_snapshot()
    elif family_id.startswith("OGE14-"):
        from app.math.progressions import generate as generate_task14

        expected = generate_task14(family_id, seed, version).to_snapshot()
    else:
        raise ValueError("No deterministic restorer exists for this original family")
    # PostgreSQL JSONB normalizes tuple-like generator fields to arrays. Compare
    # the same persisted representation in both repositories.
    saved_json = json.loads(json.dumps(snapshot, ensure_ascii=False))
    expected_json = json.loads(json.dumps(expected, ensure_ascii=False))
    if any(
        key != "problem_id" and saved_json.get(key) != value
        for key, value in expected_json.items()
    ):
        raise ValueError("The original task does not match its seed and generator version")


def _check_scenario_snapshot(snapshot: dict[str, object], digest: object) -> None:
    from app.math.scenario_engine import ScenarioSnapshot, snapshot_digest

    restored = ScenarioSnapshot.from_snapshot(snapshot)
    if not isinstance(digest, str) or snapshot_digest(restored) != digest.strip():
        raise ValueError("The original OGE 1–5 shared snapshot failed its integrity check")


def _scenario_question(snapshot: dict[str, object], position: int) -> dict[str, object]:
    from app.math.scenario_engine import ScenarioSnapshot

    restored = ScenarioSnapshot.from_snapshot(snapshot)
    question = restored.questions[position - 1]
    return {
        **question.to_snapshot(),
        "family_id": question.family_id,
        "condition": question.condition,
        "correct_answer": question.canonical_answer,
        "solution": list(question.solution_steps),
        "hints": list(question.hints),
        "story_code": restored.story_code,
        "shared_context": restored.shared_context,
        "fingerprint": f"{restored.story_code}:{restored.seed}:{position}",
        "generator_version": question.generator_version,
        "scenario_seed": restored.seed,
    }


def _same_question(expected: dict[str, object], saved: dict[str, object]) -> None:
    expected_json = json.loads(json.dumps(expected, ensure_ascii=False))
    saved_json = json.loads(json.dumps(saved, ensure_ascii=False))
    if any(saved_json.get(key) != value for key, value in expected_json.items()):
        raise ValueError("Mixed OGE 1–5 question differs from the saved shared scenario")


class ErrorReplayRepository:
    """Atomic one-use references; replay attempts are excluded from training metrics."""

    def __init__(self, repository: Any) -> None:
        self._repository = repository
        self._pool = getattr(repository, "_pool", None)
        if self._pool is None and not hasattr(repository, "_training_error_replays"):
            repository._training_error_replays = {}

    async def status_for_source(
        self, user_id: int, source_type: str, source_id: UUID, source_position: int
    ) -> dict[str, object] | None:
        if self._pool is None:
            row = self._repository._training_error_replays.get(
                (user_id, source_type, str(source_id), source_position)
            )
            return dict(row) if row else None
        row = await self._pool.fetchrow(
            """SELECT r.* FROM training_error_replays r JOIN users u ON u.id=r.user_id
               WHERE u.telegram_user_id=$1 AND r.source_type=$2 AND r.source_id=$3
                 AND r.source_position=$4""",
            user_id, source_type, source_id, source_position,
        )
        return _replay_row(row) if row else None

    async def start(
        self, user_id: int, source: ReplaySource
    ) -> dict[str, object]:
        if self._pool is None:
            key = (user_id, source.source_type, str(source.source_id), source.source_position)
            active = next(
                (
                    row
                    for (owner, *_), row in self._repository._training_error_replays.items()
                    if owner == user_id and row["status"] == "active"
                ),
                None,
            )
            if active is not None and active.get("id") != str(
                self._repository._training_error_replays.get(key, {}).get("id")
            ):
                raise ReplayAlreadyActive("Another original-task replay is active")
            row = self._repository._training_error_replays.get(key)
            if row is None:
                row = {
                    "id": str(uuid4()), "source_type": source.source_type,
                    "source_id": str(source.source_id), "source_position": source.source_position,
                    "status": "active", "attempt_count": 0, "attempts": [], "hints_used": 0,
                    "solution_viewed": False, "prompt_message_id": None,
                }
                self._repository._training_error_replays[key] = row
            await self._repository.save_user_state(user_id, "error_replay")
            return dict(row)
        async with self._pool.acquire() as connection, connection.transaction():
            user_uuid = await connection.fetchval(
                "SELECT id FROM users WHERE telegram_user_id=$1 FOR UPDATE", user_id
            )
            if user_uuid is None:
                raise ValueError("Original task owner does not exist")
            active = await connection.fetchrow(
                """SELECT id,source_type,source_id,source_position
                   FROM training_error_replays WHERE user_id=$1 AND status='active' FOR UPDATE""",
                user_uuid,
            )
            if active is not None and (
                active["source_type"] != source.source_type
                or active["source_id"] != source.source_id
                or int(active["source_position"]) != source.source_position
            ):
                raise ReplayAlreadyActive("Another original-task replay is active")
            row = await connection.fetchrow(
                """INSERT INTO training_error_replays
                   (user_id,source_type,source_id,source_position)
                   VALUES ($1,$2,$3,$4)
                   ON CONFLICT (user_id,source_type,source_id,source_position) DO NOTHING
                   RETURNING *""",
                user_uuid, source.source_type, source.source_id, source.source_position,
            )
            if row is None:
                row = await connection.fetchrow(
                    """SELECT * FROM training_error_replays WHERE user_id=$1
                       AND source_type=$2 AND source_id=$3 AND source_position=$4 FOR UPDATE""",
                    user_uuid, source.source_type, source.source_id, source.source_position,
                )
            await connection.execute(
                """UPDATE users SET current_state=jsonb_set(
                       current_state - 'navigation_message_id' - 'navigation_revision',
                       '{screen}', '"error_replay"'::jsonb)
                   WHERE id=$1""",
                user_uuid,
            )
            return _replay_row(row)

    async def set_prompt(self, user_id: int, replay_id: UUID, message_id: int) -> None:
        if self._pool is None:
            for (owner, *_), row in self._repository._training_error_replays.items():
                if owner == user_id and row["id"] == str(replay_id):
                    previous = row.get("prompt_message_id") or 0
                    if row["status"] == "active" and message_id > previous:
                        row["prompt_message_id"] = message_id
                    return
            return
        await self._pool.execute(
            """UPDATE training_error_replays r SET prompt_message_id=$3,updated_at=now()
               FROM users u WHERE r.user_id=u.id AND u.telegram_user_id=$1 AND r.id=$2
                 AND r.status='active' AND (r.prompt_message_id IS NULL
                     OR r.prompt_message_id < $3)""",
            user_id, replay_id, message_id,
        )

    async def record_attempt(
        self, user_id: int, replay_id: UUID, raw_answer: str, correct: bool,
        message_id: int, reply_to: int | None,
    ) -> dict[str, object] | None:
        if self._pool is None:
            row = self._memory_row(user_id, replay_id)
            if row is None:
                return None
            attempts = row["attempts"]
            assert isinstance(attempts, list)
            if any(item.get("message_id") == message_id for item in attempts):
                return {**row, "event": "duplicate"}
            if row["status"] != "active":
                return {**row, "event": "closed"}
            if (
                await self._repository.user_state(user_id) != "error_replay"
                or not _matches_prompt(row, message_id, reply_to)
            ):
                return {**row, "event": "stale"}
            number = int(cast(int, row["attempt_count"])) + 1
            attempts.append({"attempt_no": number, "message_id": message_id,
                             "raw_answer": raw_answer[:200], "is_correct": correct,
                             "used_hint": int(cast(int, row["hints_used"])) > 0,
                             "created_at": datetime.now(UTC).isoformat()})
            row["attempt_count"] = number
            if correct:
                row["status"] = "solved"
            elif number >= 2:
                row["status"] = "failed"
            if row["status"] != "active":
                await self._repository.save_user_state(user_id, "progress")
            return {**row, "event": "accepted"}
        async with self._pool.acquire() as connection, connection.transaction():
            owner = await connection.fetchrow(
                "SELECT id,current_state->>'screen' AS screen FROM users "
                "WHERE telegram_user_id=$1 FOR UPDATE", user_id,
            )
            if owner is None:
                return None
            row = await connection.fetchrow(
                "SELECT * FROM training_error_replays WHERE user_id=$1 AND id=$2 FOR UPDATE",
                owner["id"], replay_id,
            )
            if row is None:
                return None
            result = _replay_row(row)
            attempts = cast_attempts(result.get("attempts"))
            if any(item.get("message_id") == message_id for item in attempts):
                return {**result, "event": "duplicate"}
            if result["status"] != "active":
                return {**result, "event": "closed"}
            if owner["screen"] != "error_replay" or not _matches_prompt(
                result, message_id, reply_to
            ):
                return {**result, "event": "stale"}
            attempt_no = int(cast(int, result["attempt_count"])) + 1
            attempts.append({"attempt_no": attempt_no, "message_id": message_id,
                             "raw_answer": raw_answer[:200], "is_correct": correct,
                             "used_hint": int(cast(int, result["hints_used"])) > 0,
                             "created_at": datetime.now(UTC).isoformat()})
            status = "solved" if correct else ("failed" if attempt_no >= 2 else "active")
            await connection.execute(
                """UPDATE training_error_replays SET attempts=$2::jsonb,attempt_count=$3,
                   status=$4,updated_at=now(),finished_at=CASE WHEN $4='active' THEN NULL
                   ELSE now() END WHERE id=$1""",
                replay_id, json.dumps(attempts), attempt_no, status,
            )
            if status != "active":
                await connection.execute(
                    """UPDATE users SET current_state=jsonb_set(
                           current_state - 'navigation_message_id' - 'navigation_revision',
                           '{screen}', '"progress"'::jsonb) WHERE id=$1""", owner["id"],
                )
            return {**result, "attempts": attempts, "attempt_count": attempt_no,
                    "status": status, "event": "accepted"}

    async def action(self, user_id: int, replay_id: UUID, action: str, snapshot: dict[str, object]
                     ) -> str | None:
        if action == "hint":
            hints = snapshot.get("hints", [])
            if self._pool is None:
                row = self._memory_row(user_id, replay_id)
                if row is None or row["status"] != "active":
                    return None
                used = int(cast(int, row["hints_used"]))
                if not isinstance(hints, list) or used >= len(hints):
                    return None
                row["hints_used"] = used + 1
                return str(hints[used])
            async with self._pool.acquire() as connection, connection.transaction():
                row = await connection.fetchrow(
                    """SELECT r.* FROM training_error_replays r JOIN users u ON u.id=r.user_id
                       WHERE u.telegram_user_id=$1 AND r.id=$2 FOR UPDATE OF r""",
                    user_id, replay_id,
                )
                if row is None or row["status"] != "active":
                    return None
                used = int(row["hints_used"])
                if not isinstance(hints, list) or used >= len(hints):
                    return None
                await connection.execute(
                    """UPDATE training_error_replays SET hints_used=hints_used+1,
                       updated_at=now() WHERE id=$1""", replay_id,
                )
                return str(hints[used])
        if action != "solution":
            return None
        solution = snapshot.get("solution_steps", snapshot.get("solution", []))
        steps = [str(item) for item in solution] if isinstance(solution, list) else []
        if self._pool is None:
            row = self._memory_row(user_id, replay_id)
            if row is None or row["status"] != "active":
                return None
            row["status"] = "solution_viewed"
            row["solution_viewed"] = True
            return "\n".join(steps)
        async with self._pool.acquire() as connection, connection.transaction():
            result = await connection.execute(
                """UPDATE training_error_replays r SET status='solution_viewed',
                   solution_viewed_at=now(),finished_at=now(),updated_at=now()
                   FROM users u WHERE r.user_id=u.id AND u.telegram_user_id=$1
                     AND r.id=$2 AND r.status='active'""",
                user_id, replay_id,
            )
            if not result.endswith(" 1"):
                return None
        return "\n".join(steps)

    async def set_screen(self, user_id: int, screen: str) -> None:
        await self._repository.save_user_state(user_id, screen)

    def _memory_row(self, user_id: int, replay_id: UUID) -> dict[str, object] | None:
        for (owner, *_), row in getattr(self._repository, "_training_error_replays", {}).items():
            if owner == user_id and row["id"] == str(replay_id):
                return cast(dict[str, object], row)
        return None


def _matches_prompt(row: dict[str, object], message_id: int, reply_to: int | None) -> bool:
    prompt = row.get("prompt_message_id")
    return isinstance(prompt, int) and message_id > prompt and reply_to in {None, prompt}


def _replay_row(row: Any) -> dict[str, object]:
    result = dict(row)
    result["id"] = str(result["id"])
    result["source_id"] = str(result["source_id"])
    attempts = result.get("attempts", [])
    result["attempts"] = cast_attempts(attempts)
    return cast(dict[str, object], result)


def cast_attempts(value: object) -> list[dict[str, Any]]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return []
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]
