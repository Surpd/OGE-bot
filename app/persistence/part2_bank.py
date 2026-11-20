"""Static part-two atlas. Every issue pins one immutable content and rubric version."""

import hashlib
import json
from pathlib import Path
from typing import Any

import asyncpg

ATLAS = Path(__file__).resolve().parents[2] / "atlas" / "part2"


def figure(path: str, root: Path = ATLAS) -> bytes:
    name = Path(path)
    if name.parts != ("figures", name.name) or name.suffix != ".png":
        raise ValueError("Invalid atlas figure path")
    return (root / name).read_bytes()


def load_bank(root: Path = ATLAS) -> tuple[list[dict[str, Any]], list[tuple[str, int, str, str]]]:
    subtypes = json.loads((root / "taxonomy.json").read_text())["subtypes"]
    cards = []
    for line in (root / "tasks.jsonl").read_text().splitlines():
        task = json.loads(line)
        for visual in task["visuals"]:
            visual["sha256"] = hashlib.sha256(figure(visual["path"], root)).hexdigest()
        payload = json.dumps(task, ensure_ascii=False, sort_keys=True)
        digest = hashlib.sha256(payload.encode()).hexdigest()
        cards.append((task["task_id"], task["content_version"], payload, digest))
    return subtypes, cards


async def import_bank(connection: asyncpg.Connection, root: Path = ATLAS) -> int:
    subtypes, cards = load_bank(root)
    approved = json.loads((root / "reviewed_versions.json").read_text())
    async with connection.transaction():
        await connection.execute("SELECT pg_advisory_xact_lock(202725)")
        for item in subtypes:
            await connection.execute(
                "INSERT INTO part2_families VALUES ($1,$2,$3) ON CONFLICT DO NOTHING",
                item["family_id"],
                item["number"],
                item["family_title"],
            )
            await connection.execute(
                "INSERT INTO part2_subtypes VALUES ($1,$2,$3) ON CONFLICT DO NOTHING",
                item["subtype_id"],
                item["family_id"],
                item["title"],
            )
        # Even superseded cards must still be able to read their original images.
        for row in await connection.fetch(
            "SELECT DISTINCT v->>'path' path, v->>'sha256' sha FROM part2_versions,"
            " LATERAL jsonb_array_elements(payload->'visuals') v"
        ):
            if hashlib.sha256(figure(row["path"], root)).hexdigest() != row["sha"]:
                raise ValueError(f"Historical image changed: {row['path']}")
        await connection.execute("UPDATE part2_versions SET available=false WHERE available")
        for task_id, version, payload, digest in cards:
            subtype = json.loads(payload)["subtype_id"]
            stored = await connection.fetchval(
                """INSERT INTO part2_cards VALUES ($1,$2) ON CONFLICT (task_id)
                DO UPDATE SET task_id=excluded.task_id RETURNING subtype_id""",
                task_id,
                subtype,
            )
            if stored != subtype:
                raise ValueError(f"Card subtype changed: {task_id}")
            stored = await connection.fetchval(
                """INSERT INTO part2_versions VALUES ($1,$2,$3,$4,$5)
                ON CONFLICT (task_id,version) DO UPDATE SET available=excluded.available
                RETURNING digest""",
                task_id,
                version,
                payload,
                digest,
                approved.get(task_id) == digest,
            )
            if stored != digest:
                raise ValueError(f"Content changed without a new version: {task_id}")
    return len(cards)
