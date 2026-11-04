from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg
import pytest

from app.math.oge07_graph import generate_graph_problem
from app.math.oge07_scheduler import build_task7_candidate_batch
from app.persistence.image_retention import restore_graphic_snapshot
from app.persistence.repository import PostgresRepository, read_migration
from app.persistence.training_insights import training_insights
from scripts.compact_graphic_snapshots import compact_old_snapshots


@pytest.mark.asyncio
async def test_postgres_retention_keeps_recent_and_active_png_and_preserves_history() -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL not configured")

    pool = await asyncpg.create_pool(database_url)
    user_id = int(uuid4().int % (2**62)) + 1
    try:
        for migration in sorted(Path("migrations").glob("*.sql")):
            await pool.execute(await read_migration(str(migration)))
        repository = PostgresRepository(pool)
        await repository.ensure_task7_session(user_id)
        async with pool.acquire() as connection:
            user = await connection.fetchrow(
                "SELECT id FROM users WHERE telegram_user_id=$1", user_id
            )
            session = await connection.fetchrow(
                "SELECT id FROM sessions WHERE user_id=$1 AND mode='task7'", user["id"]
            )
            assert user is not None and session is not None
            old_session_id = await connection.fetchval(
                """INSERT INTO sessions(user_id, mode, state, finished_at)
                   VALUES ($1, 'task7', '{}'::jsonb, now()) RETURNING id""",
                user["id"],
            )

            problem_ids: list[UUID] = []
            snapshots: list[dict[str, object]] = []
            for index in range(101):
                snapshot = generate_graph_problem("OGE07-N01", 770_000 + index).to_snapshot()
                snapshot.update(
                    {
                        "selection_attempts": index + 1,
                        "_family_queue_after": [],
                        "_last_family_after": "OGE07-N01",
                    }
                )
                snapshots.append(snapshot)
                problem_id = UUID(str(snapshot["problem_id"]))
                problem_ids.append(problem_id)
                await connection.execute(
                    """INSERT INTO issued_problems
                       (id, user_id, session_id, family_id, generator_version, seed,
                        fingerprint, shape_fingerprint, snapshot, outcome, issued_at)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$7,$8::jsonb,'skipped',
                               TIMESTAMPTZ '2000-01-01 00:00:00+00' + $9 * INTERVAL '1 second')""",
                    problem_id,
                    user["id"],
                    old_session_id,
                    snapshot["family_id"],
                    snapshot["generator_version"],
                    snapshot["seed"],
                    snapshot["fingerprint"],
                    json.dumps(snapshot),
                    index,
                )

        active_candidate = build_task7_candidate_batch(
            {}, 770_200, family_ids=("OGE07-N01",)
        )[0]
        active = await repository.advance_task7_problem(user_id, None, [active_candidate])
        active_id = UUID(str(active["problem_id"]))
        active_state_before = await repository.task7_state(user_id)
        progress_before = await repository.task7_progress(user_id)
        history_before = await repository.task7_history(user_id, limit=5)
        oldest_history_before = await training_insights(
            repository, user_id, "history:100", page_size=6
        )
        assert active_state_before is not None

        preview = await compact_old_snapshots(database_url, user_uuid=user["id"])
        assert preview["would_compact"] == 2
        assert preview["compacted"] == 0

        result = await compact_old_snapshots(
            database_url,
            keep_full_per_user=100,
            apply=True,
            user_uuid=user["id"],
        )
        assert result["compacted"] == 2, result

        async with pool.acquire() as connection:
            rows = await connection.fetch(
                """SELECT p.id, p.snapshot, p.outcome, s.active_problem_id
                   FROM issued_problems p LEFT JOIN sessions s ON s.id=p.session_id
                   WHERE p.user_id=$1 ORDER BY p.issued_at, p.id""",
                user["id"],
            )
        assert len(rows) == 102
        decoded = [
            (
                row,
                json.loads(row["snapshot"])
                if isinstance(row["snapshot"], str)
                else row["snapshot"],
            )
            for row in rows
        ]
        compacted_rows = [
            item for item in decoded if "graph_png_base64" not in item[1]
        ]
        assert [item[0]["id"] for item in compacted_rows] == problem_ids[:2]
        active_row = next(item for item in decoded if item[0]["id"] == active_id)
        assert active_row[0]["outcome"] == "issued"
        assert "graph_png_base64" in active_row[1]
        assert restore_graphic_snapshot(compacted_rows[0][1]) == json.loads(
            json.dumps(snapshots[0])
        )
        assert restore_graphic_snapshot(compacted_rows[1][1]) == json.loads(
            json.dumps(snapshots[1])
        )
        oldest_history_after = await training_insights(
            repository, user_id, "history:100", page_size=6
        )
        assert oldest_history_after == oldest_history_before
        assert {row["id"] for row in oldest_history_after["history"]} == set(problem_ids[:2])

        active_state_after = await repository.task7_state(user_id)
        assert active_state_after == active_state_before
        assert await repository.task7_progress(user_id) == progress_before
        assert await repository.task7_history(user_id, limit=5) == history_before
    finally:
        await pool.execute("DELETE FROM users WHERE telegram_user_id=$1", user_id)
        await pool.close()
