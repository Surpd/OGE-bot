"""Read-only measurements of retained OGE task snapshots and replay metadata."""

from __future__ import annotations

import asyncio
import json
import os
from collections import Counter
from typing import Any

import asyncpg


def _payload_bytes(value: object) -> tuple[int, Counter[str]]:
    byte_count = 0
    names: Counter[str] = Counter()

    def visit(node: object) -> None:
        nonlocal byte_count
        if isinstance(node, dict):
            for key, child in node.items():
                if isinstance(key, str) and (
                    key.endswith("_base64") or key == "option_svgs"
                ):
                    names[key] += 1
                    byte_count += len(json.dumps(child, ensure_ascii=False).encode())
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(value)
    return byte_count, names


async def audit(database_url: str) -> dict[str, Any]:
    connection = await asyncpg.connect(database_url)
    try:
        report: dict[str, Any] = {
            "read_only": True,
            "tables": {},
            "scenario_duplicates": {},
            "replay_metadata": None,
        }
        async with connection.transaction(readonly=True):
            for name, query in (
                (
                    "ordinary",
                    """SELECT count(*) AS rows,
                              COALESCE(sum(pg_column_size(snapshot)),0) AS snapshot_bytes,
                              COALESCE(avg(pg_column_size(snapshot)),0)::bigint AS average_bytes,
                              COALESCE(max(pg_column_size(snapshot)),0) AS maximum_bytes,
                              count(*) FILTER (WHERE snapshot::text LIKE '%base64%') AS with_images
                       FROM issued_problems""",
                ),
                (
                    "mixed",
                    """SELECT count(*) AS rows,
                              COALESCE(sum(pg_column_size(p.snapshot)),0) AS snapshot_bytes,
                              COALESCE(avg(pg_column_size(p.snapshot)),0)::bigint AS average_bytes,
                              COALESCE(max(pg_column_size(p.snapshot)),0) AS maximum_bytes,
                              count(*) FILTER (
                                  WHERE p.snapshot::text LIKE '%base64%'
                              ) AS with_images
                       FROM mixed_training_problems p""",
                ),
                (
                    "scenarios",
                    """SELECT count(*) AS rows,
                              COALESCE(sum(pg_column_size(snapshot)),0) AS snapshot_bytes,
                              COALESCE(avg(pg_column_size(snapshot)),0)::bigint AS average_bytes,
                              COALESCE(max(pg_column_size(snapshot)),0) AS maximum_bytes,
                              count(*) FILTER (WHERE snapshot::text LIKE '%base64%') AS with_images
                       FROM oge15_scenarios""",
                ),
            ):
                row = await connection.fetchrow(query)
                report["tables"][name] = {key: int(value) for key, value in dict(row).items()}

            report["mixed_session_state"] = dict(
                await connection.fetchrow(
                    """SELECT count(*)::bigint AS sessions,
                              COALESCE(sum(pg_column_size(state)),0)::bigint AS state_bytes,
                              COALESCE(avg(pg_column_size(state)),0)::bigint AS average_bytes,
                              count(*) FILTER (
                                WHERE jsonb_typeof(state->'scenario_snapshot')='object'
                              )::bigint
                                AS with_shared_scenario,
                              count(*) FILTER (WHERE status='completed')::bigint AS completed
                       FROM mixed_training_sessions"""
                )
            )
            report["mixed_scenario_history"] = dict(
                await connection.fetchrow(
                    """SELECT count(*)::bigint AS retained_shared_scenarios,
                              COALESCE(sum(pg_column_size(
                                  snapshot->'_original_scenario_snapshot'
                              )),0)::bigint AS retained_scenario_bytes
                       FROM mixed_training_problems
                       WHERE snapshot ? '_original_scenario_snapshot'"""
                )
            )
            exists = await connection.fetchval(
                "SELECT to_regclass('training_error_replays') IS NOT NULL"
            )
            if exists:
                report["replay_metadata"] = dict(
                    await connection.fetchrow(
                        """SELECT count(*)::bigint AS rows,
                                  COALESCE(avg(pg_column_size(to_jsonb(r))),0)::bigint
                                    AS average_row_bytes,
                                  COALESCE(max(pg_column_size(to_jsonb(r))),0)::bigint
                                    AS maximum_row_bytes,
                                  COALESCE(sum(pg_column_size(attempts)),0)::bigint
                                    AS attempt_log_bytes
                           FROM training_error_replays r"""
                    )
                )
            # Inspect only a bounded sample to report actual locations and payload lengths.
            payload_keys: Counter[str] = Counter()
            payload_bytes = 0
            for _table, query in (
                (
                    "ordinary",
                    "SELECT snapshot FROM issued_problems "
                    "ORDER BY pg_column_size(snapshot) DESC LIMIT 50",
                ),
                (
                    "mixed",
                    "SELECT snapshot FROM mixed_training_problems "
                    "ORDER BY pg_column_size(snapshot) DESC LIMIT 50",
                ),
                (
                    "scenarios",
                    "SELECT snapshot FROM oge15_scenarios "
                    "ORDER BY pg_column_size(snapshot) DESC LIMIT 50",
                ),
            ):
                rows = await connection.fetch(query)
                for row in rows:
                    snapshot = row["snapshot"]
                    if isinstance(snapshot, str):
                        snapshot = json.loads(snapshot)
                    size, keys = _payload_bytes(snapshot)
                    payload_bytes += size
                    payload_keys.update(keys)
            report["largest_150_snapshot_sample"] = {
                "payload_bytes": payload_bytes,
                "payload_fields": dict(sorted(payload_keys.items())),
                "limit_per_table": 50,
            }
        return report
    finally:
        await connection.close()


def main() -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL is required; this command opens a read-only transaction")
    print(
        json.dumps(
            asyncio.run(audit(database_url)), ensure_ascii=False, indent=2, sort_keys=True
        )
    )


if __name__ == "__main__":
    main()
