from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from app.adaptive.engine import Evidence, Stage, State, apply
from app.adaptive.planner import plan, unlocked

DAY = 86400


def ev(task, day, outcome="correct", attempt=1, helped=False, fresh=True):
    return Evidence(str(task), str(task), day * DAY, outcome, attempt, helped, fresh)


def trajectory(*events):
    state = State()
    for e in events:
        state, _ = apply(state, e)
    return state


def test_gradual_ordinary_only_closure_and_relapse():
    start = [ev(1, 0, "wrong"), ev(1, 0, "wrong", 2)]
    assert trajectory(*start).stage == Stage.GAP
    practice = [*start, ev(2, 1), ev(3, 1)]
    wait = trajectory(*practice)
    assert wait.due == 3 * DAY
    assert trajectory(*practice, ev(4, 2)) == wait
    delayed = [*practice, ev(4, 30), ev(5, 31)]
    assert trajectory(*delayed).due == 35 * DAY
    closed = trajectory(*delayed, ev(6, 35))
    assert closed.stage == Stage.CONFIRMED and closed.closed == 1
    suspect, _ = apply(closed, ev(7, 50, "wrong"))
    assert suspect.opened == suspect.closed
    reopened, reason = apply(suspect, ev(8, 52, "wrong"))
    assert reason == "gap_reopened" and reopened.opened == 2


def test_strong_learner_rare_errors_and_old_errors():
    assert trajectory(ev(1, 0, "wrong"), ev(2, 40, "wrong")).stage == Stage.CHECK
    strong = trajectory(ev(1, 0, "wrong"), ev(2, 0), ev(3, 0), ev(4, 2), ev(5, 7))
    assert strong.stage == Stage.CONFIRMED and strong.closed == 0


def test_guess_help_replay_and_duplicate_variants():
    for outcome in ("skip", "invalid", "ungraded", "revision", "replay"):
        assert trajectory(ev(1, 0, outcome)) == State()
    for e in (ev(1, 1, helped=True), ev(1, 0, "solution"), ev(2, 1, helped=None)):
        assert trajectory(e).stage == Stage.CHECK
    assert trajectory(ev(1, 0, "wrong"), ev(1, 0, attempt=2)).stage == Stage.CHECK
    assert trajectory(ev(1, 0), ev(2, 1, fresh=False)).practice == 1
    assert trajectory(ev(1, 0, "wrong"), replace(ev(2, 0, "wrong"), variant="1")).opened == 0


def test_personal_selection():
    keys = {f"f{i}": 6 + i for i in range(8)}
    at = datetime(2026, 1, 1, tzinfo=UTC)
    history = [
        (6, "f0", State(stage=Stage.WAIT, due=1), at),
        (7, "f1", State(stage=Stage.GAP, opened=1), at),
    ]
    assert unlocked(history) and not unlocked([])
    slots = plan(history, keys, at.timestamp())
    assert slots[0] == "f0" and "f1" in slots and len(slots) == 5
    assert slots.count("f0") == 1


async def test_pg_evidence_rebuild_session_resume_and_concurrent_updates(bank_pool):
    import asyncio
    import json

    from app.adaptive.session import Session
    from app.adaptive.store import overview, sync
    from app.bot.adaptive import generate
    from app.persistence.repository import PostgresRepository

    repo = PostgresRepository(bank_pool)
    owner = await bank_pool.fetchval("SELECT id FROM users WHERE telegram_user_id=1")
    family = "OGE09-L1"
    from app.persistence.rotation_history import enabled

    family = enabled(9)[0]
    async with bank_pool.acquire() as conn, conn.transaction():
        await conn.execute("SET LOCAL bop.adaptive='on'")
        pid = uuid4()
        await conn.execute(
            """INSERT INTO issued_problems(id,user_id,family_id,generator_version,
            fingerprint,snapshot) VALUES($1,$2,$3,'v','variant-a','{}')""",
            pid,
            owner,
            family,
        )
        for attempt in (1, 2):
            await conn.execute(
                """INSERT INTO attempts(user_id,problem_id,attempt_no,raw_answer,
                is_correct,telegram_message_id) VALUES($1,$2,$3,'0',false,$3::smallint)""",
                owner,
                pid,
                attempt,
            )
    first, second = await asyncio.gather(overview(repo, 1), overview(repo, 1))
    assert first == second and first[0][2].opened == 1
    assert await overview(repo, 2) == []
    session = Session(repo, 1)
    await session.start([family] * 5)
    row = await session.current()
    candidate = generate(family, [])
    assert candidate
    assert await session.save(row, family, candidate)
    assert not await session.save(row, family, candidate)
    reopened = Session(PostgresRepository(bank_pool), 1)
    saved = await reopened.current()
    assert json.loads(saved["snapshot"])["fingerprint"] == candidate["fingerprint"]
    await reopened.set_prompt(1, str(saved["problem"]), 123)
    results = await asyncio.gather(
        *(
            reopened.act(saved["problem"], 123, "answer", raw="1", correct=True, message_id=400)
            for _ in range(2)
        )
    )
    assert sorted(results) == ["solved", "stale"]
    async with bank_pool.acquire() as conn, conn.transaction():
        await sync(conn, owner, rebuild=True)
    assert (await overview(repo, 1))[0][2].practice == 1
    assert (
        await bank_pool.fetchval("SELECT count(*) FROM adaptive_evidence WHERE owner=$1", owner)
        == 5
    )
    assert await reopened.act(saved["problem"], 123, "next") == "next"
    assert (await reopened.current())["position"] == 1


def test_delayed_retrieval_requires_issue_after_interval():
    waiting = trajectory(ev("a", 0), ev("b", 0))
    state, _ = apply(waiting, replace(ev("c", 12), issued=DAY))
    assert state == waiting
    assert apply(waiting, replace(ev("c", 12), issued=3 * DAY))[0].checks == 1


async def test_written_progress_uses_validated_initial_grade_and_preserves_revisions(bank_pool):
    from app.adaptive.sources import item

    owner = await bank_pool.fetchval("SELECT id FROM users WHERE telegram_user_id=1")
    card = await bank_pool.fetchrow("""SELECT c.task_id,c.subtype_id,v.version FROM part2_cards c
        JOIN part2_versions v USING(task_id) WHERE v.reviewed AND v.available LIMIT 1""")
    async with bank_pool.acquire() as conn, conn.transaction():
        await conn.execute("SET LOCAL bop.adaptive='on'")
        for status, score, want in [
            ("graded", 0, "wrong"),
            ("graded", 1, "wrong"),
            ("graded", 2, "correct"),
            ("unreadable", None, "ungraded"),
            ("uncertain", None, "ungraded"),
            ("error", None, "ungraded"),
        ]:
            issue = await conn.fetchval(
                """INSERT INTO part2_issues(
                owner,number,task_id,version,subtype_id,closed)
                VALUES(1,20,$1,$2,$3,true) RETURNING id""",
                card["task_id"],
                card["version"],
                card["subtype_id"],
            )
            for rev in (1, 2):
                await conn.execute(
                    """INSERT INTO part2_grades(issue_id,revision,model,prompt_version,
                    rubric_version,status,score,result,reserved_usd) VALUES($1,$2,'mock','test',
                    1,$3,$4,jsonb_build_object('status',$3::text,'score',$4::smallint) ||
                    '{"criterion_evidence":[{"criterion":"answer","student_evidence":"x=2"}],
                    "needs_review":false}'::jsonb,0)""",
                    issue,
                    rev,
                    status,
                    score,
                )
            got = await item(conn, owner, "written", str(issue))
            assert [(f.outcome, f.assisted) for f in got.facts[1:]] == [
                (want, False),
                ("revision", False),
            ]
            assert all(f.score == score for f in got.facts[1:])


async def test_mixed_and_scenario_share_variant_and_only_fresh_results_count(bank_pool):
    import json

    from app.adaptive.sources import item
    from app.adaptive.store import sync
    from app.bot.adaptive import generate
    from app.math.scenario_engine import ScenarioSnapshot, snapshot_digest

    p = generate("TYRES-DIAMETER", [])
    scene = ScenarioSnapshot.from_snapshot(p["scenario_snapshot"])
    pos = p["number"]
    owner = await bank_pool.fetchval("SELECT id FROM users WHERE telegram_user_id=1")
    async with bank_pool.acquire() as conn, conn.transaction():
        await conn.execute("SET LOCAL bop.adaptive='on'")
        sid = await conn.fetchval(
            """INSERT INTO oge15_scenarios(user_id,story_code,seed,generator_version,
            snapshot_schema_version,snapshot,snapshot_sha256)
            VALUES($1,$2,$3,$4,1,$5,$6) RETURNING id""",
            owner,
            scene.story_code,
            scene.seed,
            scene.generator_version,
            json.dumps(scene.to_snapshot()),
            snapshot_digest(scene),
        )
        session = await conn.fetchval(
            """INSERT INTO oge15_sessions(user_id,scenario_id,mode,story_code,
            current_position) VALUES($1,$2,'single',$3,$4) RETURNING id""",
            owner,
            sid,
            scene.story_code,
            pos,
        )
        await conn.execute(
            """INSERT INTO oge15_question_progress(session_id,position,status)
            VALUES($1,$2,'solved')""",
            session,
            pos,
        )
        await conn.execute(
            """INSERT INTO oge15_attempts(session_id,position,attempt_no,telegram_message_id,
            raw_answer,is_correct) VALUES($1,$2,1,1,'a',true)""",
            session,
            pos,
        )
        mix = await conn.fetchval(
            """INSERT INTO mixed_training_sessions(user_id,state) VALUES($1,'{}') RETURNING id""",
            owner,
        )
        for n in (1, pos):
            uid = uuid4()
            fp = f"{scene.story_code}:{scene.seed}:{n}"
            snap = scene.questions[n - 1].to_snapshot()
            if n == 1:
                snap["_original_scenario_snapshot"] = scene.to_snapshot()
            await conn.execute(
                """INSERT INTO mixed_training_problems(id,session_id,number,family_id,
                fingerprint,snapshot,snapshot_sha256) VALUES($1,$2,$3,$4,$5,$6,repeat('0',64))""",
                uid,
                mix,
                n,
                snap["family_id"],
                fp,
                json.dumps(snap),
            )
        await conn.execute(
            """INSERT INTO mixed_training_attempts(problem_id,attempt_no,telegram_message_id,
            raw_answer,is_correct) VALUES($1,1,2,'answer',true)""",
            uid,
        )
        first = await item(conn, owner, "scenario", f"{session}:{pos}")
        second = await item(conn, owner, "mixed", str(uid))
        assert first.skill == second.skill and first.variant == second.variant == p["fingerprint"]
        await sync(conn, owner)
        practice = await conn.fetchval(
            "SELECT state->>'practice' FROM adaptive_skills WHERE owner=$1 AND skill=$2",
            owner,
            first.skill,
        )
        # Same transaction timestamp for both exposures. No proof either was independent.
        assert practice == "0"


async def test_companion_dispatcher_personal_path_and_repeated_callbacks(monkeypatch, bank_pool):
    import json
    import os

    import asyncpg
    from test_companion_qa import Harness, config

    from app.adaptive.session import Session
    from app.companion.storage import open_storage
    from app.config import get_settings
    from app.persistence.scenario_repository import ScenarioPostgresRepository

    monkeypatch.setenv("OGE_COMPANION_ADAPTIVE_ENABLED", "true")
    get_settings.cache_clear()
    bot_id = 200000000 + int(uuid4().hex[:7], 16)
    url = os.environ["DATABASE_URL"]
    repo = await open_storage(url, bot_id)
    h = Harness(
        repo, config(oge_companion_adaptive_enabled=True), ScenarioPostgresRepository(repo._pool)
    )
    try:
        await h.message("/start")
        await h.click("exit")
        await h.message("№6 · Вычисления")
        ordinary = await repo.task6_state(42)
        await h.message("7654321")
        await h.message("7654321")
        await h.message("/start")
        await h.click("nav:adaptive")
        session = Session(repo, 42)
        row = await session.current()
        assert row and row["problem"] and row["position"] == 0
        first = row["problem"]
        await h.click(f"ad:menu:{first}")
        await h.click("nav:adaptive")
        assert (await session.current())["problem"] == first
        await h.message(json.loads(row["snapshot"])["correct_answer"])
        assert (await session.current())["outcome"] == "solved"
        previous = await h.click(f"ad:next:{first}")
        await h.click(saved=previous)
        assert (await session.current())["position"] == 1
        assert (await repo.task6_state(42))["problem"] == ordinary["problem"]
        await h.message("/start")
        await h.message("/progress")
        await h.click("nav:gaps:0")
        assert any(
            "Последние свидетельства" in (m.text or "") for m in h.transport.messages.values()
        )
        assert await bank_pool.fetchval("SELECT count(*) FROM adaptive_sessions") == 0
    finally:
        await h.bot.session.close()
        await repo._pool.close()
        conn = await asyncpg.connect(url)
        await conn.execute(f'DROP SCHEMA "{repo.schema}" CASCADE')
        await conn.close()
        get_settings.cache_clear()


async def test_backfilled_ordinary_and_mixed_delayed_checks(bank_pool):
    from datetime import timedelta

    from app.adaptive.store import overview, sync
    from app.persistence.repository import PostgresRepository

    t = datetime(2026, 1, 1, tzinfo=UTC)
    family = "OGE09-L1"
    owner = await bank_pool.fetchval("SELECT id FROM users WHERE telegram_user_id=1")
    mix = await bank_pool.fetchval(
        "INSERT INTO mixed_training_sessions(user_id,state) VALUES($1,'{}') RETURNING id", owner
    )
    async with bank_pool.acquire() as conn, conn.transaction():
        for ix, (channel, day, passes) in enumerate(
            [
                ("ordinary", 0, False),
                ("mixed", 1, False),
                ("ordinary", 1, True),
                ("mixed", 2, True),
                ("ordinary", 3, True),
                ("mixed", 7, True),
                ("ordinary", 12, True),
            ]
        ):
            at = t + timedelta(days=day, seconds=ix)
            pid = uuid4()
            if channel == "mixed":
                await conn.execute(
                    """INSERT INTO mixed_training_problems(id,session_id,number,
                    family_id,fingerprint,snapshot,snapshot_sha256,issued_at)
                    VALUES($1,$2,9,$3,$4,'{}',repeat('0',64),$5)""",
                    pid,
                    mix,
                    family,
                    str(ix),
                    at,
                )
                await conn.execute(
                    """INSERT INTO mixed_training_attempts(problem_id,attempt_no,
                    telegram_message_id,raw_answer,is_correct,created_at)
                    VALUES($1,1,$2,'0',$3,$4)""",
                    pid,
                    ix + 1,
                    passes,
                    at,
                )
            else:
                await conn.execute(
                    """INSERT INTO issued_problems(id,user_id,family_id,fingerprint,
                    generator_version,snapshot,issued_at) VALUES($1,$2,$3,$4,'v','{}',$5)""",
                    pid,
                    owner,
                    family,
                    str(ix),
                    at,
                )
                await conn.execute(
                    """INSERT INTO attempts(problem_id,user_id,attempt_no,
                    telegram_message_id,raw_answer,is_correct,created_at)
                    VALUES($1,$2,1,$3,'0',$4,$5)""",
                    pid,
                    owner,
                    ix + 1,
                    passes,
                    at,
                )
        await sync(conn, owner, rebuild=True)
    history = await overview(PostgresRepository(bank_pool), 1)
    assert history[0][2].closed == 1 and history[0][2].stage == Stage.CONFIRMED
    assert (
        await bank_pool.fetchval(
            """SELECT source FROM adaptive_evidence WHERE reason='check_passed'
        AND owner=$1""",
            owner,
        )
        == "mixed"
    )


def test_fixed_bank_and_unavailable_family_fail_closed():
    from app.bot.adaptive import generate

    assert generate("unsupported", []) is None
    f = "FLAT-03-RECT-AREA"
    first = generate(f, [])
    assert first and not generate(f, [first["fingerprint"]])
    assert trajectory(ev(1, 0, "ambiguous"), ev(1, 0, "ambiguous", 2)).stage == Stage.CHECK
