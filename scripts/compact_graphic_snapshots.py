"""Compact old completed graphic snapshots while preserving restorable task data.

Run with ``--apply`` to update PostgreSQL. The default is a dry run.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from hashlib import sha256
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
    OR (p.family_id LIKE 'OGE15-%' AND p.snapshot ? 'image_sha256')
    OR (p.family_id LIKE 'OGE17-%' AND p.snapshot ? 'png_sha256')
    OR (p.family_id LIKE 'OGE18-%' AND p.snapshot ? 'image_sha256')
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
            """WITH graphic_rows AS (
                 SELECT p.user_id,p.id FROM issued_problems p
                 WHERE """ + _GRAPHIC_ATLAS_CLAUSE + " " + scope_clause + """
                 UNION ALL
                 SELECT s.user_id,p.id FROM mixed_training_problems p
                 JOIN mixed_training_sessions s ON s.id=p.session_id
                 WHERE """ + _GRAPHIC_ATLAS_CLAUSE.replace("p.user_id", "s.user_id")
                 + " " + scope_clause.replace("p.user_id", "s.user_id") + """
               ) SELECT count(*) AS total, count(DISTINCT user_id) AS users FROM graphic_rows""",
            task13_graph_families,
            user_uuid,
        )
        target_query = """WITH all_graphics AS (
               SELECT 'ordinary'::text AS source,p.id,p.user_id,p.issued_at,p.outcome,
                      p.snapshot,NULL::text AS snapshot_sha256,
                      EXISTS (SELECT 1 FROM sessions s WHERE s.active_problem_id=p.id)
                          AS is_active
               FROM issued_problems p
               WHERE """ + _GRAPHIC_ATLAS_CLAUSE + " " + scope_clause + """
               UNION ALL
               SELECT 'mixed'::text AS source,p.id,s.user_id,p.issued_at,p.outcome,p.snapshot,
                      p.snapshot_sha256,
                      COALESCE(s.state->>'active_problem_id','')=p.id::text AS is_active
               FROM mixed_training_problems p
               JOIN mixed_training_sessions s ON s.id=p.session_id
               WHERE """ + _GRAPHIC_ATLAS_CLAUSE + " " + scope_clause.replace(
                   "p.user_id", "s.user_id"
               ) + """
           ), ranked AS (
               SELECT *,row_number() OVER (
                   PARTITION BY user_id ORDER BY issued_at DESC,id DESC
               ) AS position FROM all_graphics
           )
           SELECT r.source,r.id,r.snapshot,r.snapshot_sha256 FROM ranked r
           WHERE r.position > $3 AND NOT r.is_active AND r.outcome <> 'issued'
             AND r.snapshot ?| ARRAY[
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
                compacted = compact_snapshot(snapshot)
                if row["source"] == "ordinary":
                    status = await writer.execute(
                        """UPDATE issued_problems AS p SET snapshot=$2::jsonb
                           WHERE p.id=$1 AND p.outcome <> 'issued'
                             AND p.snapshot=$3::jsonb
                             AND jsonb_typeof(p.snapshot)='object'
                             AND NOT EXISTS (
                                 SELECT 1 FROM sessions s WHERE s.active_problem_id=p.id
                             )""",
                        row["id"], json.dumps(compacted), json.dumps(snapshot),
                    )
                else:
                    async with writer.transaction():
                        status = await writer.execute(
                            """UPDATE mixed_training_problems p SET snapshot=$2::jsonb,
                                  snapshot_sha256=$4
                               FROM mixed_training_sessions s
                               WHERE p.id=$1 AND s.id=p.session_id AND p.outcome <> 'issued'
                                 AND p.snapshot=$3::jsonb AND p.snapshot_sha256=$5
                                 AND COALESCE(s.state->>'active_problem_id','')<>p.id::text""",
                            row["id"], json.dumps(compacted), json.dumps(snapshot),
                            sha256(
                                json.dumps(
                                    compacted,
                                    ensure_ascii=False,
                                    sort_keys=True,
                                    separators=(",", ":"),
                                ).encode()
                            ).hexdigest(),
                            row["snapshot_sha256"],
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
