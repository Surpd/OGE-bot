import asyncio
import os
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest

from app.persistence.part2_bank import import_bank
from app.persistence.part2_training import Part2Training


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


async def test_albums_resume_rotation_and_ownership(bank_pool):
    bank = Part2Training(bank_pool)
    for number in range(20, 26):
        result = await asyncio.gather(bank.open(1, number), bank.open(1, number))
        assert result[0] == result[1]
        issue = result[0]
        a = await bank.current(1, issue)
        assert a and a["card"]["number"] == number
        assert await bank.current(2, issue) is None
        assert not await bank.append(2, issue, 1, 1, None, "wrong", 4)
        assert await bank.append(1, issue, 1, 5, "step 1", "photo-a", 2, f"album-{number}")
        assert not await bank.append(1, issue, 1, 5, "step 1", "photo-a", 2, f"album-{number}")
        reopened = Part2Training(bank_pool)
        assert await reopened.open(1, number) == issue
        assert await reopened.append(1, issue, 1, 6, None, "photo-b", 2, f"album-{number}")
        assert not await reopened.append(1, issue, 1, 7, None, "photo-c", 2)
        assert await reopened.open(1, number, replace=issue) != issue
        b = await bank.current(1)
        assert not await bank.append(1, b["id"], 1, 9, None, "late", 2, f"album-{number}")
        assert b["subtype_id"] != a["subtype_id"]
        assert await reopened.open(1, number, replace=issue) is None
