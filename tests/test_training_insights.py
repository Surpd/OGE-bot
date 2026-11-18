from datetime import UTC, datetime
from pathlib import Path

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
        "issued": 5, "completed": 5, "answered_tasks": 4, "success_rate": 50.0,
        "attempts": 6, "incorrect_attempts": 3, "correct": 2,
        "first_correct": 1, "second_correct": 1,
        "unassisted_correct": 1, "assisted_correct": 1, "unknown_assistance": 0,
        "unknown_correct_attempt": 0,
        "error_tasks": 2, "failed": 1, "skipped": 1, "hints_used": 1,
        "solutions_viewed": 1,
    }
    assert len(insights["errors"]) == 2
    assert insights["numbers"][7]["issued"] == 0


def test_historical_missing_attempts_and_assistance_are_unknown():
    insights = summarize([record(), record(attempts=[{"attempt_no": 2, "is_correct": True}])])
    assert insights["total"]["correct"] == 2
    assert insights["total"]["unknown_assistance"] == 2
    assert insights["total"]["unassisted_correct"] == 0
    assert insights["total"]["first_correct"] == 0


@pytest.mark.parametrize(
    ("outcome", "attempts", "answered", "correct", "used_hint"),
    [
        ("solved", [True], 1, 1, False),  # correct first attempt
        ("solved", [False, True], 1, 1, False),  # wrong then correct
        ("solved", [True], 1, 1, True),  # hint assisted is still correct
        ("failed", [False, False], 1, 0, False),  # two mistakes are one task
        ("skipped", [False], 1, 0, False),  # one mistake then skip
        ("solution_viewed", [False], 1, 0, False),  # mistake then reveal
        ("skipped", [], 0, 0, False),
        ("solution_viewed", [], 0, 0, False),
        ("issued", [], 0, 0, False),
        ("active", [False], 1, 0, False),  # active first mistake counts immediately
    ],
)
def test_answered_task_denominator_counts_tasks_not_attempts(
    outcome, attempts, answered, correct, used_hint
):
    attempts = [
        {"attempt_no": index, "is_correct": is_correct,
         "used_hint": used_hint if is_correct else False}
        for index, is_correct in enumerate(attempts, 1)
    ]
    totals = summarize([record(outcome=outcome, attempts=attempts)])["total"]
    assert totals["issued"] == 1
    assert totals["answered_tasks"] == answered
    assert totals["correct"] == correct
    assert totals["success_rate"] == (correct * 100 / answered if answered else None)
    assert 0 <= (totals["success_rate"] or 0) <= 100


def test_empty_and_legacy_statistics_have_safe_rates_and_unknown_assistance():
    from app.persistence.training_insights import success_label

    empty = summarize([])
    assert empty["total"]["answered_tasks"] == 0
    assert empty["total"]["success_rate"] is None
    assert success_label(empty["total"]) == "—"
    old = summarize([
        record(outcome="solved"), record(outcome="failed"),
        record(outcome="skipped"), record(outcome="solution_viewed"),
    ])
    assert old["total"]["answered_tasks"] == 2
    assert old["total"]["correct"] == 1
    assert old["total"]["unknown_assistance"] == 1
    assert old["total"]["first_correct"] == old["total"]["second_correct"] == 0
    assert old["total"]["correct"] <= old["total"]["answered_tasks"]


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
        for migration in sorted(Path("migrations").glob("*.sql")):
            await pool.execute(await read_migration(str(migration)))
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
async def test_postgres_widget_unifies_practical_and_ordinary_outcomes(insights_pool):
    import json

    from app.bot.progress_widget import widget_response
    from app.persistence.repository import PostgresRepository

    pool = insights_pool
    telegram_user_id = 918273645
    user_id = await pool.fetchval(
        "INSERT INTO users(telegram_user_id) VALUES($1) RETURNING id", telegram_user_id
    )
    ordinary = [
        (9, "solved", [False, True]),
        (12, "issued", []),
        (7, "solution_viewed", [True]),
        (14, "solved", []),  # historical terminal row with unknown attempt/hint metadata
    ]
    for number, outcome, attempts in ordinary:
        problem_id = await pool.fetchval(
            """INSERT INTO issued_problems(user_id,family_id,generator_version,fingerprint,
               snapshot,outcome,solution_viewed_at)
               VALUES($1,$2,'1',$3,$4::jsonb,$5,
                      CASE WHEN $5='solution_viewed' THEN now() END) RETURNING id""",
            user_id, f"OGE{number:02}-F001", f"ordinary-{number}",
            json.dumps({"condition": f"Условие №{number}", "exam_number": number}), outcome,
        )
        for attempt_no, is_correct in enumerate(attempts, 1):
            await pool.execute(
                """INSERT INTO attempts(problem_id,user_id,attempt_no,raw_answer,
                       is_correct,used_hint) VALUES($1,$2,$3,'ответ',$4,$5)""",
                problem_id, user_id, attempt_no, is_correct, bool(is_correct and attempt_no == 2),
            )

    scenario_id = await pool.fetchval(
        """INSERT INTO oge15_scenarios(user_id,story_code,seed,generator_version,
           snapshot_schema_version,snapshot,snapshot_sha256)
           VALUES($1,'PAPER',1,'fixture',1,$2::jsonb,repeat('a',64)) RETURNING id""",
        user_id, json.dumps({"questions": [
            {"condition": f"Практическое условие {position}"} for position in range(1, 6)
        ]}),
    )
    session_id = await pool.fetchval(
        """INSERT INTO oge15_sessions(user_id,scenario_id,story_code,mode,current_position)
           VALUES($1,$2,'PAPER','full',3) RETURNING id""", user_id, scenario_id,
    )
    statuses = ("skipped", "active", "solved", "solution_viewed", "skipped")
    for position, status in enumerate(statuses, 1):
        await pool.execute(
            """INSERT INTO oge15_question_progress(session_id,position,status,hints_used,
                   solution_viewed_at) VALUES($1,$2,$3,CASE WHEN $2::smallint=3 THEN 1 ELSE 0 END,
               CASE WHEN $3='solution_viewed' THEN now() END)""",
            session_id, position, status,
        )
    for attempt_no, is_correct, used_hint in ((1, False, False), (2, True, True)):
        await pool.execute(
            """INSERT INTO oge15_attempts(session_id,position,attempt_no,telegram_message_id,
               raw_answer,is_correct,used_hint) VALUES($1,3,$2,$3,'answer',$4,$5)""",
            session_id, attempt_no, 10_000 + attempt_no, is_correct, used_hint,
        )
    # A viewed solution with an old correct attempt must not become a solved result.
    await pool.execute(
        """INSERT INTO oge15_attempts(session_id,position,attempt_no,telegram_message_id,
           raw_answer,is_correct,used_hint) VALUES($1,4,1,10004,'answer',true,false)""",
        session_id,
    )

    repository = PostgresRepository(pool)
    total = (await training_insights(repository, telegram_user_id))["total"]
    assert total["issued"] == 9  # five individual questions share one scenario snapshot
    assert total["completed"] == 7
    assert total["answered_tasks"] == 5
    assert total["correct"] == 3
    assert total["success_rate"] == 60.0
    assert total["assisted_correct"] == 2
    assert total["unassisted_correct"] == 0
    assert total["unknown_assistance"] == 1
    assert total["unknown_correct_attempt"] == 1
    assert total["second_correct"] == 2
    assert total["error_tasks"] == 2  # wrong first attempt remains visible
    assert total["incorrect_attempts"] == 2
    assert total["solutions_viewed"] == 2
    assert total["skipped"] == 2

    by_number = (await training_insights(repository, telegram_user_id, "numbers"))["numbers"]
    assert by_number[1]["issued"] == 1 and by_number[1]["skipped"] == 1
    assert by_number[2]["issued"] == 1 and by_number[2]["completed"] == 0
    assert by_number[3]["correct"] == 1 and by_number[3]["error_tasks"] == 1
    assert by_number[4]["correct"] == 0 and by_number[4]["solutions_viewed"] == 1
    assert by_number[5]["skipped"] == 1
    memory = MemoryRepository()
    memory.issued9[telegram_user_id] = {
        "ordinary-9": {"family_id": "OGE09-F001", "condition": "Условие №9"},
    }
    memory.outcomes9[telegram_user_id] = {"ordinary-9": "solved"}
    memory.attempts9[telegram_user_id] = [
        {"problem_id": "ordinary-9", "attempt_no": 1, "is_correct": False,
         "used_hint": False},
        {"problem_id": "ordinary-9", "attempt_no": 2, "is_correct": True,
         "used_hint": True},
    ]
    memory.issued12[telegram_user_id] = {
        "ordinary-12": {"family_id": "OGE12-F001", "condition": "Условие №12"},
    }
    memory.issued7[telegram_user_id] = {
        "ordinary-7": {"family_id": "OGE07-F001", "condition": "Условие №7"},
    }
    memory.outcomes7[telegram_user_id] = {"ordinary-7": "solution_viewed"}
    memory.solutions7[telegram_user_id] = {"ordinary-7"}
    memory.attempts7[telegram_user_id] = [
        {"problem_id": "ordinary-7", "attempt_no": 1, "is_correct": True,
         "used_hint": False},
    ]
    memory.issued14[telegram_user_id] = {
        "ordinary-14": {"family_id": "OGE14-F001", "condition": "Условие №14"},
    }
    memory.outcomes14[telegram_user_id] = {"ordinary-14": "solved"}
    memory._mixed_training_records[telegram_user_id] = [
        {"id": f"scenario-{position}", "record_id": f"m:scenario-{position}",
         "number": position, "family_id": "OGE15:PAPER", "outcome": status,
         "attempt_records": attempts, "hints_used": int(position == 3)}
        for position, status, attempts in (
            (1, "skipped", []),
            (2, "active", []),
            (3, "solved", [
                {"attempt_no": 1, "is_correct": False, "used_hint": False},
                {"attempt_no": 2, "is_correct": True, "used_hint": True},
            ]),
            (4, "solution_viewed", [
                {"attempt_no": 1, "is_correct": True, "used_hint": False},
            ]),
            (5, "skipped", []),
        )
    ]
    memory_total = (await training_insights(memory, telegram_user_id))["total"]
    assert total == memory_total
    assert (await training_insights(memory, telegram_user_id))["numbers"] == by_number
    history_json = await widget_response(repository, telegram_user_id, "tab:h")
    history = __import__("json").loads(history_json)
    assert len(history["r"]) == 3
    assert len(history_json.encode()) <= 1024
    assert all("answer" not in json.dumps(row).lower() for row in history["r"])
    practical_detail = await widget_response(
        repository, telegram_user_id, f"item:s:{session_id}:3"
    )
    detail = json.loads(practical_detail)["d"]
    assert detail["n"] == "№1–5 · PAPER · №3"
    assert detail["a"] == [
        {"n": 1, "ok": False, "h": False},
        {"n": 2, "ok": True, "h": True},
    ]
    assert await widget_response(repository, 112233, f"item:s:{session_id}:3") == '{"tab":"err"}'


@pytest.mark.asyncio
@pytest.mark.mass
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
                return [{"number": None, "family_id": None, **dict.fromkeys(METRICS, 0)}]
            assert args == (123, 6, 6)
            assert "LIMIT $2 OFFSET $3" in query
            assert "left(i.snapshot->>'condition',160)" in query
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


@pytest.mark.asyncio
async def test_all_ordinary_numbers_match_memory_and_postgres(insights_pool):
    import json

    from app.persistence.repository import PostgresRepository
    from app.persistence.training_insights import training_record_detail

    memory = MemoryRepository()
    user_id = await insights_pool.fetchval(
        "INSERT INTO users(telegram_user_id) VALUES(778899) RETURNING id"
    )
    ordinary_ids = {}
    for number in range(6, 20):
        pid = await insights_pool.fetchval(
            """INSERT INTO issued_problems(user_id,family_id,generator_version,fingerprint,
               snapshot,outcome,hints_used) VALUES($1,$2,'1',$2,$3::jsonb,'solved',1)
               RETURNING id""",
            user_id, f"OGE{number:02}-F001", json.dumps({"condition": f"task {number}"}),
        )
        for attempt_no, is_correct in ((1, False), (2, True)):
            await insights_pool.execute(
                """INSERT INTO attempts(problem_id,user_id,attempt_no,raw_answer,
                                     is_correct,used_hint)
                   VALUES($1,$2,$3,'x',$4,$5)""",
                pid, user_id, attempt_no, is_correct, is_correct,
            )
        issued_attr = "issued_history" if number == 6 else f"issued{number}"
        attempts_attr = "attempt_history" if number == 6 else f"attempts{number}"
        outcomes_attr = "outcomes" if number == 6 else f"outcomes{number}"
        hints_attr = "hints_history" if number == 6 else f"hints{number}"
        getattr(memory, issued_attr)[778899] = {
            str(pid): {"family_id": f"OGE{number:02}-F001", "condition": f"task {number}"}
        }
        getattr(memory, attempts_attr)[778899] = [
            {"problem_id": str(pid), "attempt_no": no, "is_correct": correct,
             "used_hint": correct} for no, correct in ((1, False), (2, True))
        ]
        getattr(memory, outcomes_attr)[778899] = {str(pid): "solved"}
        getattr(memory, hints_attr)[778899] = {str(pid): 1}
        if number == 18:
            target = str(pid)
        if number == 9:
            ordinary_ids[number] = pid

    # Mixed tasks live in their own tables and must contribute once beside
    # ordinary records, with two attempts still representing one task.
    mixed_session = await insights_pool.fetchval(
        """INSERT INTO mixed_training_sessions(user_id,state)
           VALUES($1,'{}'::jsonb) RETURNING id""", user_id
    )
    mixed_cases = (
        ("solved", (False, True)),
        ("failed", (False, False)),
        ("skipped", ()),
    )
    memory_mixed = []
    for index, (outcome, answers) in enumerate(mixed_cases):
        # IDs are table-local; a same-UUID ordinary row must not absorb mixed
        # attempts or be counted twice as an answer.
        mixed_id = ordinary_ids[9] if index == 0 else None
        mixed_id = await insights_pool.fetchval(
            """INSERT INTO mixed_training_problems(id,session_id,number,family_id,
               fingerprint,snapshot,snapshot_sha256,outcome,hints_used)
               VALUES(COALESCE($2::uuid,gen_random_uuid()),$1,9,'OGE09-F001',$3,
                      '{}'::jsonb,repeat('a',64),$4,$5) RETURNING id""",
            mixed_session, mixed_id, f"mixed-{index}", outcome, int(any(answers))
        )
        attempt_records = []
        for attempt_no, is_correct in enumerate(answers, 1):
            await insights_pool.execute(
                """INSERT INTO mixed_training_attempts(problem_id,attempt_no,
                   telegram_message_id,raw_answer,is_correct,used_hint)
                   VALUES($1,$2,$3,'answer',$4,$5)""",
                mixed_id, attempt_no, 70_000 + index * 10 + attempt_no,
                is_correct, is_correct,
            )
            attempt_records.append({
                "attempt_no": attempt_no, "is_correct": is_correct,
                "used_hint": is_correct,
            })
        memory_mixed.append({
            "id": str(mixed_id), "record_id": f"m:{mixed_id}", "number": 9,
            "family_id": "OGE09-F001", "outcome": outcome,
            "attempt_records": attempt_records, "hints_used": int(any(answers)),
            "solution_viewed": False, "issued_at": None,
        })
    memory._mixed_training_records[778899] = memory_mixed

    pg = PostgresRepository(insights_pool)
    sql_result = await training_insights(pg, 778899)
    memory_result = await training_insights(memory, 778899)
    assert sql_result["total"] == memory_result["total"]
    assert sql_result["numbers"] == memory_result["numbers"]
    assert sql_result["total"]["incorrect_attempts"] == 17
    assert sql_result["total"]["issued"] == 17
    assert sql_result["total"]["answered_tasks"] == 16
    assert sql_result["total"]["correct"] == 15
    assert sql_result["total"]["success_rate"] == 93.75
    assert sql_result["numbers"][9]["issued"] == 4
    assert sql_result["numbers"][9]["answered_tasks"] == 3
    assert sql_result["numbers"][9]["skipped"] == 1
    for number in range(6, 20):
        row = sql_result["numbers"][number]
        assert (row["issued"], row["correct"], row["second_correct"], row["error_tasks"]) == (
            1, 1, 1, 1
        )
    for repo in (pg, memory):
        assert (await training_insights(repo, 778899, "errors"))["page_total"] == 16
        assert (await training_insights(repo, 778899, "history"))["page_total"] == 17
        assert (await training_insights(repo, 778899, "families"))["page_total"] == 14
        assert (await training_record_detail(repo, 778899, f"o:{target}"))["condition"] == "task 18"
        assert await training_record_detail(repo, 778900, f"o:{target}") is None


def test_recommendations_include_geometry_but_not_closed_number(monkeypatch):
    from app.math import oge19_scheduler

    monkeypatch.setattr(oge19_scheduler, "ENABLED_FAMILIES", ())

    import json

    from app.bot.progress_image import _recommendation as image_recommendation
    from app.bot.progress_widget import overview_data
    from app.persistence.training_insights import recommended_number

    insights = summarize([
        *[record(9, outcome="solved", attempts=[{"is_correct": True}]) for _ in range(4)],
        record(9, outcome="failed", attempts=[{"is_correct": False}]),
        *[record(18, outcome="solved", attempts=[{"is_correct": True}]) for _ in range(3)],
        *[record(18, outcome="failed", attempts=[{"is_correct": False}]) for _ in range(2)],
        *[record(19, outcome="failed", attempts=[{"is_correct": False}]) for _ in range(5)],
    ])
    assert recommended_number(insights["numbers"], insights["families"]) == 18
    assert "№18" in render_progress(insights)
    assert "№18" in json.loads(overview_data(insights))["p"]["r"]
    assert "№18" in image_recommendation(insights)
    assert insights["numbers"][19]["error_tasks"] == 5
    monkeypatch.setattr(oge19_scheduler, "ENABLED_FAMILIES", tuple(oge19_scheduler.FAMILY_THEMES))
    assert recommended_number(insights["numbers"], insights["families"]) == 19
    assert "№19" in render_progress(insights)
    assert "№19" in json.loads(overview_data(insights))["p"]["r"]
    assert "№19" in image_recommendation(insights)


def test_recommendation_requires_minimum_sample_and_avoids_ties():
    from app.persistence.training_insights import recommended_number

    four_of_four = summarize([
        *[record(6, attempts=[{"is_correct": True}]) for _ in range(4)],
        *[record(7, attempts=[{"is_correct": True}]) for _ in range(4)],
    ])
    assert recommended_number(four_of_four["numbers"], four_of_four["families"]) is None
    tied = summarize([
        *[record(6, outcome="failed", attempts=[{"is_correct": False}]) for _ in range(5)],
        *[record(7, outcome="failed", attempts=[{"is_correct": False}]) for _ in range(5)],
    ])
    assert recommended_number(tied["numbers"], tied["families"]) is None

    family_tie = summarize([
        *[record(6, family_id="OGE06-A", outcome="failed",
                 attempts=[{"is_correct": False}]) for _ in range(3)],
        *[record(6, family_id="OGE06-A", attempts=[{"is_correct": True}]) for _ in range(2)],
        *[record(6, family_id="OGE06-B", attempts=[{"is_correct": True}]) for _ in range(5)],
        *[record(7, family_id="OGE07-A", attempts=[{"is_correct": True}]) for _ in range(7)],
        *[record(7, family_id="OGE07-A", outcome="failed",
                 attempts=[{"is_correct": False}]) for _ in range(3)],
    ])
    assert family_tie["numbers"][6]["success_rate"] == 70
    assert family_tie["numbers"][7]["success_rate"] == 70
    assert recommended_number(family_tie["numbers"], family_tie["families"]) == 6


def test_progress_text_uses_answered_denominator_and_keeps_skips_separate():
    four_answered = summarize([
        *[record(6, attempts=[{"attempt_no": 1, "is_correct": True}]) for _ in range(4)],
        *[record(6, outcome="skipped") for _ in range(15)],
    ])
    text = render_progress(four_answered, "number:6")
    assert "Ответили: 4 · верно: 4 · успешность: 100%" in text
    assert "Пропуски: 15" in text
    assert "не менее 5" in text

    five_answered = summarize([
        *[record(6, attempts=[{"attempt_no": 1, "is_correct": True}]) for _ in range(4)],
        record(6, outcome="failed", attempts=[{"attempt_no": 1, "is_correct": False}]),
    ])
    assert "успешность: 80%" in render_progress(five_answered, "number:6")


def test_progress_number_keyboard_includes_every_first_part_number():
    keyboard = progress_keyboard("numbers")
    buttons = [
        button.text
        for row in keyboard.inline_keyboard
        for button in row
        if button.callback_data and button.callback_data.startswith("progress:number:")
    ]
    assert buttons == [f"№{number}" for number in range(1, 20)]
