import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import asyncpg
import pytest

from app.admin.repository import AdminRepository
from app.persistence.repository import read_migration


@pytest.mark.asyncio
async def test_admin_views_separate_adaptive_mixed_scenario_and_replay_sources() -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL not configured")

    admin = await asyncpg.connect(database_url)
    database_name = f"oge_admin_sources_{uuid4().hex}"
    await admin.execute(f'CREATE DATABASE "{database_name}"')
    parsed = urlsplit(database_url)
    test_url = urlunsplit(
        (parsed.scheme, parsed.netloc, f"/{database_name}", parsed.query, parsed.fragment)
    )
    source_schema = f"sources_{uuid4().hex}"
    setup = await asyncpg.connect(test_url)
    pool = None
    try:
        await setup.execute(f'CREATE SCHEMA "{source_schema}"')
        pool = await asyncpg.create_pool(
            test_url, server_settings={"search_path": f'"{source_schema}",public'}
        )
        for migration in sorted(Path("migrations").glob("*.sql")):
            await pool.execute(await read_migration(str(migration)))

        user_id = await pool.fetchval(
            "INSERT INTO users(telegram_user_id) VALUES(998877) RETURNING id"
        )
        ordinary_id = uuid4()
        await pool.execute(
            "INSERT INTO issued_problems(id,user_id,family_id,generator_version,fingerprint,"
            "snapshot) "
            "VALUES($1,$2,'OGE09-F001','1','ordinary-fingerprint','{}')",
            ordinary_id,
            user_id,
        )
        adaptive_id = await pool.fetchval(
            "INSERT INTO adaptive_sessions(owner,plan,strategy) "
            "VALUES($1,'{}','personal') RETURNING id",
            user_id,
        )
        await pool.execute(
            "INSERT INTO adaptive_slots(session_id,position,problem) VALUES($1,1,$2)",
            adaptive_id,
            ordinary_id,
        )
        await pool.execute(
            "INSERT INTO attempts(user_id,problem_id,attempt_no,raw_answer,is_correct,bot_id) "
            "VALUES($1,$2,1,'secret ordinary answer',true,0)",
            user_id,
            ordinary_id,
        )
        await pool.execute(
            "INSERT INTO adaptive_evidence(owner,skill,number,source,task,ordinal,variant,"
            "occurred,outcome,attempt) "
            "SELECT $1,'OGE09-F001',9,'personal',$2::uuid::text,0,'same-variant',"
            "issued_at,'issued',0 "
            "FROM issued_problems WHERE id=$2::uuid",
            user_id,
            ordinary_id,
        )

        mixed_session = await pool.fetchval(
            "INSERT INTO mixed_training_sessions(user_id,state) VALUES($1,'{}') RETURNING id",
            user_id,
        )
        mixed_id = uuid4()
        await pool.execute(
            "INSERT INTO mixed_training_problems(id,session_id,number,family_id,fingerprint,"
            "snapshot,snapshot_sha256) "
            "VALUES($1,$2,9,'OGE09-F002','mixed-fingerprint','{}',repeat('b',64))",
            mixed_id,
            mixed_session,
        )
        await pool.execute(
            "INSERT INTO mixed_training_attempts(problem_id,attempt_no,telegram_message_id,"
            "raw_answer,is_correct,bot_id) "
            "VALUES($1,1,81,'secret mixed answer',false,0)",
            mixed_id,
        )

        scene_id = await pool.fetchval(
            "INSERT INTO oge15_scenarios(user_id,story_code,seed,generator_version,"
            "snapshot_schema_version,snapshot,snapshot_sha256) "
            "VALUES($1,'TYRES',1,'1',1,$2,repeat('c',64)) RETURNING id",
            user_id,
            '{"questions":[{"family_id":"OGE15-F001"},{"family_id":"OGE15-F002"}]}',
        )
        scenario_session = await pool.fetchval(
            "INSERT INTO oge15_sessions(user_id,scenario_id,story_code,mode,current_position) "
            "VALUES($1,$2,'TYRES','single',1) RETURNING id",
            user_id,
            scene_id,
        )
        await pool.execute(
            "INSERT INTO oge15_question_progress(session_id,position,status) "
            "VALUES($1,1,'active'),($1,2,'pending')",
            scenario_session,
        )
        assert await pool.fetchval(
            "SELECT adaptive_issued_at IS NOT NULL FROM oge15_question_progress "
            "WHERE session_id=$1 AND position=1",
            scenario_session,
        )
        await pool.execute(
            "INSERT INTO oge15_attempts(session_id,position,attempt_no,telegram_message_id,"
            "raw_answer,is_correct,bot_id) "
            "VALUES($1,1,1,82,'secret scenario answer',true,0)",
            scenario_session,
        )

        replay_id = await pool.fetchval(
            "INSERT INTO training_error_replays(user_id,source_type,source_id,attempts,"
            "attempt_count) "
            "VALUES($1,'ordinary',$2,$3::jsonb,1) RETURNING id",
            user_id,
            ordinary_id,
            '[{"attempt_no":1,"message_id":83,"raw_answer":"private replay answer",'
            '"is_correct":false,"created_at":"2026-11-28T08:00:00+00:00"}]',
        )
        await pool.execute(
            "INSERT INTO telegram_updates(update_id,status) VALUES(444,'processed')"
        )

        analytics_schema = f"{source_schema}_admin"
        repository = AdminRepository(pool)
        async with repository.read() as conn:
                task_rows = await conn.fetch(
                    'SELECT source,mode,task_key FROM tasks ORDER BY source,mode'
                )
                assert [(row["source"], row["mode"]) for row in task_rows] == [
                    ("mixed", "unknown"),
                    ("ordinary", "personal"),
                    ("replay", "replay"),
                    ("scenario", "scenario_single"),
                ]
                assert sum(row["task_key"] == str(ordinary_id) for row in task_rows) == 1
                assert sum(row["task_key"] == str(replay_id) for row in task_rows) == 1
                assert await conn.fetchval(
                    f'SELECT novel FROM "{analytics_schema}".tasks WHERE source=\'ordinary\''
                ) is True
                assert await conn.fetchval(
                    f'SELECT count(*) FROM "{analytics_schema}".tasks WHERE source=\'scenario\''
                ) == 1

                attempts = await conn.fetch(
                    f'SELECT source,created_at FROM "{analytics_schema}".attempts ORDER BY source'
                )
                assert [row["source"] for row in attempts] == [
                    "mixed", "ordinary", "replay", "scenario"
                ]
                assert attempts[2]["created_at"] is not None

                assert await conn.fetchval("SHOW transaction_read_only") == "on"
                assert await conn.fetchval("SHOW transaction_isolation") == "repeatable read"
                assert await conn.fetchval("SELECT current_schemas(false)") == [
                    "pg_catalog", analytics_schema
                ]
                task_columns = await conn.fetch(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema=$1 AND table_name='tasks'",
                    analytics_schema,
                )
                assert not {"snapshot", "raw_answer", "telegram_user_id"} & {
                    row["column_name"] for row in task_columns
                }
                assert await conn.fetchval(
                    f'SELECT bot_id FROM "{analytics_schema}".operations WHERE bot_id=0 LIMIT 1'
                ) == 0
                with pytest.raises(asyncpg.ReadOnlySQLTransactionError):
                    await conn.execute(
                        f'UPDATE "{source_schema}".users SET telegram_user_id=0'
                    )
        # Scoped settings must not persist on a pooled connection.
        async with pool.acquire() as conn:
            assert await conn.fetchval("SHOW transaction_read_only") == "off"
            assert source_schema in await conn.fetchval("SHOW search_path")
            assert await conn.fetchval("SHOW statement_timeout") == "0"
            assert await conn.fetchval("SHOW idle_in_transaction_session_timeout") == "0"
    finally:
        if pool is not None:
            await pool.close()
        await setup.close()
        await admin.execute(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)')
        await admin.close()
