"""Initialize only an empty, dedicated DB; credentials come from environment, never CLI."""

import asyncio
import os

import asyncpg

from app.config import get_settings
from app.staging.safety import validate_settings


async def main() -> None:
    s = get_settings()
    validate_settings(s)
    if s.app_env != "staging" or os.getenv("STAGING_INIT_EMPTY_DATABASE") != "yes":
        raise RuntimeError("Explicit empty staging database initialization is required")
    conn = await asyncpg.connect(s.database_url)
    try:
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(734019)")
            if await conn.fetchval(
                "SELECT EXISTS(SELECT FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname NOT IN ('pg_catalog','information_schema') "
                "AND n.nspname NOT LIKE 'pg_toast%' AND c.relkind IN ('r','p','v','m','S'))"
            ):
                raise RuntimeError("Refusing nonempty database; never initialize from a live clone")
            await conn.execute("CREATE SCHEMA staging")
            await conn.execute(
                "CREATE TABLE staging.identity (singleton boolean PRIMARY KEY DEFAULT true "
                "CHECK(singleton), bot_id bigint NOT NULL, owner_id bigint NOT NULL, "
                "hostname text NOT NULL, database_name text NOT NULL, database_role text NOT NULL)"
            )
            await conn.execute(
                "INSERT INTO staging.identity "
                "VALUES(true,$1,$2,$3,current_database(),current_user)",
                s.staging_bot_id,
                s.staging_owner_id,
                s.staging_hostname,
            )
            await conn.execute(
                "CREATE TABLE staging.qa_sessions (owner bigint PRIMARY KEY, "
                "payload jsonb NOT NULL DEFAULT '{}', "
                "updated_at timestamptz NOT NULL DEFAULT now())"
            )
            await conn.execute("REVOKE ALL ON SCHEMA staging FROM PUBLIC")
            await conn.execute("REVOKE ALL ON ALL TABLES IN SCHEMA staging FROM PUBLIC")
    finally:
        await conn.close()
    print("Empty staging database initialized. No student data imported.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as error:
        # Connection/config exceptions may contain credentials; never print their payload.
        print(
            f"Initialization refused ({type(error).__name__}). "
            "Check staging identity, pinned SHA and an empty dedicated database."
        )
        raise SystemExit(1) from None
