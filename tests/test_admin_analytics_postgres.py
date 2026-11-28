import json
import os
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import pytest
from pydantic import SecretStr

from app.admin.queries import COST, DAYS, HOME, MODES, RETENTION, TASK, TYPE_ORDERS, TYPES, WRITTEN
from app.admin.repository import AdminRepository
from app.admin.service import AdminService, ReportWindow
from app.persistence.part2_grades import budget_usage


@pytest.fixture
async def analytics(bank_pool):
    schema = await bank_pool.fetchval("SELECT current_schema()")
    role = f"admin_test_{uuid4().hex}"
    provision = Path("scripts/configure_admin_analytics_reader.sql").read_text(encoding="utf-8")
    async with bank_pool.acquire() as conn:
        await conn.execute(provision)
        await conn.execute(
            f"CREATE ROLE {role} LOGIN PASSWORD 'synthetic-admin-password';"
            f"GRANT oge_admin_reader TO {role}"
        )
    url = urlsplit(os.environ["DATABASE_URL"])
    dsn = urlunsplit(url._replace(
        netloc=f"{role}:synthetic-admin-password@{url.netloc.rsplit('@', 1)[-1]}"
    ))
    service = AdminService(
        AdminRepository(SecretStr(dsn), f"{schema}_admin"),
        excluded=frozenset({1, 2}), primary_id=345, environment="test", budget=Decimal(5),
        now=lambda: datetime(2026, 11, 28, 7, 15, tzinfo=UTC),
    )
    try:
        yield service
    finally:
        await service.close()
        await bank_pool.execute(f"DROP ROLE {role}")
        await bank_pool.execute(f'DROP SCHEMA "{schema}_admin" CASCADE')


async def _issue(pool, user, timestamp, family="OGE06-TEST"):
    return await pool.fetchval(
        """INSERT INTO issued_problems(user_id,family_id,generator_version,fingerprint,
              snapshot,issued_at) VALUES($1,$2,'test',$3,'{}',$4::text::timestamptz)
           RETURNING id""",
        user, family, uuid4().hex, timestamp,
    )


async def _answer(pool, user, problem, attempt, correct, stamp, hint=False, message=1):
    await pool.execute(
        """INSERT INTO attempts(user_id,problem_id,attempt_no,raw_answer,is_correct,
             created_at,used_hint,telegram_message_id,bot_id)
           VALUES($1,$2,$3,'private',$4,$5::text::timestamptz,$6,$7,0)""",
        user, problem, attempt, correct, stamp, hint, message,
    )


async def _written_issue(pool, owner, timestamp):
    return await pool.fetchval(
        """INSERT INTO part2_issues(owner,number,task_id,version,subtype_id,closed,issued_at)
           SELECT $1,f.number,v.task_id,v.version,c.subtype_id,true,$2::text::timestamptz
           FROM part2_cards c JOIN part2_versions v USING(task_id)
           JOIN part2_subtypes s USING(subtype_id) JOIN part2_families f USING(family_id)
           WHERE f.number=20 ORDER BY c.task_id,v.version LIMIT 1 RETURNING id""",
        owner, timestamp,
    )


async def _check(pool, issue, revision, timestamp, status, score, cost):
    await pool.execute(
        """INSERT INTO part2_grades(issue_id,revision,created_at,dispatched_at,
                                     model,prompt_version,rubric_version,status,score,
                                     reserved_usd,cost_usd)
           VALUES($1,$2,$3::text::timestamptz,
             CASE WHEN $4='pending' THEN NULL ELSE $3::text::timestamptz END,
             'test','test',1,$4,$5,0.10,$6)""",
        issue, revision, timestamp, status, score, cost,
    )


async def test_admin_reports_on_hand_calculated_data(bank_pool, analytics) -> None:
    await bank_pool.execute("INSERT INTO users(telegram_user_id) VALUES(101),(102),(103),(104)")
    users = {
        row["telegram_user_id"]: row["id"]
        for row in await bank_pool.fetch("SELECT id,telegram_user_id FROM users")
    }
    first = await _issue(bank_pool, users[101], "2026-11-21 00:00+03")
    await _answer(bank_pool, users[101], first, 1, False, "2026-11-21 00:00+03")
    await _answer(bank_pool, users[101], first, 2, True, "2026-11-22 12:00+03", True, 2)
    later = await _issue(bank_pool, users[101], "2026-11-27 10:00+03")
    await _answer(bank_pool, users[101], later, 1, True, "2026-11-27 10:00+03", message=3)
    await bank_pool.execute("""
        UPDATE issued_problems SET solution_viewed_at='2026-11-27 11:00+03' WHERE id=$1
    """, later)
    await bank_pool.execute("""
        INSERT INTO adaptive_evidence(owner,skill,number,source,task,ordinal,variant,
                                      occurred,outcome,attempt)
        VALUES($1,'OGE06-TEST',6,'ordinary',$2,0,'fresh-variant','2026-11-27 10:00+03','issued',0)
    """, users[101], str(later))
    unknown = await _issue(bank_pool, users[101], "2026-11-27 12:00+03")
    await _answer(bank_pool, users[101], unknown, 1, True, "2026-11-27 12:01+03", message=None)
    unfinished = await _issue(bank_pool, users[101], "2026-11-27 22:00+03")
    await _answer(bank_pool, users[101], unfinished, 1, False, "2026-11-27 23:59:59+03", message=4)
    await _answer(bank_pool, users[101], unfinished, 2, True, "2026-11-28 00:00+03", message=5)
    for owner, stamps in {
        1: ["2026-11-23 11:00+03"],
        2: ["2026-11-23 12:00+03"],
        102: ["2026-11-09 11:00+03", "2026-11-16 11:00+03", "2026-11-25 11:00+03"],
        103: ["2026-11-10 11:00+03"],
    }.items():
        for index, stamp in enumerate(stamps, 1):
            problem = await _issue(bank_pool, users[owner], stamp, "OGE08-TEST")
            await _answer(bank_pool, users[owner], problem, 1, False, stamp, message=index)

    issue = await _written_issue(bank_pool, 101, "2026-11-21 13:00+03")
    await _check(bank_pool, issue, 1, "2026-11-22 13:00+03", "graded", 2, Decimal("0.02"))
    await _check(bank_pool, issue, 3, "2026-11-25 13:00+03", "error", None, None)
    await _check(bank_pool, issue, 4, "2026-11-26 13:00+03", "unreadable", None, Decimal("0.03"))
    pending = await _written_issue(bank_pool, 104, "2026-11-26 13:00+03")
    await _check(bank_pool, pending, 2, "2026-11-27 14:00+03", "pending", None, None)
    await _written_issue(bank_pool, 103, "2026-11-27 13:00+03")
    await bank_pool.execute("""
        INSERT INTO part2_api_tests(owner,confirmation,created_at,dispatched_at,status,reserved_usd,
            cost_usd,model)
        VALUES(1,1,'2026-11-27 12:00+03','2026-11-27 12:01+03','graded',0.1,0.015,'test'),
              (1,2,'2020-10-01 12:00+03','2020-10-01 12:01+03','error',0.1,NULL,'test')
    """)

    report = await analytics.load("home", "7")
    assert report.unavailable is None
    expected_home = dict(
        registered=4, active=3, first=2, repeat_days=1, answered=5, attempts=6,
        graded=1, known_cost=Decimal("0.065"), unknown_cost=2, errors=1,
    )
    assert report.data == expected_home
    assert (await analytics.load("home", "7")).updated_at == report.updated_at
    assert (await analytics.load("home", "today")).data["active"] == 1

    usage = (await analytics.load("usage", "7")).data
    assert usage["retention"] == dict(
        eligible=2, returned=1, first_day=date(2026, 11, 8), last_day=date(2026, 11, 14)
    )
    assert [row["active"] for row in usage["days"]] == [1, 1, 0, 0, 2, 1, 2]
    assert sum(row["submitted"] for row in usage["modes"]) == 4
    assert len((await analytics.load("learners", "7")).data["rows"]) == 3
    assert (await analytics.load("learner", "7", key=str(users[101]))).data["solved"] == 3
    assert not (await analytics.load("learner", "7", key=str(users[1]))).data["found"]

    detail = (await analytics.load("task", "7", number=6, key="OGE06-TEST")).data
    assert {field: detail[field] for field in (
        "answered", "solved", "first_correct", "first_unassisted", "assistance_unknown",
        "hinted", "hint_known", "solution_views",
    )} == dict(
        answered=4, solved=3, first_correct=2, first_unassisted=1, assistance_unknown=1,
        hinted=1, hint_known=3, solution_views=1,
    )
    assert detail["novel_first_unassisted"] == 1
    types = (await analytics.load("types", "7", number=6, sort="help")).data
    assert types["rows"][0]["answered"] == 4

    written = (await analytics.load("written", "7")).data
    assert written == {
        "issued": 3, "issues_submitted": 2, "submitted": 4, "revisions": 2, "graded": 1,
        "unreadable": 1, "uncertain": 0, "error": 1, "pending": 1, "more": False,
        "rows": [dict(number=20, subtype_id=None, title=None, submitted=4,
                      graded=1, zero=0, one=0, two=1)],
    }
    cost = (await analytics.load("cost", "7")).data
    assert cost["held"] == Decimal("0.30")
    assert cost["diagnostics"] == 1 and cost["diagnostic_cost"] == Decimal("0.015")
    assert cost["known_cost_per_result"] == Decimal("0.05") and cost["unknown_written"] == 2
    async with bank_pool.acquire() as conn:
        current_budget = await budget_usage(conn, 101)
    assert cost["available"] == Decimal(5) - current_budget["spent"] - current_budget["held"]
    assert (await analytics.load("system", "7")).data["errors"] == 1
    assert analytics.repository is not None
    async with analytics.repository.read() as conn:
        assert await conn.fetchval("SHOW transaction_read_only") == "on"
        assert await conn.fetchval("SELECT current_user LIKE 'admin_test_%'") is True
    await bank_pool.execute("UPDATE part2_grades SET status='uncertain' WHERE issue_id=$1", pending)
    assert (await analytics.load("written", "7")).data["pending"] == 1
    refreshed = (await analytics.load("written", "7", refresh=True)).data
    assert refreshed["pending"] == 0 and refreshed["uncertain"] == 1


async def test_admin_query_plans_on_synthetic_history(bank_pool, analytics) -> None:
    await bank_pool.execute("""
        INSERT INTO users(telegram_user_id) SELECT n FROM generate_series(1001, 9000) n;
        INSERT INTO issued_problems(user_id,family_id,generator_version,fingerprint,
                                    snapshot,issued_at)
        SELECT u.id,'OGE06-PLAN','test',gen_random_uuid()::text,'{}',
               '2026-11-27 08:00+03'::timestamptz
               - ((u.telegram_user_id+n) % 90) * interval '1 day'
        FROM users u CROSS JOIN generate_series(1, 10) n WHERE u.telegram_user_id>=1001;
        INSERT INTO attempts(problem_id,user_id,attempt_no,raw_answer,is_correct,created_at,
                             telegram_message_id)
        SELECT id,user_id,1,'synthetic',true,issued_at+interval '1 minute',NULL
        FROM issued_problems;
        INSERT INTO part2_issues(owner,number,task_id,version,subtype_id,closed,issued_at)
        SELECT u.telegram_user_id,card.number,card.task_id,card.version,card.subtype_id,true,
               '2026-11-27 08:00+03'::timestamptz-(u.telegram_user_id % 45)*interval '1 day'
        FROM users u CROSS JOIN (
            SELECT f.number,v.task_id,v.version,c.subtype_id
            FROM part2_cards c JOIN part2_versions v USING(task_id)
            JOIN part2_subtypes s USING(subtype_id) JOIN part2_families f USING(family_id)
            WHERE f.number=20 ORDER BY c.task_id,v.version LIMIT 1
        ) card WHERE u.telegram_user_id BETWEEN 1001 AND 5000;
        INSERT INTO part2_grades(issue_id,revision,created_at,model,prompt_version,rubric_version,
                                 status,score,reserved_usd,cost_usd)
        SELECT id,1,issued_at+interval '1 hour','test','test',version,
               CASE WHEN id % 10=0 THEN 'error' ELSE 'graded' END,
               CASE WHEN id % 10<>0 THEN 2 END, 0.1, CASE WHEN id % 10<>0 THEN 0.02 END
        FROM part2_issues;
        ANALYZE part2_issues;
        ANALYZE part2_grades;
        ANALYZE users;
        ANALYZE issued_problems;
        ANALYZE attempts;
    """)
    window = ReportWindow.at("7", datetime(2026, 11, 28, 7, 15, tzinfo=UTC))
    args = (window.start, window.end, [])
    first, last = window.mature_cohorts()
    assert analytics.repository is not None
    async with analytics.repository.read() as conn:
        for name, query, params in (
            ("home", HOME, args),
            ("days", DAYS, args),
            ("modes", MODES, args),
            ("retention", RETENTION, (first, last, [])),
            ("types", TYPES.format(order=TYPE_ORDERS["sample"]), (*args, 6, 7, 0)),
            ("task", TASK, (*args, 6, "OGE06-PLAN")),
            ("written", WRITTEN, (*args, 0)),
            ("cost", COST, args),
        ):
            plan_json = await conn.fetchval(
                "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + query, *params
            )
            assert plan_json
            plan = json.loads(plan_json)[0]
            stack = [plan["Plan"]]
            scans = set()
            while stack:
                node = stack.pop()
                stack.extend(node.get("Plans", []))
                if "Index Name" in node:
                    scans.add(node["Index Name"])
            print(
                f"{name}: {plan['Execution Time']:.1f} ms; "
                f"shared blocks {plan['Plan']['Shared Hit Blocks']}; "
                f"indexes {', '.join(sorted(scans)) or 'none'}"
            )
    home = await analytics.load("home", "7", refresh=True)
    assert home.unavailable is None and home.data["answered"] == 6215
