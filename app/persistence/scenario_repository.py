"""PostgreSQL persistence for one-snapshot OGE 1–5 practice sessions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

import asyncpg

from app.math.scenario_engine import (
    PracticeMode,
    ScenarioIntegrityError,
    ScenarioSnapshot,
    snapshot_digest,
)
from app.math.scenarios.recent_questions import question_signature


class AttemptResult(StrEnum):
    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"
    STALE = "stale"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class ScenarioSession:
    session_id: UUID
    scenario_id: UUID
    mode: PracticeMode
    status: str
    current_position: int
    navigation_revision: int
    question_status: str
    attempt_count: int
    hints_used: int
    prompt_message_id: int | None
    control_message_id: int | None
    snapshot: ScenarioSnapshot


class ScenarioPostgresRepository:
    """Stores the shared context once and progress/outcomes by question position."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def start_session(
        self,
        telegram_user_id: int,
        snapshot: ScenarioSnapshot,
        mode: PracticeMode,
        positions: tuple[int, ...],
    ) -> ScenarioSession:
        if telegram_user_id <= 0:
            raise ValueError("Telegram user id must be positive")
        if mode is PracticeMode.FULL and positions != (1, 2, 3, 4, 5):
            raise ValueError("Full mode must select the complete ordered question set")
        if mode is PracticeMode.SINGLE and (
            len(positions) != 1 or positions[0] not in range(1, 6)
        ):
            raise ValueError("Single mode must select exactly one question position")
        if tuple(question.position for question in snapshot.questions) != (1, 2, 3, 4, 5):
            raise ValueError("Scenario snapshot must preserve all five related questions")
        encoded = json.dumps(
            snapshot.to_snapshot(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        digest = snapshot_digest(snapshot)
        async with self._pool.acquire() as connection, connection.transaction():
            user_id = await connection.fetchval(
                """INSERT INTO users (telegram_user_id) VALUES ($1)
                   ON CONFLICT (telegram_user_id) DO UPDATE
                   SET telegram_user_id=EXCLUDED.telegram_user_id RETURNING id""",
                telegram_user_id,
            )
            scenario_id = await connection.fetchval(
                """INSERT INTO oge15_scenarios
                   (user_id, story_code, seed, generator_version, snapshot_schema_version,
                    snapshot, snapshot_sha256)
                   VALUES ($1, $2, $3, $4, 1, $5::jsonb, $6) RETURNING id""",
                user_id,
                snapshot.story_code,
                snapshot.seed,
                snapshot.generator_version,
                encoded,
                digest,
            )
            for asset in snapshot.assets:
                await connection.execute(
                    """INSERT INTO oge15_assets (sha256, storage_key, content_type)
                       VALUES ($1, $2, $3) ON CONFLICT (sha256) DO NOTHING""",
                    asset.sha256,
                    asset.storage_key,
                    asset.content_type,
                )
                stored_asset = await connection.fetchrow(
                    "SELECT storage_key, content_type FROM oge15_assets WHERE sha256=$1",
                    asset.sha256,
                )
                if (
                    stored_asset is None
                    or stored_asset["storage_key"] != asset.storage_key
                    or stored_asset["content_type"] != asset.content_type
                ):
                    raise ValueError("Asset digest is already bound to different stored content")
                await connection.execute(
                    """INSERT INTO oge15_scenario_assets (scenario_id, asset_sha256)
                       VALUES ($1, $2)""",
                    scenario_id,
                    asset.sha256,
                )
            session_id = await connection.fetchval(
                """INSERT INTO oge15_sessions
                   (user_id, scenario_id, mode, current_position)
                   VALUES ($1, $2, $3, $4) RETURNING id""",
                user_id,
                scenario_id,
                mode.value,
                positions[0],
            )
            for position in positions:
                await connection.execute(
                    """INSERT INTO oge15_question_progress (session_id, position, status)
                       VALUES ($1, $2, $3)""",
                    session_id,
                    position,
                    "active" if position == positions[0] else "pending",
                )
            return ScenarioSession(
                session_id=session_id,
                scenario_id=scenario_id,
                mode=mode,
                status="active",
                current_position=positions[0],
                navigation_revision=0,
                question_status="active",
                attempt_count=0,
                hints_used=0,
                prompt_message_id=None,
                control_message_id=None,
                snapshot=snapshot,
            )

    async def recent_questions(self, telegram_user_id: int) -> frozenset[tuple[str, str, str]]:
        """Read up to four recent sessions via the user/start-time index."""
        rows = await self._pool.fetch(
            """WITH recent AS (
                   SELECT session.id, session.scenario_id
                   FROM users AS app_user
                   JOIN oge15_sessions AS session ON session.user_id=app_user.id
                   WHERE app_user.telegram_user_id=$1
                   ORDER BY session.started_at DESC, session.id DESC LIMIT 4
               )
               SELECT scenario.snapshot,
                      ARRAY(SELECT progress.position FROM oge15_question_progress AS progress
                            WHERE progress.session_id=recent.id AND progress.status <> 'pending')
                      AS positions
               FROM recent
               JOIN oge15_scenarios AS scenario ON scenario.id=recent.scenario_id""",
            telegram_user_id,
        )
        signatures: set[tuple[str, str, str]] = set()
        for row in rows:
            raw = row["snapshot"]
            data = json.loads(raw) if isinstance(raw, str) else raw
            snapshot = ScenarioSnapshot.from_snapshot(data)
            signatures.update(
                question_signature(snapshot, snapshot.questions[position - 1])
                for position in row["positions"]
            )
        return frozenset(signatures)

    async def resume_session(self, telegram_user_id: int) -> ScenarioSession | None:
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                """SELECT session.id AS session_id, session.scenario_id, session.mode,
                          session.status, session.current_position, session.navigation_revision,
                          session.control_message_id, progress.status AS question_status,
                          progress.attempt_count, progress.hints_used,
                          progress.prompt_message_id, scenario.snapshot,
                          scenario.snapshot_sha256
                   FROM oge15_sessions AS session
                   JOIN users AS app_user ON app_user.id = session.user_id
                   JOIN oge15_scenarios AS scenario ON scenario.id = session.scenario_id
                   JOIN oge15_question_progress AS progress
                     ON progress.session_id=session.id
                    AND progress.position=session.current_position
                   WHERE app_user.telegram_user_id=$1 AND session.status <> 'completed'
                   ORDER BY session.started_at DESC LIMIT 1""",
                telegram_user_id,
            )
        if row is None:
            return None
        raw_snapshot = row["snapshot"]
        if isinstance(raw_snapshot, str):
            raw_snapshot = json.loads(raw_snapshot)
        snapshot = ScenarioSnapshot.from_snapshot(raw_snapshot)
        if snapshot_digest(snapshot) != row["snapshot_sha256"].strip():
            raise ScenarioIntegrityError("Stored scenario snapshot failed its SHA-256 check")
        return ScenarioSession(
            session_id=row["session_id"],
            scenario_id=row["scenario_id"],
            mode=PracticeMode(row["mode"]),
            status=row["status"],
            current_position=row["current_position"],
            navigation_revision=row["navigation_revision"],
            question_status=row["question_status"],
            attempt_count=row["attempt_count"],
            hints_used=row["hints_used"],
            prompt_message_id=row["prompt_message_id"],
            control_message_id=row["control_message_id"],
            snapshot=snapshot,
        )

    async def close_legacy_with_exposed_answer(
        self, telegram_user_id: int, session: ScenarioSession
    ) -> bool:
        """Invalidate only sessions containing an unfinished question with a known leak."""
        snapshot = session.snapshot
        family = None
        if snapshot.context.get("renderer_version") == "stove-svg-png-v1":
            family = "STOVE-F12-ARCH-RADIUS"
        elif snapshot.generator_version in {"garden-sosnovka-1.0", "garden-sosnovka-1.1"}:
            family = "GARDEN-01-IDENTIFY"
        elif snapshot.generator_version == "paper-v1":
            family = "PAPER-F01"
        if family is None:
            return False
        positions = [q.position for q in snapshot.questions if q.family_id == family]
        if not positions:
            return False
        async with self._pool.acquire() as connection, connection.transaction():
            owned = await connection.fetchval(
                """SELECT session.id FROM oge15_sessions AS session
                   JOIN users AS app_user ON app_user.id=session.user_id
                   WHERE app_user.telegram_user_id=$1 AND session.id=$2
                     AND session.status <> 'completed'
                   FOR UPDATE OF session""",
                telegram_user_id, session.session_id,
            )
            if owned is None:
                return False
            closed = await connection.fetchval(
                """UPDATE oge15_sessions SET status='completed', finished_at=now(),
                          navigation_revision=navigation_revision+1, control_message_id=NULL
                   WHERE id=$1 AND EXISTS (
                       SELECT 1 FROM oge15_question_progress
                       WHERE session_id=$1 AND position=ANY($2::smallint[])
                         AND status IN ('pending', 'active')
                   ) RETURNING id""",
                session.session_id, positions,
            )
        return closed is not None

    async def resume_paused(
        self, telegram_user_id: int, session_id: UUID
    ) -> ScenarioSession | None:
        """Atomically reopen one owned paused session and return its same snapshot."""
        async with self._pool.acquire() as connection, connection.transaction():
            resumed = await connection.fetchval(
                """UPDATE oge15_sessions AS session SET status='active',
                          navigation_revision=navigation_revision+1
                   FROM users AS app_user
                   WHERE session.user_id=app_user.id AND app_user.telegram_user_id=$1
                     AND session.id=$2 AND session.status='paused'
                   RETURNING session.id""",
                telegram_user_id,
                session_id,
            )
            if resumed is None:
                return None
        return await self.resume_session(telegram_user_id)

    async def set_condition_message(
        self, telegram_user_id: int, session_id: UUID, position: int, message_id: int
    ) -> bool:
        """Bind replies to the currently issued question, separately from controls."""
        if position not in range(1, 6) or message_id <= 0:
            return False
        async with self._pool.acquire() as connection:
            updated = await connection.fetchval(
                """UPDATE oge15_question_progress AS progress
                   SET prompt_message_id=$3, updated_at=now()
                   FROM oge15_sessions AS session
                   JOIN users AS app_user ON app_user.id=session.user_id
                   WHERE progress.session_id=$1 AND progress.position=$2
                     AND session.id=progress.session_id AND session.status='active'
                     AND app_user.telegram_user_id=$4
                     AND session.current_position=progress.position AND progress.status='active'
                   RETURNING progress.position""",
                session_id,
                position,
                message_id,
                telegram_user_id,
            )
        return updated is not None

    async def set_control_message(
        self, telegram_user_id: int, session_id: UUID, expected_revision: int, message_id: int
    ) -> bool:
        """Store the actual Telegram keyboard message without changing its revision."""
        if message_id <= 0:
            return False
        async with self._pool.acquire() as connection:
            updated = await connection.fetchval(
                """UPDATE oge15_sessions AS session SET control_message_id=$3
                   FROM users AS app_user
                   WHERE session.id=$1 AND session.user_id=app_user.id
                     AND app_user.telegram_user_id=$4 AND session.navigation_revision=$2
                     AND session.status='active' RETURNING session.id""",
                session_id,
                expected_revision,
                message_id,
                telegram_user_id,
            )
        return updated is not None

    async def record_attempt(
        self,
        *,
        telegram_user_id: int,
        session_id: UUID,
        position: int,
        telegram_message_id: int,
        raw_answer: str,
        normalized_answer: str | None,
        is_correct: bool,
        reply_to_message_id: int | None = None,
    ) -> AttemptResult:
        async with self._pool.acquire() as connection, connection.transaction():
            session = await connection.fetchrow(
                """SELECT session.current_position, session.status FROM oge15_sessions AS session
                   JOIN users AS app_user ON app_user.id=session.user_id
                   WHERE session.id=$1 AND app_user.telegram_user_id=$2 FOR UPDATE OF session""",
                session_id,
                telegram_user_id,
            )
            if (
                session is None
                or session["status"] != "active"
                or session["current_position"] != position
            ):
                return AttemptResult.STALE
            progress = await connection.fetchrow(
                """SELECT status, attempt_count, hints_used, prompt_message_id
                   FROM oge15_question_progress WHERE session_id=$1 AND position=$2 FOR UPDATE""",
                session_id,
                position,
            )
            if progress is None or progress["status"] != "active":
                return AttemptResult.CLOSED
            if (
                reply_to_message_id is not None
                and reply_to_message_id != progress["prompt_message_id"]
            ):
                return AttemptResult.STALE
            if (
                progress["prompt_message_id"] is not None
                and telegram_message_id <= progress["prompt_message_id"]
            ):
                return AttemptResult.STALE
            duplicate = await connection.fetchval(
                """SELECT EXISTS (SELECT 1 FROM oge15_attempts
                   WHERE session_id=$1 AND telegram_message_id=$2)""",
                session_id,
                telegram_message_id,
            )
            if duplicate:
                return AttemptResult.DUPLICATE
            attempt_no = progress["attempt_count"] + 1
            if attempt_no > 2:
                return AttemptResult.CLOSED
            await connection.execute(
                """INSERT INTO oge15_attempts
                   (session_id, position, attempt_no, telegram_message_id, raw_answer,
                    normalized_answer, is_correct, used_hint)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
                session_id,
                position,
                attempt_no,
                telegram_message_id,
                raw_answer,
                normalized_answer,
                is_correct,
                progress["hints_used"] > 0,
            )
            status = "solved" if is_correct else "failed" if attempt_no == 2 else "active"
            await connection.execute(
                """UPDATE oge15_question_progress
                   SET attempt_count=$3, status=$4, updated_at=now()
                   WHERE session_id=$1 AND position=$2""",
                session_id,
                position,
                attempt_no,
                status,
            )
            return AttemptResult.ACCEPTED

    async def apply_callback(
        self,
        *,
        telegram_user_id: int,
        callback_query_id: str,
        session_id: UUID,
        control_message_id: int,
        expected_revision: int,
        expected_position: int,
        action: str,
        hint_count: int = 0,
    ) -> bool:
        """Atomically claim one callback and apply one contract-valid transition."""
        if (
            not callback_query_id
            or control_message_id <= 0
            or action not in {"hint", "solution", "skip", "next", "pause", "resume", "data"}
        ):
            return False
        async with self._pool.acquire() as connection, connection.transaction():
            session = await connection.fetchrow(
                """SELECT session.mode, session.status, session.current_position,
                          session.navigation_revision, session.control_message_id
                   FROM oge15_sessions AS session
                   JOIN users AS app_user ON app_user.id=session.user_id
                   WHERE session.id=$1 AND app_user.telegram_user_id=$2 FOR UPDATE OF session""",
                session_id,
                telegram_user_id,
            )
            if session is None:
                return False
            claim = await connection.fetchval(
                """INSERT INTO oge15_callback_claims
                   (telegram_callback_query_id, session_id, action)
                   VALUES ($1, $2, $3) ON CONFLICT DO NOTHING RETURNING 1""",
                callback_query_id,
                session_id,
                action,
            )
            if claim is None:
                return False
            if (
                session["navigation_revision"] != expected_revision
                or session["current_position"] != expected_position
                or session["control_message_id"] != control_message_id
            ):
                return False
            if action == "data":
                return bool(session["status"] == "active")
            progress = await connection.fetchrow(
                """SELECT status, hints_used FROM oge15_question_progress
                   WHERE session_id=$1 AND position=$2 FOR UPDATE""",
                session_id,
                expected_position,
            )
            if progress is None:
                return False
            next_position = expected_position + 1
            finish = False
            if (
                action == "hint"
                and session["status"] == "active"
                and progress["status"] == "active"
            ):
                if progress["hints_used"] >= hint_count:
                    return False
                await connection.execute(
                    """UPDATE oge15_question_progress SET hints_used=hints_used+1, updated_at=now()
                       WHERE session_id=$1 AND position=$2""",
                    session_id,
                    expected_position,
                )
            elif (
                action == "solution"
                and session["status"] == "active"
                and progress["status"] == "active"
            ):
                await connection.execute(
                    """UPDATE oge15_question_progress SET status='solution_viewed',
                       solution_viewed_at=COALESCE(solution_viewed_at, now()), updated_at=now()
                       WHERE session_id=$1 AND position=$2""",
                    session_id,
                    expected_position,
                )
            elif (
                action == "skip"
                and session["status"] == "active"
                and progress["status"] == "active"
            ):
                await connection.execute(
                    """UPDATE oge15_question_progress SET status='skipped', updated_at=now()
                       WHERE session_id=$1 AND position=$2""",
                    session_id,
                    expected_position,
                )
                finish = session["mode"] == "single" or expected_position == 5
            elif action == "next" and session["status"] == "active" and progress["status"] in {
                "solved", "failed", "solution_viewed"
            }:
                finish = session["mode"] == "single" or expected_position == 5
            elif action == "pause" and session["status"] in {"active", "paused"}:
                await connection.execute(
                    "UPDATE oge15_sessions SET status='paused' WHERE id=$1", session_id
                )
            elif action == "resume" and session["status"] == "paused":
                await connection.execute(
                    "UPDATE oge15_sessions SET status='active' WHERE id=$1", session_id
                )
            else:
                return False

            if action in {"skip", "next"} and not finish:
                await connection.execute(
                    """UPDATE oge15_question_progress SET status='active', updated_at=now()
                       WHERE session_id=$1 AND position=$2 AND status='pending'""",
                    session_id,
                    next_position,
                )
                await connection.execute(
                    "UPDATE oge15_sessions SET current_position=$2 WHERE id=$1",
                    session_id,
                    next_position,
                )
            if finish:
                await connection.execute(
                    "UPDATE oge15_sessions SET status='completed', finished_at=now() WHERE id=$1",
                    session_id,
                )
            await connection.execute(
                """UPDATE oge15_sessions SET navigation_revision=navigation_revision+1
                   WHERE id=$1""",
                session_id,
            )
            return True

    async def position_stats(self, telegram_user_id: int) -> dict[int, dict[str, int]]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                """SELECT position, issued, correct, skipped, solutions_viewed,
                          hints_used, attempts, first_attempts, second_attempts
                   FROM oge15_position_stats AS stats
                   JOIN users AS app_user ON app_user.id=stats.user_id
                   WHERE app_user.telegram_user_id=$1 ORDER BY position""",
                telegram_user_id,
            )
        return {
            row["position"]: {
                key: row[key]
                for key in (
                    "issued", "correct", "skipped", "solutions_viewed", "hints_used",
                    "attempts", "first_attempts", "second_attempts",
                )
            }
            for row in rows
        }


__all__ = ["AttemptResult", "ScenarioPostgresRepository", "ScenarioSession"]
