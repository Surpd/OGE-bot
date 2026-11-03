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

@pytest.fixture
async def insights_pool():
    import os
    from uuid import uuid4

    import asyncpg

    from app.persistence.repository import read_migration

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL not configured")
    connection = await asyncpg.connect(database_url)
    schema = f"test_insights_{uuid4().hex}"
    pool = None
    try:
        assert int(await connection.fetchval("SHOW server_version_num")) >= 170000
        await connection.execute(f'CREATE SCHEMA "{schema}"')
        pool = await asyncpg.create_pool(
            database_url, min_size=1, max_size=2,
            server_settings={"search_path": f'"{schema}", public'},
        )
        for migration in ("migrations/0001_foundation.sql",
                          "migrations/0003_task6_session_quality.sql"):
            await pool.execute(await read_migration(migration))
        yield pool
    finally:
        if pool is not None:
            await pool.close()
        await connection.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        await connection.close()


@pytest.mark.asyncio
async def test_postgres_insights_survive_restart_and_isolate_user(insights_pool):
    from app.persistence.repository import PostgresRepository

    pool = insights_pool
    uid = await pool.fetchval("INSERT INTO users(telegram_user_id) VALUES(123) RETURNING id")
    # Detached old family, detached snapshot fallback, and current outcome semantics.
    records = [
        record(9),
        record(12, family_id="legacy", solution_viewed=True, outcome="solution_viewed",
               attempts=[{"attempt_no": 1, "is_correct": True, "used_hint": False}]),
        record(6, hints_used=2, attempts=[{"attempt_no": 1, "is_correct": False},
                                       {"attempt_no": 2, "is_correct": True, "used_hint": True}]),
        record(14, outcome="failed", attempts=[{"attempt_no": 1, "is_correct": False}]),
        record(8, outcome="skipped"),
    ]
    for row in records:
        import json

        pid = await pool.fetchval(
            """INSERT INTO issued_problems(user_id,family_id,generator_version,fingerprint,
               snapshot,outcome,hints_used,solution_viewed_at)
               VALUES($1,$2,'1','test',$3::jsonb,$4,$5,
                      CASE WHEN $6 THEN now() END) RETURNING id""",
            uid, (row["family_id"] if row["family_id"] == "legacy"
                  else f"OGE{row['number']:02}-F001"),
            json.dumps({"condition": "1+2", "exam_number": row["number"]}),
            row["outcome"], row.get("hints_used", 0), row.get("solution_viewed", False))
        for attempt in row["attempt_records"]:
            await pool.execute(
                """INSERT INTO attempts(problem_id,user_id,attempt_no,raw_answer,
                                        is_correct,used_hint) VALUES($1,$2,$3,'3',$4,$5)""",
                pid, uid, attempt["attempt_no"],
                attempt["is_correct"], attempt.get("used_hint", False))
    repository = PostgresRepository(pool)
    insights = await training_insights(repository, 123)
    expected = summarize(records)
    assert insights["total"] == expected["total"]
    assert insights["numbers"] == expected["numbers"]
    assert (await training_insights(repository, 124))["total"]["issued"] == 0
    errors = await training_insights(repository, 123, "errors")
    assert errors["page_total"] == 2
    assert len(errors["errors"]) == 2
    assert all("snapshot" not in row and "answer" not in row for row in errors["errors"])
    families = await training_insights(repository, 123, "families")
    assert families["page_total"] == 5
    assert sum(row["issued"] for row in families["families"]) == 5


@pytest.mark.asyncio
async def test_postgres_synthetic_history_has_bounded_transfer(insights_pool, record_property):
    import json
    from time import perf_counter

    from app.persistence.repository import PostgresRepository

    pool = insights_pool
    uid = await pool.fetchval("INSERT INTO users(telegram_user_id) VALUES(456) RETURNING id")
    repository = PostgresRepository(pool)
    for size in (100, 10000):
        await pool.execute("DELETE FROM issued_problems WHERE user_id=$1", uid)
        await pool.execute(
            """INSERT INTO issued_problems(user_id,family_id,generator_version,fingerprint,
               snapshot,outcome,issued_at)
               SELECT $1,'OGE09-F001','1',i::text,
                      jsonb_build_object('condition','x+1=2','image_base64',repeat(md5(i::text),128)),
                      'solved', now()-i*interval '1 second' FROM generate_series(1,$2::int) i""",
            uid, size)
        await pool.execute(
            """INSERT INTO attempts(problem_id,user_id,attempt_no,raw_answer,is_correct,used_hint)
               SELECT id,user_id,1,'1',true,false FROM issued_problems WHERE user_id=$1""", uid)
        await pool.execute("ANALYZE issued_problems")
        await pool.execute("ANALYZE attempts")
        timings = {}
        for page in ("summary", "history:6", "errors", "families"):
            started = perf_counter()
            result = await training_insights(repository, 456, page)
            timings[page] = round((perf_counter()-started)*1000, 2)
            assert len(json.dumps(result, default=str)) < 12000
            if page == "summary":
                assert result["total"]["unassisted_correct"] == size
                assert not result["history"]
            if page == "history:6":
                assert result["page_total"] == size
                assert len(result["history"]) == 6
        record_property(f"insights_{size}_rows_ms", json.dumps(timings))
        print(f"insights {size} rows ms: {timings}")


@pytest.mark.asyncio
async def test_postgres_projection_only_fetches_requested_bounded_page():
    from types import SimpleNamespace

    from app.persistence.training_insights import METRICS

    class Pool:
        def __init__(self):
            self.queries = []

        async def fetchval(self, query, *args):
            self.queries.append(query)
            return 10000

        async def fetch(self, query, *args):
            self.queries.append(query)
            assert "p.snapshot," not in query
            assert "jsonb_agg" not in query
            if "GROUPING SETS" in query:
                assert args == (123,)
                return [{"number": None, **dict.fromkeys(METRICS, 0)}]
            assert args == (123, 6, 6)
            assert "LIMIT $2 OFFSET $3" in query
            assert "left(i.snapshot->>'condition', 120)" in query
            return [{"id": "old", "number": 9, "family_id": "OGE09-F001",
                     "condition": "x+1=2", "outcome": "solved", "issued_at": datetime.now(UTC)}]

    pool = Pool()
    repository = SimpleNamespace(_pool=pool)
    summary = await training_insights(repository, 123)
    assert not summary["history"]
    assert len(pool.queries) == 1
    assert "->>'condition'" not in pool.queries[0]
    history = await training_insights(repository, 123, "history:6")
    assert history["page_total"] == 10000
    assert len(history["history"]) == 1
    assert "Записи 7–12 из 10000" in render_progress(history, "history:6")
    assert "snapshot" not in history["history"][0]


@pytest.mark.asyncio
async def test_memory_pages_keep_unknown_old_results_and_bound_history():
    repository = MemoryRepository()
    repository.issued_history[1] = {
        str(i): {"family_id": "OGE06-F001", "condition": str(i), "image": "x" * 10000}
        for i in range(25)
    }
    repository.outcomes[1] = {str(i): "solved" for i in range(25)}
    summary = await training_insights(repository, 1)
    assert summary["total"]["unknown_correct_attempt"] == 25
    assert summary["history"] == []
    history = await training_insights(repository, 1, "history:6")
    assert history["page_total"] == 25
    assert [r["condition"] for r in history["history"]] == [str(i) for i in range(18, 12, -1)]
    assert all("image" not in row for row in history["history"])
