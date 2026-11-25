import asyncio
import json
from uuid import UUID, uuid4

import pytest


def candidate(family: str, fingerprint: str) -> dict[str, object]:
    return {
        "problem_id": str(uuid4()),
        "family_id": family,
        "generator_version": "test-v1",
        "fingerprint": fingerprint,
        "correct_answer": "1",
        "hints": ["hint"],
        "solution": ["solution"],
    }


async def test_strategy_validation_and_cold_start(bank_pool):
    from app.adaptive.session import Session
    from app.persistence.repository import PostgresRepository

    session = Session(PostgresRepository(bank_pool), 1)
    with pytest.raises(ValueError):
        await session.start(["f"] * 4)
    with pytest.raises(ValueError):
        await session.start(["f"] * 5, strategy="number")
    await session.start([f"f{i}" for i in range(5)], strategy="personal", scope={"reasons": []})
    row = await session.current()
    assert row["strategy"] == "personal" and row["revision"] == 0


async def test_similar_uses_next_slot_and_revision_is_callback_safe(bank_pool):
    from app.adaptive.session import Session
    from app.persistence.repository import PostgresRepository

    family = "OGE09-L1"
    session = Session(PostgresRepository(bank_pool), 1)
    await session.start([family, "other-1", "other-2", "other-3", "other-4"])
    row = await session.current()
    first = candidate(family, "fresh-a")
    assert await session.save(row, family, first)
    row = await session.current()
    assert await session.act(
        row["problem"], None, "answer", raw="0", correct=False, message_id=11,
        session_id=row["id"], position=0, revision=0,
    ) == "issued"
    assert await session.act(
        row["problem"], None, "answer", raw="0", correct=False, message_id=12,
        session_id=row["id"], position=0, revision=0,
    ) == "failed"
    assert await bank_pool.fetchval(
        "SELECT solution_viewed_at IS NOT NULL FROM issued_problems WHERE id=$1", row["problem"]
    )
    results = await asyncio.gather(*[
        session.choose_similar(row["id"], 0, row["problem"], revision=0) for _ in range(2)
    ])
    assert sorted(results) == ["next", "stale"]
    next_row = await session.current()
    assert next_row["position"] == 1 and next_row["revision"] == 1
    second = candidate(family, "fresh-b")
    assert await session.save(next_row, family, second)
    slot = await bank_pool.fetchrow(
        "SELECT position,selection FROM adaptive_slots WHERE problem=$1",
        UUID(str(second["problem_id"])),
    )
    assert tuple(slot) == (1, "similar")
    from app.adaptive.store import sync
    async with bank_pool.acquire() as conn, conn.transaction():
        await sync(conn, next_row["owner"])
    assert set(await session.seen(next_row["owner"], family)) == {"fresh-a", "fresh-b"}


async def test_finish_is_idempotent_and_summary_deltas_are_persisted(bank_pool):
    from app.adaptive.session import Session
    from app.persistence.repository import PostgresRepository

    family = "OGE09-L1"
    session = Session(PostgresRepository(bank_pool), 1)
    await session.start([family] * 5, strategy="family", scope={"family": family})
    row = await session.current()
    item = candidate(family, "only")
    assert await session.save(row, family, item)
    row = await session.current()
    assert await session.act(
        row["problem"], None, "solution", session_id=row["id"], position=0, revision=0
    ) == "solution"
    assert await session.act(
        row["problem"], None, "finish", session_id=row["id"], position=0, revision=0
    ) == "finished"
    assert await session.act(
        row["problem"], None, "finish", session_id=row["id"], position=0, revision=0
    ) == "stale"
    totals = await session.totals(row["id"])
    assert dict(totals) == {
        "issued": 1,
        "completed": 1,
        "attempted": 0,
        "solved": 0,
        "hinted": 0,
        "reviewed": 1,
        "independent": 0,
        "fresh": 1,
    }
    first = await session.summary_deltas(row["id"])
    second = await session.summary_deltas(row["id"])
    assert [dict(value) for value in first] == [dict(value) for value in second]
    assert await bank_pool.fetchval(
        "SELECT count(*) FROM adaptive_session_deltas WHERE session_id=$1", row["id"]
    ) == len(first)


async def test_exhausted_similar_does_not_consume_a_position(bank_pool):
    from app.adaptive.session import Session
    from app.persistence.repository import PostgresRepository

    family = "OGE09-L1"
    session = Session(PostgresRepository(bank_pool), 1)
    await session.start([family, "next-family", "a", "b", "c"])
    row = await session.current()
    assert await session.save(row, family, candidate(family, "fresh-a"))
    row = await session.current()
    assert await session.act(row["problem"], None, "skip") == "skip"
    assert await session.choose_similar(row["id"], 0, row["problem"], revision=0) == "next"
    assert await session.cancel_similar(row["id"], 1, revision=1) == "exhausted"
    restored = await session.current()
    assert restored["position"] == 0 and restored["problem"] == row["problem"]
    assert restored["revision"] == 2
    assert __import__("json").loads(restored["plan"])[1] == "next-family"


async def test_summary_keeps_position_delta_when_same_family_changes_elsewhere(bank_pool):
    """A later ordinary event must not become the personal session's reported change."""
    from app.adaptive.session import Session
    from app.adaptive.store import sync
    from app.persistence.repository import PostgresRepository

    family = "OGE09-L1"
    session = Session(PostgresRepository(bank_pool), 1)
    await session.start([family] * 5)
    row = await session.current()
    assert await session.save(row, family, candidate(family, "personal"))
    row = await session.current()
    assert await session.act(row["problem"], None, "answer", raw="0", message_id=1) == "issued"
    assert await session.act(row["problem"], None, "finish") == "finished"
    external = candidate(family, "external")
    await bank_pool.execute(
        """INSERT INTO issued_problems(id,user_id,family_id,generator_version,
        fingerprint,snapshot,outcome) VALUES($1,$2,$3,'test',$4,'{}','solved')""",
        UUID(str(external["problem_id"])), row["owner"], family, external["fingerprint"],
    )
    async with bank_pool.acquire() as conn, conn.transaction():
        await conn.execute("SET LOCAL bop.adaptive='on'")
        await conn.execute(
            """INSERT INTO attempts(user_id,problem_id,attempt_no,raw_answer,is_correct,
            telegram_message_id) VALUES($1,$2,1,'1',true,99)""",
            row["owner"], UUID(str(external["problem_id"])),
        )
        await sync(conn, row["owner"], rebuild=True)
    deltas = await session.summary_deltas(row["id"])
    assert deltas
    current = await bank_pool.fetchval(
        "SELECT state FROM adaptive_skills WHERE owner=$1 AND skill=$2", row["owner"], family
    )
    current = json.loads(current) if isinstance(current, str) else current
    personal_after = deltas[-1]["after_state"]
    if isinstance(personal_after, str):
        personal_after = json.loads(personal_after)
    assert personal_after != {key: current[key] for key in personal_after}


async def test_save_rechecks_freshness_across_mixed_history(bank_pool):
    from app.adaptive.session import Session
    from app.persistence.repository import PostgresRepository

    family, fingerprint = "OGE09-L1", "already-in-mixed"
    owner = await bank_pool.fetchval("SELECT id FROM users WHERE telegram_user_id=1")
    mixed = await bank_pool.fetchval(
        "INSERT INTO mixed_training_sessions(user_id,state) VALUES($1,'{}') RETURNING id", owner
    )
    await bank_pool.execute(
        """INSERT INTO mixed_training_problems(id,session_id,number,family_id,fingerprint,
        snapshot,snapshot_sha256) VALUES($1,$2,9,$3,$4,'{}',$5)""",
        uuid4(), mixed, family, fingerprint, "0" * 64,
    )
    session = Session(PostgresRepository(bank_pool), 1)
    await session.start([family] * 5)
    row = await session.current()
    assert not await session.save(row, family, candidate(family, fingerprint))
    assert (await session.current())["problem"] is None


async def test_similar_and_next_have_one_revision_winner(bank_pool):
    from app.adaptive.session import Session
    from app.persistence.repository import PostgresRepository

    family = "OGE09-L1"
    session = Session(PostgresRepository(bank_pool), 1)
    await session.start([family, "original-next", "a", "b", "c"])
    row = await session.current()
    assert await session.save(row, family, candidate(family, "race"))
    row = await session.current()
    assert await session.act(row["problem"], None, "skip", revision=0) == "skip"
    results = await asyncio.gather(
        session.choose_similar(row["id"], 0, row["problem"], revision=0),
        session.act(
            row["problem"], None, "next", session_id=row["id"], position=0, revision=0
        ),
    )
    assert results.count("stale") == 1 and results.count("next") == 1
    current = await session.current()
    assert current["position"] == 1 and current["revision"] == 1


async def test_personal_toggle_invalidates_old_session_actions(bank_pool):
    from app.adaptive.session import Session
    from app.persistence.repository import PostgresRepository

    repo = PostgresRepository(bank_pool)
    session = Session(repo, 1)
    await session.start(["OGE09-L1"] * 5)
    row = await session.current()
    assert await session.save(row, "OGE09-L1", candidate("OGE09-L1", "toggle"))
    row = await session.current()
    await repo.set_personal_enabled(1, False)
    assert await session.act(row["problem"], None, "skip", revision=0) == "stale"
    assert (await session.current())["outcome"] == "issued"


async def test_router_resumes_short_session_after_repository_restart(bank_pool, monkeypatch):
    from unittest.mock import AsyncMock

    from app.adaptive.session import Session
    from app.bot import adaptive, router
    from app.config import get_settings
    from app.persistence.repository import PostgresRepository

    monkeypatch.setenv("OGE_ADAPTIVE_ENABLED", "true")
    get_settings.cache_clear()
    try:
        repo = PostgresRepository(bank_pool)
        await repo.save_user_state(1, "task9")
        session = Session(repo, 1)
        await session.start(["OGE09-L1"] * 5)
        row = await session.current()
        assert row and await repo.last_training_mode(1) == "adaptive"
        restarted = PostgresRepository(bank_pool)
        assert await router._has_resumable_session(restarted, 1)
        rendered = AsyncMock()
        monkeypatch.setattr(adaptive, "present", rendered)
        message = AsyncMock()
        message.from_user.id = 1
        await router.continue_session(message, restarted)
        rendered.assert_awaited_once_with(message, restarted, 1)
        assert (await Session(restarted, 1).current())["id"] == row["id"]
        assert await restarted.user_state(1) == "adaptive"
    finally:
        get_settings.cache_clear()


async def test_finished_short_session_restores_last_ordinary_resume(bank_pool):
    from app.adaptive.session import Session
    from app.persistence.repository import PostgresRepository

    repo = PostgresRepository(bank_pool)
    await repo.save_user_state(1, "task9")
    session = Session(repo, 1)
    await session.start(["OGE09-L1"] * 5)
    row = await session.current()
    assert await session.act(None, None, "finish", session_id=row["id"], position=0) == "finished"
    assert await repo.last_training_mode(1) == "task9"


@pytest.mark.parametrize("action", ["skip", "solution"])
async def test_fifth_terminal_action_finishes_atomically(bank_pool, action):
    from app.adaptive.session import Session
    from app.persistence.repository import PostgresRepository

    session = Session(PostgresRepository(bank_pool), 1)
    family = "OGE09-L1"
    await session.start([family] * 5)
    for position in range(5):
        row = await session.current()
        assert await session.save(row, family, candidate(family, f"terminal-{position}"))
        row = await session.current()
        result = await session.act(row["problem"], None, action, revision=position)
        if position < 4:
            assert result == action
            assert await session.act(row["problem"], None, "next", revision=position) == "next"
        else:
            assert result == f"completed_{action}"
    assert await session.current() is None
