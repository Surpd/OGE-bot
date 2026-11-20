"""Owner-scoped, version-pinned bank issuance and append-only student work."""

import json
from typing import Any, Literal

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
            """SELECT i.*,v.payload,v.reviewed FROM part2_issues i
            JOIN part2_versions v USING(task_id,version)
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
        media_group: str | None = None,
        *,
        replace_photo: int | None = None,
    ) -> Literal["saved", "duplicate", "photo_limit", "stale"]:
        if not body and not photo:
            return "stale"
        async with self.pool.acquire() as conn, conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock($1)", owner)
            row = await conn.fetchval(
                """SELECT id FROM part2_issues WHERE owner=$1 AND id=$2 AND NOT closed
                AND revision=$3 AND solution_viewed_at IS NULL FOR UPDATE""",
                owner,
                issue,
                revision,
            )
            if not row:
                return "stale"
            if await conn.fetchval(
                """SELECT EXISTS(SELECT 1 FROM part2_work w JOIN part2_issues i ON i.id=w.issue_id
                   WHERE i.owner=$1 AND w.message_id=$2)""",
                owner,
                message,
            ):
                return "duplicate"
            if media_group:
                album = await conn.fetchrow(
                    """SELECT w.issue_id,w.revision FROM part2_work w
                    JOIN part2_issues i ON i.id=w.issue_id
                    WHERE w.media_group=$1 AND i.owner=$2 LIMIT 1""",
                    media_group,
                    owner,
                )
                if album:
                    if (album["issue_id"], album["revision"]) != (issue, revision):
                        return "stale"
                    return "photo_limit"
            work = await conn.fetch(
                """SELECT message_id,photo FROM part2_work
                WHERE issue_id=$1 AND revision=$2 AND NOT superseded""",
                issue,
                revision,
            )
            replacing = bool(
                photo
                and any(item["photo"] and item["message_id"] == replace_photo for item in work)
            )
            if photo and replace_photo is not None and not replacing:
                return "stale"
            if photo and not replacing and any(item["photo"] for item in work):
                # Remember the rejected message without retaining student content.
                # A delayed redelivery must not become the first photo of the next draft.
                await conn.execute(
                    """INSERT INTO part2_work(issue_id,revision,message_id,media_group,superseded)
                    VALUES ($1,$2,$3,$4,true)""",
                    issue,
                    revision,
                    message,
                    media_group,
                )
                return "photo_limit"
            if len(work) >= 12 and not replacing:
                return "stale"
            if replacing:
                # Only this open draft is changed. Standalone text and past revisions survive.
                await conn.execute(
                    """UPDATE part2_work SET superseded=true, photo=NULL, body=NULL
                    WHERE issue_id=$1 AND revision=$2 AND photo IS NOT NULL""",
                    issue,
                    revision,
                )
            await conn.execute(
                """INSERT INTO part2_work(issue_id,revision,message_id,body,photo,media_group)
                VALUES ($1,$2,$3,$4,$5,$6)""",
                issue,
                revision,
                message,
                body,
                photo,
                media_group,
            )
            return "saved"
