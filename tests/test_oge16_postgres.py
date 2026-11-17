"""Real PostgreSQL 17 lifecycle, snapshot recovery, and transactional races."""

import asyncio
import os
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest

from app.math.oge16_circles import FAMILIES, from_snapshot
from app.math.oge16_scheduler import build_task16_candidate_batch
from app.persistence.repository import PostgresRepository


@pytest.mark.parametrize("family", FAMILIES)
async def test_task16_postgres_restore_duplicate_race_skip_and_restart(family):
    url = os.getenv("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not configured; PostgreSQL 17 runs in CI")
    pool = await asyncpg.create_pool(url)
    user_id = uuid4().int % (2**62)
    try:
        assert str(await pool.fetchval("SHOW server_version")).startswith("17.")
        for migration in sorted(Path("migrations").glob("*.sql")):
            await pool.execute(migration.read_text())
        await pool.execute(Path("migrations/0017_task16_sessions.sql").read_text())
        repo = PostgresRepository(pool)
        sessions = await asyncio.gather(*(repo.ensure_task16_session(user_id) for _ in range(2)))
        assert sessions[0] == sessions[1]
        candidate = build_task16_candidate_batch({}, 42, enabled_families=(family,))[0]
        issued = await repo.advance_task16_problem(user_id, None, [candidate])
        pid = issued["problem_id"]
        await repo.save_user_state(user_id, "task16")
        assert await repo.set_task16_condition_message(user_id, pid, 100)
        assert await repo.task16_hint(user_id, pid, 100)
        restarted = PostgresRepository(pool)
        restored = await restarted.task16_state(user_id)
        assert restored["state"]["hints_used"] == 1
        assert from_snapshot(restored["problem"]).png == from_snapshot(candidate).png
        assert await restarted.last_training_mode(user_id) == "task16"
        wrong = await restarted.task16_attempt(user_id, pid, "0", False, 101, 100)
        assert wrong["status"] == "active"
        duplicate = await restarted.task16_attempt(user_id, pid, "0", False, 101, 100)
        assert duplicate["status"] == "duplicate"
        results = await asyncio.gather(
            *(
                restarted.task16_attempt(user_id, pid, issued["correct_answer"], True, mid, 100)
                for mid in (102, 103)
            )
        )
        assert sum(r is not None and r.get("attempt") == 2 for r in results) == 1
        assert (await restarted.task16_progress(user_id))["attempts"] == 2
        next_candidates = build_task16_candidate_batch(
            {"recent_fingerprints": [issued["fingerprint"]]}, 43, enabled_families=FAMILIES
        )
        results = await asyncio.gather(
            *(
                restarted.advance_task16_problem(user_id, pid, next_candidates, "task16", 100)
                for _ in range(2)
            )
        )
        assert sum(r.get("_transitioned") is True for r in results) == 1
        current = await restarted.task16_state(user_id)
        new_pid = current["problem"]["problem_id"]
        assert await restarted.set_task16_condition_message(user_id, new_pid, 200)
        assert await restarted.task16_hint(user_id, pid, 100) is None
        recent = current["state"]["recent_fingerprints"]
        candidates = build_task16_candidate_batch(
            {"recent_fingerprints": recent}, 44, enabled_families=FAMILIES
        )
        results = await asyncio.gather(
            restarted.task16_attempt(user_id, new_pid, "0", False, 201, 200),
            restarted.advance_task16_problem(user_id, new_pid, candidates, "task16", 200, True),
        )
        assert results[1]["_transitioned"] is True
        assert (await restarted.task16_progress(user_id))["skipped"] == 1
        current = await restarted.task16_state(user_id)
        final_pid = current["problem"]["problem_id"]
        await restarted.set_task16_condition_message(user_id, final_pid, 300)
        assert await restarted.transition_task_screen(
            user_id, "task16", final_pid, "main_menu", 300
        )
        assert await restarted.open_training_screen(user_id, "main_menu", "task16", final_pid)
        await restarted.save_user_state(user_id, "number_selection")
        previous = await restarted.prepare_training_restart(
            user_id, "task16", final_pid, "number_selection"
        )
        assert previous == "active"
        await restarted.restore_training_restart(user_id, "task16", final_pid, previous)
        assert (await restarted.task16_state(user_id))["state"]["status"] == "active"
    finally:
        await pool.execute("DELETE FROM users WHERE telegram_user_id=$1", user_id)
        await pool.close()


async def test_task16_postgres_finite_cycle_is_persisted_across_restart():
    import json

    from app.math.oge16_scheduler import finite_pool

    url = os.getenv("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not configured")
    pool = await asyncpg.create_pool(url)
    user_id = uuid4().int % (2**62)
    try:
        for migration in sorted(Path("migrations").glob("*.sql")):
            await pool.execute(migration.read_text())
        repo = PostgresRepository(pool)
        sid = await repo.ensure_task16_session(user_id)
        recent = [fp for fp, _ in finite_pool("OGE16-C03")]
        await pool.execute(
            "UPDATE sessions SET state=$2::jsonb WHERE id=$1::uuid",
            sid,
            json.dumps({"recent_fingerprints": recent}),
        )
        batch = build_task16_candidate_batch(
            {"recent_fingerprints": recent}, 23, enabled_families=("OGE16-C03",)
        )
        issued = await repo.advance_task16_problem(user_id, None, batch)
        restarted = PostgresRepository(pool)
        state = await restarted.task16_state(user_id)
        assert state["state"]["recent_fingerprints"] == [issued["fingerprint"]]
        assert "_finite_cycle_fingerprints" not in state["problem"]
        assert (await restarted.task16_progress(user_id))["issued"] == 1
        assert from_snapshot(state["problem"]).png == from_snapshot(issued).png
    finally:
        await pool.execute("DELETE FROM users WHERE telegram_user_id=$1", user_id)
        await pool.close()
