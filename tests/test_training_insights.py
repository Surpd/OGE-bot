from datetime import UTC, datetime

import pytest

from app.bot.progress import progress_keyboard, render_progress
from app.persistence.repository import MemoryRepository
from app.persistence.training_insights import summarize, training_insights


def record(number=6, outcome="solved", attempts=None, **extra):
    return {"number": number, "family_id": "OGE06-F001", "outcome": outcome,
            "attempt_records": attempts or [], "condition": "1 + 2", **extra}


def test_solved_metrics_use_terminal_outcome_and_attempt_time_assistance():
    insights = summarize([
        record(attempts=[{"attempt_no": 1, "is_correct": True, "used_hint": False}]),
        record(9, attempts=[{"attempt_no": 1, "is_correct": False},
                            {"attempt_no": 2, "is_correct": True, "used_hint": True}],
               hints_used=1),
        record(10, outcome="solution_viewed", solution_viewed=True,
               attempts=[{"attempt_no": 1, "is_correct": True, "used_hint": False}]),
        record(12, outcome="failed", attempts=[{"attempt_no": 1, "is_correct": False},
                                              {"attempt_no": 2, "is_correct": False}]),
        record(14, outcome="skipped"),
    ])
    assert insights["total"] == {
        "issued": 5, "attempts": 6, "correct": 2, "first_correct": 1, "second_correct": 1,
        "unassisted_correct": 1, "assisted_correct": 1, "unknown_assistance": 0,
        "unknown_correct_attempt": 0,
        "failed": 1, "skipped": 1, "hints_used": 1, "solutions_viewed": 1,
    }
    assert len(insights["errors"]) == 2
    assert insights["numbers"][7]["issued"] == 0


def test_historical_missing_attempts_and_assistance_are_unknown():
    insights = summarize([record(), record(attempts=[{"attempt_no": 2, "is_correct": True}])])
    assert insights["total"]["correct"] == 2
    assert insights["total"]["unknown_assistance"] == 2
    assert insights["total"]["unassisted_correct"] == 0
    assert insights["total"]["first_correct"] == 0
    assert "неизвестно" in render_progress(insights)


@pytest.mark.asyncio
async def test_memory_adapter_preserves_training_and_separates_users():
    repository = MemoryRepository()
    repository.states[1] = "task6"
    repository.training[1] = {"state": {"attempts": 1}}
    repository.issued_history[1] = {"a": {"family_id": "OGE06-F001", "condition": "1+2"}}
    repository.outcomes[1] = {"a": "solved"}
    repository.attempt_history[1] = [{"problem_id": "a", "attempt_no": 1, "is_correct": True}]
    repository.issued9[1] = {"b": {"family_id": "OGE09-F001"}}
    repository.outcomes9[1] = {"b": "skipped"}
    repository.issued14[2] = {"other": {"family_id": "other"}}
    insights = await training_insights(repository, 1)
    assert insights["total"]["issued"] == 2
    assert insights["total"]["skipped"] == 1
    assert repository.states[1] == "task6"
    assert repository.training[1] == {"state": {"attempts": 1}}
    assert insights["families"][0]["name"] != "OGE06-F001"


def test_all_pages_are_bounded_and_paginate_without_exposing_answers():
    records = [record(issued_at=datetime.now(UTC), condition="x" * 500,
                      family_id=f"old-{index}") for index in range(30)]
    insights = summarize(records)
    for page in ("summary", "numbers", "families", "families:6", "history", "errors"):
        assert len(render_progress(insights, page)) < 4096
    keyboard = progress_keyboard("history:6", 30)
    callbacks = [b.callback_data for row in keyboard.inline_keyboard for b in row]
    assert "progress:history:0" in callbacks
    assert "progress:history:12" in callbacks
    assert "nav:main" in callbacks

@pytest.mark.asyncio
async def test_postgres_insights_survive_restart_and_isolate_user():
    import os
    from uuid import uuid4

    import asyncpg

    from app.persistence.repository import PostgresRepository, read_migration

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL not configured")
    pool = await asyncpg.create_pool(database_url)
    user_id = int(uuid4().int % (2**62)) + 1
    try:
        for migration in ("migrations/0001_foundation.sql", "migrations/0002_task6_training.sql",
                          "migrations/0003_task6_session_quality.sql"):
            await pool.execute(await read_migration(migration))
        repository = PostgresRepository(pool)
        await repository.register_user(user_id)
        uid = await pool.fetchval("SELECT id FROM users WHERE telegram_user_id=$1", user_id)
        session = await pool.fetchval(
            "INSERT INTO sessions(user_id,mode) VALUES($1,'task6') RETURNING id", uid)
        pid = await pool.fetchval(
            """INSERT INTO issued_problems(user_id,session_id,family_id,generator_version,
               fingerprint,snapshot,outcome,hints_used) VALUES($1,$2,'OGE06-F001','1',
               'test','{"condition":"1+2"}'::jsonb,'solved',1) RETURNING id""", uid, session)
        await pool.execute(
            """INSERT INTO attempts(problem_id,user_id,attempt_no,raw_answer,is_correct,used_hint)
               VALUES($1,$2,1,'3',true,true)""", pid, uid)
        insights = await training_insights(PostgresRepository(pool), user_id)
        assert insights["total"]["assisted_correct"] == 1
        assert insights["total"]["unassisted_correct"] == 0
        assert insights["numbers"][6]["first_correct"] == 1
        assert (await training_insights(repository, user_id + 1))["total"]["issued"] == 0
    finally:
        await pool.execute("DELETE FROM users WHERE telegram_user_id=$1", user_id)
        await pool.close()

@pytest.mark.asyncio
async def test_postgres_projection_decodes_json_and_retains_detached_history():
    from types import SimpleNamespace

    class Pool:
        async def fetch(self, query, user_id):
            assert user_id == 123
            assert "u.telegram_user_id=$1" in query
            return [{"id": "old", "family_id": "OGE09-F001", "mode": None,
                     "snapshot": '{"condition":"x+1=2","answer":"1"}',
                     "outcome": "solved", "hints_used": 0, "solution_viewed": False,
                     "issued_at": datetime.now(UTC),
                     "attempt_records": '[{"attempt_no":1,"is_correct":true,"used_hint":false}]'}]

    insights = await training_insights(SimpleNamespace(_pool=Pool()), 123)
    assert insights["numbers"][9]["correct"] == 1
    assert insights["total"]["unassisted_correct"] == 1
    assert "answer" not in insights["history"][0]
    assert "snapshot" not in insights["history"][0]
