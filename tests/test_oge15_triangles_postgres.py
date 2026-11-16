"""Real PostgreSQL 17 lifecycle, snapshot recovery, and transactional races."""

import asyncio
import os
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest

from app.math.oge15_scheduler import build_task15_candidate_batch
from app.math.oge15_triangles import FAMILIES, from_snapshot
from app.persistence.repository import PostgresRepository


@pytest.mark.parametrize("family", FAMILIES)
async def test_task15_postgres_restore_duplicate_race_skip_and_restart(family):
    url = os.getenv("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not configured; PostgreSQL 17 runs in CI")
    pool = await asyncpg.create_pool(url)
    user_id = uuid4().int % (2**62)
    try:
        assert str(await pool.fetchval("SHOW server_version")).startswith("17.")
        for migration in sorted(Path("migrations").glob("*.sql")):
            await pool.execute(migration.read_text())
        await pool.execute(Path("migrations/0015_task15_sessions.sql").read_text())
        repo = PostgresRepository(pool)
        sessions = await asyncio.gather(*(repo.ensure_task15_session(user_id) for _ in range(2)))
        assert sessions[0] == sessions[1]
        candidate = build_task15_candidate_batch({}, 42, enabled_families=(family,))[0]
        issued = await repo.advance_task15_problem(user_id, None, [candidate])
        pid = issued["problem_id"]
        await repo.save_user_state(user_id, "task15")
        assert await repo.set_task15_condition_message(user_id, pid, 100)
        assert await repo.task15_hint(user_id, pid, 100)
        restarted = PostgresRepository(pool)
        restored = await restarted.task15_state(user_id)
        assert restored["state"]["hints_used"] == 1
        assert from_snapshot(restored["problem"]) == from_snapshot(candidate)
        assert await restarted.last_training_mode(user_id) == "task15"
        wrong = await restarted.task15_attempt(user_id, pid, "0", False, 101, 100)
        assert wrong["status"] == "active"
        duplicate = await restarted.task15_attempt(user_id, pid, "0", False, 101, 100)
        assert duplicate["status"] == "duplicate"
        results = await asyncio.gather(
            *(
                restarted.task15_attempt(user_id, pid, issued["correct_answer"], True, mid, 100)
                for mid in (102, 103)
            )
        )
        assert sum(r is not None and r.get("attempt") == 2 for r in results) == 1
        assert (await restarted.task15_progress(user_id))["attempts"] == 2
        next_candidates = build_task15_candidate_batch(
            {"recent_fingerprints": [issued["fingerprint"]]}, 43, enabled_families=FAMILIES
        )
        results = await asyncio.gather(
            *(
                restarted.advance_task15_problem(user_id, pid, next_candidates, "task15", 100)
                for _ in range(2)
            )
        )
        assert sum(r.get("_transitioned") is True for r in results) == 1
        current = await restarted.task15_state(user_id)
        new_pid = current["problem"]["problem_id"]
        assert await restarted.set_task15_condition_message(user_id, new_pid, 200)
        assert await restarted.task15_hint(user_id, pid, 100) is None
        recent = current["state"]["recent_fingerprints"]
        candidates = build_task15_candidate_batch(
            {"recent_fingerprints": recent}, 44, enabled_families=FAMILIES
        )
        results = await asyncio.gather(
            restarted.task15_attempt(user_id, new_pid, "0", False, 201, 200),
            restarted.advance_task15_problem(user_id, new_pid, candidates, "task15", 200, True),
        )
        assert results[1]["_transitioned"] is True
        assert (await restarted.task15_progress(user_id))["skipped"] == 1
        current = await restarted.task15_state(user_id)
        final_pid = current["problem"]["problem_id"]
        await restarted.set_task15_condition_message(user_id, final_pid, 300)
        assert await restarted.transition_task_screen(
            user_id, "task15", final_pid, "main_menu", 300
        )
        assert await restarted.open_training_screen(user_id, "main_menu", "task15", final_pid)
        await restarted.save_user_state(user_id, "number_selection")
        previous = await restarted.prepare_training_restart(
            user_id, "task15", final_pid, "number_selection"
        )
        assert previous == "active"
        await restarted.restore_training_restart(user_id, "task15", final_pid, previous)
        assert (await restarted.task15_state(user_id))["state"]["status"] == "active"
        # Solution callbacks outside the training screen must fail closed.
        assert await restarted.task15_reveal_solution(user_id, final_pid, 300) is None
        assert await restarted.open_training_screen(user_id, "number_selection", "task15", final_pid)
        assert await restarted.task15_reveal_solution(user_id, final_pid, 300)
        assert (await restarted.task15_progress(user_id))["solutions_viewed"] == 1
    finally:
        await pool.execute("DELETE FROM users WHERE telegram_user_id=$1", user_id)
        await pool.close()
