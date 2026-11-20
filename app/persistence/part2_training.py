"""Owner-scoped, version-pinned bank issuance and append-only student work."""

import json
from typing import Any

import asyncpg


class Part2Training:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool

    async def choices(self, number: int) -> list[asyncpg.Record]:
        return list(
            await self.pool.fetch(
                """SELECT DISTINCT s.subtype_id,s.title FROM part2_subtypes s
            JOIN part2_cards c USING(subtype_id) JOIN part2_versions v USING(task_id)
            JOIN part2_families f USING(family_id) WHERE f.number=$1 AND v.available
            ORDER BY s.title""",
                number,
            )
        )

    async def open(
        self, owner: int, number: int, subtype: str | None = None, *, replace: int | None = None
    ) -> int | None:
        async with self.pool.acquire() as conn, conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock($1)", owner)
            current = await conn.fetchrow(
                "SELECT * FROM part2_issues WHERE owner=$1 AND number=$2 AND NOT closed FOR UPDATE",
                owner,
                number,
            )
            if replace is not None and (not current or current["id"] != replace):
                return None
            if current and replace is None and (not subtype or current["subtype_id"] == subtype):
                await conn.execute(
                    "UPDATE part2_issues SET touched_at=now() WHERE id=$1", current["id"]
                )
                return int(current["id"])
            card = await conn.fetchrow(
                """WITH history AS (SELECT * FROM part2_issues WHERE owner=$1 AND number=$2)
                SELECT task_id,version,subtype_id FROM part2_versions v
                JOIN part2_cards c USING(task_id) JOIN part2_subtypes s USING(subtype_id)
                JOIN part2_families f USING(family_id) WHERE v.available AND f.number=$2
                AND ($3::text IS NULL OR subtype_id=$3)
                ORDER BY (SELECT max(issued_at) FROM history h WHERE h.subtype_id=c.subtype_id)
                  NULLS FIRST, (SELECT max(issued_at) FROM history h WHERE h.task_id=v.task_id)
                  NULLS FIRST, random() LIMIT 1""",
                owner,
                number,
                subtype,
            )
            if card is None:
                return None
            if current:
                await conn.execute("UPDATE part2_issues SET closed=true WHERE id=$1", current["id"])
            return int(
                await conn.fetchval(
                    """INSERT INTO part2_issues(owner,number,task_id,version,subtype_id)
                VALUES ($1,$2,$3,$4,$5) RETURNING id""",
                    owner,
                    number,
                    *card.values(),
                )
            )

    async def current(self, owner: int, issue: int | None = None) -> dict[str, Any] | None:
        row = await self.pool.fetchrow(
            """SELECT i.*,v.payload FROM part2_issues i JOIN part2_versions v USING(task_id,version)
            WHERE owner=$1 AND NOT closed ORDER BY touched_at DESC,id DESC LIMIT 1""",
            owner,
        )
        if not row or issue is not None and issue != row["id"]:
            return None
        return {**row, "card": json.loads(row["payload"])}

    async def append(
        self,
        owner: int,
        issue: int,
        revision: int,
        message: int,
        body: str | None,
        photo: str | None,
        limit: int,
    ) -> bool:
        async with self.pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                """SELECT id FROM part2_issues WHERE owner=$1 AND id=$2 AND NOT closed
                AND revision=$3 FOR UPDATE""",
                owner,
                issue,
                revision,
            )
            if not row:
                return False
            count = await conn.fetchrow(
                """SELECT count(*) entries,count(photo) photos FROM part2_work
                WHERE issue_id=$1 AND revision=$2""",
                issue,
                revision,
            )
            if count["entries"] >= 12 or photo and count["photos"] >= limit:
                return False
            return bool(
                await conn.fetchval(
                    """INSERT INTO part2_work(issue_id,revision,message_id,body,photo)
                VALUES ($1,$2,$3,$4,$5) ON CONFLICT DO NOTHING RETURNING true""",
                    issue,
                    revision,
                    message,
                    body,
                    photo,
                )
            )
