"""Rebuild one learner at a time in the explicitly selected database and schema."""

import argparse
import asyncio
import os
import re

import asyncpg

from app.adaptive.store import sync


async def main() -> None:
    parser = argparse.ArgumentParser()
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--user", type=int)
    scope.add_argument("--all", action="store_true")
    parser.add_argument("--schema", default="public")
    args = parser.parse_args()
    if not re.fullmatch(r"public|oge_test_bot_[1-9][0-9]{0,19}", args.schema):
        parser.error("Unknown bot namespace")
    conn = await asyncpg.connect(
        os.environ["DATABASE_URL"], server_settings={"search_path": args.schema}
    )
    try:
        last = 0
        while True:
            owners = await conn.fetch(
                """SELECT id,telegram_user_id FROM users
                WHERE telegram_user_id>$1 AND ($2::bigint IS NULL OR telegram_user_id=$2)
                ORDER BY telegram_user_id LIMIT 100""",
                last,
                args.user,
            )
            if not owners:
                if not last and args.user:
                    parser.error("Unknown learner")
                break
            for owner in owners:
                async with conn.transaction():
                    await sync(conn, owner["id"], rebuild=True)
                last = owner["telegram_user_id"]
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
