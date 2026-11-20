import json
import os
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest

from app.persistence.part2_bank import ATLAS, import_bank, load_bank


def test_review_is_pinned_to_content_and_images():
    _, cards = load_bank()
    reviewed = json.loads((ATLAS / "reviewed_versions.json").read_text())
    sampled = [json.loads(p) for tid, _, p, d in cards if reviewed.get(tid) == d]
    assert len(sampled) == len(reviewed) == 12
    for number in range(20, 26):
        assert len({x["subtype_id"] for x in sampled if x["number"] == number}) == 2


async def test_import_is_atomic_and_replay_keeps_the_original_version(tmp_path):
    if not os.getenv("DATABASE_URL"):
        pytest.skip("requires PostgreSQL")
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    schema = f"part2_{uuid4().hex}"
    try:
        async with conn.transaction():
            await conn.execute(f'CREATE SCHEMA "{schema}"')
            await conn.execute(f'SET LOCAL search_path TO "{schema}"')
            await conn.execute(
                Path("migrations/0021_part2_bank.sql")
                .read_text()
                .removeprefix("BEGIN;")
                .removesuffix("COMMIT;\n")
            )
            for _ in range(2):
                assert await import_bank(conn) == 486
            assert await conn.fetchval("SELECT count(*) FROM part2_versions") == 486
            assert await conn.fetchval("SELECT count(*) FROM part2_versions WHERE available") == 12
            for name in ("figures", "taxonomy.json", "reviewed_versions.json"):
                (tmp_path / name).symlink_to(ATLAS / name)
            card = json.loads((ATLAS / "tasks.jsonl").read_text().splitlines()[0])
            original = card["statement"]
            card["statement"] += " v2"
            path = tmp_path / "tasks.jsonl"
            path.write_text(json.dumps(card))
            with pytest.raises(ValueError, match="without a new version"):
                await import_bank(conn, tmp_path)
            card["content_version"] += 1
            path.write_text(json.dumps(card))
            await import_bank(conn, tmp_path)
            rows = await conn.fetch(
                "SELECT payload->>'statement' text FROM part2_versions "
                "WHERE task_id=$1 ORDER BY version",
                card["task_id"],
            )
            assert [r["text"] for r in rows] == [original, card["statement"]]
    finally:
        await conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        await conn.close()
