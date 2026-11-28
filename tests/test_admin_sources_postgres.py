import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import asyncpg
import pytest

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
        provision = Path("scripts/configure_admin_analytics_reader.sql").read_text()
        await pool.execute(provision)
        await pool.execute(provision)

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
        await pool.execute(
            "UPDATE oge15_question_progress SET adaptive_issued_at=NULL WHERE session_id=$1",
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
        async with pool.acquire() as conn:
            await conn.execute("SET ROLE oge_admin_reader")
            try:
                task_rows = await conn.fetch(
                    f'SELECT source,mode,task_key FROM "{analytics_schema}".tasks '
                    "ORDER BY source,mode"
                )
                assert [(row["source"], row["mode"]) for row in task_rows] == [
                    ("mixed", "mixed"),
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

                assert await conn.fetchval(
                    "SELECT has_table_privilege('oge_admin_reader',c.oid,'SELECT') "
                    "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname=$1 AND c.relname='issued_problems'",
                    source_schema,
                ) is False
                assert await conn.fetchval(
                    "SELECT rolbypassrls OR rolsuper FROM pg_roles WHERE rolname=current_user"
                ) is False
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
            finally:
                await conn.execute("RESET ROLE")

            await conn.execute("SET ROLE oge_admin_projection")
            try:
                assert await conn.fetchval(
                    f'SELECT count(id) FROM "{source_schema}".issued_problems'
                ) == 1
                with pytest.raises(asyncpg.InsufficientPrivilegeError):
                    await conn.fetchval(
                        f'SELECT raw_answer FROM "{source_schema}".attempts LIMIT 1'
                    )
                with pytest.raises(asyncpg.InsufficientPrivilegeError):
                    await conn.fetchval(
                        f'SELECT attempts FROM "{source_schema}".training_error_replays LIMIT 1'
                    )
            finally:
                await conn.execute("RESET ROLE")
    finally:
        if pool is not None:
            await pool.close()
        await setup.close()
        await admin.execute(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)')
        await admin.close()


@pytest.mark.asyncio
async def test_reader_provisioning_works_for_non_superuser_createrole_owner() -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL not configured")

    admin = await asyncpg.connect(database_url)
    privileges = await admin.fetchrow(
        "SELECT rolsuper,rolcreaterole,rolcreatedb FROM pg_roles WHERE rolname=current_user"
    )
    if not privileges["rolsuper"] and not (
        privileges["rolcreaterole"] and privileges["rolcreatedb"]
    ):
        await admin.close()
        pytest.skip("requires CREATEROLE and CREATEDB to create an isolated non-superuser fixture")

    suffix = uuid4().hex[:10]
    owner_role = f"admin_owner_{suffix}"
    reader_role = f"oge_reader_{suffix}"
    projection_role = f"oge_projection_{suffix}"
    login_role = f"admin_login_{suffix}"
    database_name = f"oge_admin_owner_{suffix}"
    test_password = "synthetic-owner-password"
    login_password = "synthetic-reader-password"
    await admin.execute(
        f"CREATE ROLE {owner_role} LOGIN CREATEROLE CREATEDB PASSWORD '{test_password}'"
    )
    await admin.execute(f'CREATE DATABASE "{database_name}" OWNER {owner_role}')

    parsed = urlsplit(database_url)
    hostport = parsed.netloc.rsplit("@", 1)[-1]
    owner_url = urlunsplit(parsed._replace(
        netloc=f"{owner_role}:{test_password}@{hostport}", path=f"/{database_name}"
    ))
    login_url = urlunsplit(parsed._replace(
        netloc=f"{login_role}:{login_password}@{hostport}", path=f"/{database_name}"
    ))
    owner = await asyncpg.connect(owner_url)
    pool = None
    login = None
    try:
        schema = f"owner_{suffix}"
        await owner.execute(f'CREATE SCHEMA "{schema}"')
        pool = await asyncpg.create_pool(
            owner_url, server_settings={"search_path": f'"{schema}",public'}
        )
        for migration in sorted(Path("migrations").glob("*.sql")):
            await pool.execute(await read_migration(str(migration)))

        provision = Path("scripts/configure_admin_analytics_reader.sql").read_text()
        provision = provision.replace("oge_admin_projection", projection_role)
        provision = provision.replace("oge_admin_reader", reader_role)
        await pool.execute(provision)
        await pool.execute(provision)

        assert await pool.fetchval(
            "SELECT NOT rolsuper AND NOT rolbypassrls "
            "FROM pg_roles WHERE rolname=$1",
            projection_role,
        ) is True
        assert await pool.fetchval(
            "SELECT NOT rolsuper AND NOT rolbypassrls "
            "FROM pg_roles WHERE rolname=$1",
            reader_role,
        ) is True
        assert await pool.fetchval(
            "SELECT NOT pg_has_role($1,$2,'MEMBER')", reader_role, projection_role
        ) is True
        analytics_schema = f"{schema}_admin"
        assert await pool.fetchval(
            "SELECT pg_get_userbyid(c.relowner) FROM pg_class c "
            "JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname=$1 AND c.relname='tasks'",
            analytics_schema,
        ) == projection_role

        await pool.execute(
            f"CREATE ROLE {login_role} LOGIN PASSWORD '{login_password}'; "
            f"GRANT {reader_role} TO {login_role}"
        )
        login = await asyncpg.connect(login_url)
        assert await login.fetchval(f'SELECT count(*) FROM "{analytics_schema}".tasks') == 0
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await login.fetchval(f'SELECT count(id) FROM "{schema}".issued_problems')
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await login.execute(f"SET ROLE {projection_role}")
    finally:
        if login is not None:
            await login.close()
        if pool is not None:
            await pool.close()
        await owner.close()
        await admin.execute(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)')
        await admin.execute(
            f"DROP ROLE IF EXISTS {login_role}, {reader_role}, {projection_role}, {owner_role}"
        )
        await admin.close()
