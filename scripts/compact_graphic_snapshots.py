"""Compact old completed graphic snapshots while preserving restorable task data.

Run with ``--apply`` to update PostgreSQL. The default is a dry run.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from typing import cast
from uuid import UUID

import asyncpg

from app.persistence.image_retention import (
    can_compact_snapshot,
    compact_snapshot,
    is_graphic_snapshot,
    oge13_graphic_families,
)

_GRAPHIC_ATLAS_CLAUSE = """(
    jsonb_typeof(p.snapshot)='object' AND (
    (p.family_id LIKE 'OGE07-N%' AND p.snapshot ? 'graph_png_sha256')
    OR (p.family_id LIKE 'OGE11-%' AND p.snapshot ? 'image_sha256')
    OR p.family_id = ANY($1::text[])
    OR p.snapshot ?| ARRAY['graph_png_base64','png_base64','image_base64','picture_base64']
    )
)"""


def _snapshot_object(value: object) -> dict[str, object]:
    parsed = json.loads(value) if isinstance(value, str) else value
    if not isinstance(parsed, dict):
        raise ValueError("issued problem snapshot must be a JSON object")
    return cast(dict[str, object], parsed)


async def compact_old_snapshots(
    database_url: str,
    keep_full_per_user: int = 100,
    apply: bool = False,
    user_uuid: UUID | None = None,
) -> dict[str, int]:
    """Compact eligible completed snapshots beyond each user's retention limit."""
    if keep_full_per_user < 0:
        raise ValueError("keep_full_per_user cannot be negative")

    reader = await asyncpg.connect(database_url)
    writer = None
    try:
        if apply:
            writer = await asyncpg.connect(database_url)
        task13_graph_families = list(oge13_graphic_families())
        scope_clause = "AND ($2::uuid IS NULL OR p.user_id=$2)"
        counts = await reader.fetchrow(
            "SELECT count(*) AS total, count(DISTINCT p.user_id) AS users "
            f"FROM issued_problems p WHERE {_GRAPHIC_ATLAS_CLAUSE} {scope_clause}",
            task13_graph_families,
            user_uuid,
        )
        target_query = """WITH ranked AS (
               SELECT p.id, p.outcome,
                      EXISTS (SELECT 1 FROM sessions s WHERE s.active_problem_id=p.id)
                          AS is_active,
                      row_number() OVER (
                          PARTITION BY p.user_id ORDER BY p.issued_at DESC, p.id DESC
                      ) AS position
               FROM issued_problems p
               WHERE """ + _GRAPHIC_ATLAS_CLAUSE + " " + scope_clause + """
           )
           SELECT p.id, p.snapshot FROM ranked r
           JOIN issued_problems p ON p.id=r.id
           WHERE r.position > $3 AND NOT r.is_active AND r.outcome <> 'issued'
             AND p.snapshot ?| ARRAY[
                 'graph_png_base64', 'png_base64', 'image_base64', 'picture_base64', 'option_svgs'
             ]"""
        result = {
            "users_with_graphics": int(counts["users"]),
            "graphic_snapshots": int(counts["total"]),
            "eligible_for_compaction": 0,
            "would_compact": 0,
            "compacted": 0,
            "retained": 0,
            "unrestorable_retained": 0,
            "dry_run": int(not apply),
        }
        async with reader.transaction(readonly=True):
            async for row in reader.cursor(
                target_query,
                task13_graph_families,
                user_uuid,
                keep_full_per_user,
                prefetch=100,
            ):
                snapshot = _snapshot_object(row["snapshot"])
                if not is_graphic_snapshot(snapshot) or not can_compact_snapshot(snapshot):
                    result["retained"] += 1
                    result["unrestorable_retained"] += 1
                    continue
                result["eligible_for_compaction"] += 1
                result["would_compact"] += 1
                if writer is None:
                    continue
                status = await writer.execute(
                    """UPDATE issued_problems AS p SET snapshot=$2::jsonb
                       WHERE p.id=$1 AND p.outcome <> 'issued'
                         AND p.snapshot=$3::jsonb
                         AND jsonb_typeof(p.snapshot)='object'
                         AND NOT EXISTS (
                             SELECT 1 FROM sessions s
                             WHERE s.active_problem_id=p.id
                         )""",
                    row["id"],
                    json.dumps(compact_snapshot(snapshot)),
                    json.dumps(snapshot),
                )
                if status.endswith(" 1"):
                    result["compacted"] += 1
                else:
                    result["retained"] += 1
        return result
    finally:
        if writer is not None:
            await writer.close()
        await reader.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--keep-full-per-user",
        type=int,
        default=int(os.getenv("OGE_IMAGE_RETENTION_FULL_PER_USER", "100")),
        help="number of newest graphical tasks to retain per user (default 100)",
    )
    parser.add_argument("--apply", action="store_true", help="write compacted snapshots")
    args = parser.parse_args()
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        parser.error("DATABASE_URL is required")
    result = asyncio.run(
        compact_old_snapshots(
            database_url,
            keep_full_per_user=args.keep_full_per_user,
            apply=args.apply,
        )
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
