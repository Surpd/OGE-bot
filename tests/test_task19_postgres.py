"""Task 19 end-to-end persistence coverage against the CI PostgreSQL service."""

from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import asyncpg
import pytest
from aiogram.types import User

from app.bot import router
from app.main import _run_schema_migrations
from app.math import oge19_scheduler
from app.math.oge19_scheduler import FAMILY_THEMES
from app.persistence.repository import PostgresRepository


def incoming(text: str = "", message_id: int = 100, user_id: int = 190019):
    message = AsyncMock()
    message.from_user = User(id=user_id, is_bot=False, first_name="Postgres Student")
    message.message_id = message_id
    message.text = text
    message.reply_to_message = None
    message.answer.return_value.message_id = message_id + 1
    return message


def callback(action: str, problem_id: str, message_id: int, user_id: int = 190019):
    result = AsyncMock()
    result.data = f"t19:{action}:{problem_id}"
    result.from_user = User(id=user_id, is_bot=False, first_name="Postgres Student")
    result.message = AsyncMock()
    result.message.message_id = message_id
    return result


@pytest.mark.asyncio
async def test_task19_postgres_flow_survives_repository_restart_and_is_isolated(monkeypatch):
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL not configured")

    monkeypatch.setattr(oge19_scheduler, "ENABLED_FAMILIES", tuple(FAMILY_THEMES))
    admin = await asyncpg.connect(database_url)
    database_name = f"oge19_e2e_{uuid4().hex}"
    await admin.execute(f'CREATE DATABASE "{database_name}"')
    parsed = urlsplit(database_url)
    test_url = urlunsplit(
        (parsed.scheme, parsed.netloc, f"/{database_name}", parsed.query, parsed.fragment)
    )
    pool: asyncpg.Pool | None = None
    try:
        pool = await asyncpg.create_pool(test_url)
        await _run_schema_migrations(pool)
        repo = PostgresRepository(pool)
        user_id = 190019
        await repo.register_user(user_id)
        await repo.set_training_family(user_id, 19, "OGE19-MIXED")
        database_user_id = await pool.fetchval(
            "SELECT id FROM users WHERE telegram_user_id=$1", user_id
        )

        # Seed solved work for adjacent numbers. Task 19 progress must not count
        # or mutate any of these sessions or their issued rows.
        sibling_sessions: dict[str, tuple[str, str]] = {}
        for number in range(15, 19):
            mode = f"task{number}"
            sentinel = {"sentinel": f"preserve-{mode}"}
            session_id = await pool.fetchval(
                "INSERT INTO sessions (user_id, mode, state) VALUES ($1,$2,$3::jsonb) "
                "RETURNING id",
                database_user_id,
                mode,
                json.dumps(sentinel),
            )
            problem_id = uuid4()
            await pool.execute(
                """INSERT INTO issued_problems
                   (id,user_id,session_id,family_id,generator_version,seed,fingerprint,
                    shape_fingerprint,snapshot,outcome)
                   VALUES ($1,$2,$3,$4,'fixture',1,$5,$5,'{}'::jsonb,'solved')""",
                problem_id,
                database_user_id,
                session_id,
                mode,
                f"sibling-{mode}",
            )
            sibling_sessions[mode] = (str(session_id), str(problem_id))

        # Issue a real task through the shared Telegram engine and persist its
        # exact signed snapshot in PostgreSQL.
        await router.choose_task19(incoming(), repo)
        issued = await repo.task19_state(user_id)
        assert issued is not None
        first_problem = issued["problem"]
        first_id = str(first_problem["problem_id"])
        original_condition = first_problem["condition"]
        original_statements = [item["statement"] for item in first_problem["statements"]]
        prompt_id = issued["state"]["problem_prompt_message_id"]
        assert await pool.fetchval(
            "SELECT count(*) FROM issued_problems p JOIN sessions s ON s.id=p.session_id "
            "WHERE s.mode='task19' AND p.id=$1::uuid",
            first_id,
        ) == 1

        # Simulate a bot/repository restart by closing the first pool and
        # restoring state through a new repository instance.
        await pool.close()
        pool = await asyncpg.create_pool(test_url)
        repo = PostgresRepository(pool)
        restored = await repo.task19_state(user_id)
        assert restored is not None
        assert restored["problem"]["condition"] == original_condition
        restored_statements = [item["statement"] for item in restored["problem"]["statements"]]
        assert restored_statements == original_statements
        assert await repo.training_family(user_id, 19) == "OGE19-MIXED"

        hint_callback = callback("hint", first_id, prompt_id)
        await router.task19_callback(hint_callback, repo)
        hint = hint_callback.message.answer.await_args.args[0]
        assert first_problem["correct_answer"] not in hint
        assert (await repo.task19_state(user_id))["state"]["attempts"] == 0

        wrong = "1" if first_problem["correct_answer"] != "1" else "2"
        first_attempt = incoming(wrong, prompt_id + 1)
        await router.task19_answer(first_attempt, repo)
        await router.task19_answer(first_attempt, repo)  # duplicate webhook delivery
        after_duplicate = await repo.task19_state(user_id)
        assert after_duplicate["state"]["attempts"] == 1
        assert await pool.fetchval(
            "SELECT count(*) FROM attempts WHERE problem_id=$1::uuid", first_id
        ) == 1

        # Resume the active problem after repository recreation and finish on
        # the second try. The history and counters must survive both operations.
        await repo.save_user_state(user_id, "number_selection")
        resumed_message = incoming(message_id=prompt_id + 10)
        await router.continue_session(resumed_message, repo)
        resumed = await repo.task19_state(user_id)
        assert resumed["problem"]["problem_id"] == first_id
        assert resumed["problem"]["condition"] == original_condition
        assert resumed["state"]["attempts"] == 1

        next_prompt_id = resumed["state"]["problem_prompt_message_id"]
        await router.task19_answer(
            incoming(str(first_problem["correct_answer"]), next_prompt_id + 1), repo
        )
        solved = await repo.task19_state(user_id)
        assert solved["state"]["status"] == "solved"
        assert solved["state"]["attempts"] == 2
        assert solved["state"]["used_hint"] is True

        await repo.save_user_state(user_id, "number_selection")
        await router.saved_training_navigation(
            incoming(message_id=next_prompt_id + 20),
            repo,
            user_id,
            "confirm",
            19,
            first_id,
        )
        restarted = await repo.task19_state(user_id)
        assert restarted["problem"]["problem_id"] != first_id
        assert restarted["state"]["attempts"] == 0
        restart_prompt_id = restarted["state"]["problem_prompt_message_id"]
        await router.task19_callback(
            callback("skip", str(restarted["problem"]["problem_id"]), restart_prompt_id), repo
        )
        after_skip = await repo.task19_state(user_id)
        assert after_skip["problem"]["problem_id"] != restarted["problem"]["problem_id"]
        recent_ids = after_skip["state"]["recent_proposition_ids"]
        assert set(item["proposition_id"] for item in first_problem["statements"]) <= set(
            recent_ids
        )
        assert len(recent_ids) <= 30

        progress = await repo.task19_progress(user_id)
        assert progress["issued"] == 3
        assert progress["correct"] == 1
        assert progress["solved_second_try"] == 1
        assert progress["attempts"] == 2
        assert progress["hints_used"] == 1
        assert progress["skipped"] == 1

        sibling_rows = await pool.fetch(
            """SELECT s.mode, s.id::text AS session_id, s.state, p.id::text AS problem_id,
                      p.outcome
               FROM sessions s JOIN issued_problems p ON p.session_id=s.id
               WHERE s.user_id=$1 AND s.mode BETWEEN 'task15' AND 'task18'
               ORDER BY s.mode""",
            database_user_id,
        )
        assert len(sibling_rows) == 4
        for row in sibling_rows:
            assert row["session_id"] == sibling_sessions[row["mode"]][0]
            assert row["problem_id"] == sibling_sessions[row["mode"]][1]
            state = row["state"]
            if isinstance(state, str):
                state = json.loads(state)
            assert state == {"sentinel": f"preserve-{row['mode']}"}
            assert row["outcome"] == "solved"
    finally:
        if pool is not None:
            await pool.close()
        await admin.execute(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)')
        await admin.close()
