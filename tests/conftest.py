import os
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest

from app.persistence.part2_bank import import_bank


@pytest.fixture
async def bank_pool():
    if not os.getenv("DATABASE_URL"):
        pytest.skip("requires PostgreSQL")
    url = os.environ["DATABASE_URL"]
    conn = await asyncpg.connect(url)
    schema = f"p2_{uuid4().hex}"
    await conn.execute(f'CREATE SCHEMA "{schema}"')
    pool = await asyncpg.create_pool(
        url, min_size=1, max_size=4, server_settings={"search_path": schema}
    )
    try:
        for path in sorted(Path("migrations").glob("*.sql")):
            await pool.execute(path.read_text())
        async with pool.acquire() as db:
            await import_bank(db)
        await pool.execute("INSERT INTO users(telegram_user_id) VALUES(1),(2)")
        yield pool
    finally:
        await pool.close()
        await conn.execute(f'DROP SCHEMA "{schema}" CASCADE')
        await conn.close()
