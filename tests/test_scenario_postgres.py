from __future__ import annotations

import json
import os
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import asyncpg
import pytest

from app.math.scenario_engine import (
    POSITIONS,
    PracticeMode,
    QuestionDraft,
    QuestionSnapshot,
    ScenarioAssetRef,
    ScenarioIntegrityError,
    ScenarioSnapshot,
)
from app.persistence.repository import read_migration
from app.persistence.scenario_repository import AttemptResult, ScenarioPostgresRepository


def _snapshot() -> ScenarioSnapshot:
    questions = tuple(
        QuestionSnapshot.from_draft(
            QuestionDraft(
                position=position,
                scenario_seed=12345,
                family_id=f"PAPER-F{position:02}",
                generator_version="paper-v1",
                condition=f"Question {position}",
                answer_policy_id="paper.numeric",
                answer_policy_version="1",
                canonical_answer=str(position),
                hints=("hint",),
                solution_steps=("step",),
                math_model={"answer": position},
            )
        )
        for position in POSITIONS
    )
    return ScenarioSnapshot(
        story_code="PAPER",
        seed=12345,
        generator_version="paper-v1",
        compatibility_matrix_version="paper-compat-v1",
        context={"table": [[1, 2], [3, 4]]},
        shared_context="Shared paper table",
        assets=(ScenarioAssetRef("a" * 64, "image/png", f"sha256/{'a' * 64}.png"),),
        questions=questions,
        provenance=("catalog:fixture",),
    )


async def _test_database(database_url: str) -> tuple[asyncpg.Connection, str, str]:
    admin = await asyncpg.connect(database_url)
    name = f"oge15_scenario_{uuid4().hex}"
    await admin.execute(f'CREATE DATABASE "{name}"')
    parsed = urlsplit(database_url)
    test_url = urlunsplit((parsed.scheme, parsed.netloc, f"/{name}", parsed.query, parsed.fragment))
    return admin, name, test_url


@pytest.mark.asyncio
async def test_scenario_snapshot_resume_callbacks_attempts_stats_and_asset_retention() -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL not configured")
    admin, database_name, test_url = await _test_database(database_url)
    pool = await asyncpg.create_pool(test_url)
    user_id = int(uuid4().int % (2**62)) + 1
    try:
        await pool.execute(await read_migration("migrations/0001_foundation.sql"))
        await pool.execute(await read_migration("migrations/0012_oge15_scenarios.sql"))
        store = ScenarioPostgresRepository(pool)
        snapshot = _snapshot()
        created = await store.start_session(user_id, snapshot, PracticeMode.FULL, POSITIONS)

        assert await pool.fetchval("SELECT count(*) FROM oge15_scenarios") == 1
        assert await pool.fetchval("SELECT count(*) FROM oge15_question_progress") == 5
        assert await pool.fetchval("SELECT count(*) FROM oge15_scenario_assets") == 1
        columns = await pool.fetch(
            """SELECT column_name FROM information_schema.columns
               WHERE table_name='oge15_question_progress'"""
        )
        assert "snapshot" not in {row["column_name"] for row in columns}
        assert await pool.fetchval("SELECT count(*) FROM oge15_protected_assets") == 1
        assert await store.set_condition_message(user_id, created.session_id, 1, 90)
        assert await store.set_control_message(user_id, created.session_id, 0, 100)

        first = await store.record_attempt(
            telegram_user_id=user_id,
            session_id=created.session_id,
            position=1,
            telegram_message_id=101,
            raw_answer="0",
            normalized_answer="0",
            is_correct=False,
        )
        duplicate = await store.record_attempt(
            telegram_user_id=user_id,
            session_id=created.session_id,
            position=1,
            telegram_message_id=101,
            raw_answer="0",
            normalized_answer="0",
            is_correct=False,
        )
        second = await store.record_attempt(
            telegram_user_id=user_id,
            session_id=created.session_id,
            position=1,
            telegram_message_id=102,
            raw_answer="1",
            normalized_answer="1",
            is_correct=True,
        )
        assert (first, duplicate, second) == (
            AttemptResult.ACCEPTED,
            AttemptResult.DUPLICATE,
            AttemptResult.ACCEPTED,
        )
        assert await store.apply_callback(
            telegram_user_id=user_id,
            callback_query_id="callback-next-1",
            session_id=created.session_id,
            control_message_id=100,
            expected_revision=0,
            expected_position=1,
            action="next",
        )
        assert not await store.apply_callback(
            telegram_user_id=user_id,
            callback_query_id="callback-next-1",
            session_id=created.session_id,
            control_message_id=100,
            expected_revision=0,
            expected_position=1,
            action="next",
        )
        assert not await store.apply_callback(
            telegram_user_id=user_id,
            callback_query_id="callback-old-menu",
            session_id=created.session_id,
            control_message_id=100,
            expected_revision=0,
            expected_position=1,
            action="skip",
        )

        restarted_store = ScenarioPostgresRepository(pool)
        restored = await restarted_store.resume_session(user_id)
        assert restored is not None
        assert restored.session_id == created.session_id
        assert restored.current_position == 2
        assert restored.navigation_revision == 1
        assert restored.question_status == "active"
        assert restored.attempt_count == 0 and restored.hints_used == 0
        assert restored.control_message_id == 100
        assert restored.snapshot == snapshot
        stats = await restarted_store.position_stats(user_id)
        assert stats[1] == {
            "issued": 1,
            "correct": 1,
            "skipped": 0,
            "solutions_viewed": 0,
            "hints_used": 0,
            "attempts": 2,
            "first_attempts": 1,
            "second_attempts": 1,
        }
        assert stats[0]["issued"] == 2

        await pool.execute(
            """UPDATE oge15_scenarios
               SET snapshot=jsonb_set(snapshot, '{shared_context}', '"tampered"'::jsonb)
               WHERE id=$1""",
            created.scenario_id,
        )
        with pytest.raises(ScenarioIntegrityError, match="SHA-256"):
            await restarted_store.resume_session(user_id)
        await pool.execute(
            "UPDATE oge15_scenarios SET snapshot=$2::jsonb WHERE id=$1",
            created.scenario_id,
            json.dumps(snapshot.to_snapshot()),
        )

        await pool.execute(
            "UPDATE oge15_sessions SET status='completed', finished_at=now() WHERE id=$1",
            created.session_id,
        )
        single = await restarted_store.start_session(
            user_id, snapshot, PracticeMode.SINGLE, (4,)
        )
        assert await pool.fetchval(
            "SELECT count(*) FROM oge15_question_progress WHERE session_id=$1",
            single.session_id,
        ) == 1
        assert await pool.fetchval(
            "SELECT jsonb_array_length(snapshot->'questions') FROM oge15_scenarios WHERE id=$1",
            single.scenario_id,
        ) == 5
        await pool.execute(
            "UPDATE oge15_sessions SET status='completed', finished_at=now() WHERE id=$1",
            single.session_id,
        )
        assert await pool.fetchval("SELECT count(*) FROM oge15_protected_assets") == 0
        assert await pool.fetchval("SELECT count(*) FROM oge15_assets") == 1
    finally:
        await pool.execute("DELETE FROM users WHERE telegram_user_id=$1", user_id)
        await pool.close()
        await admin.execute(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)')
        await admin.close()
