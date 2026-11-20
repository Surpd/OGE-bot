"""Written-work scores remain separate from the first-part answer contract."""

from typing import Any

import asyncpg


async def summary(pool: asyncpg.Pool, owner: int) -> dict[int, dict[str, Any]]:
    rows = await pool.fetch(
        """WITH by_issue AS (
            SELECT i.id,i.number,i.hints,s.title,
              count(g.score) checked, count(g.revision) FILTER(WHERE g.revision>1) revisions,
              count(*) FILTER(WHERE g.status IN ('uncertain','unreadable')) unclear,
              count(*) FILTER(WHERE g.status IN ('pending','error')) unavailable,
              max(g.score) FILTER(WHERE g.revision=1) initial,
              count(*) FILTER(WHERE g.score=0) zeros,count(*) FILTER(WHERE g.score=1) ones,
              count(*) FILTER(WHERE g.score=2) twos, coalesce(sum(g.score),0) points
            FROM part2_issues i JOIN part2_subtypes s USING(subtype_id)
            LEFT JOIN part2_grades g ON g.issue_id=i.id WHERE i.owner=$1
            GROUP BY i.id,s.title)
            SELECT number,title,count(*) issued,sum(hints) hints,sum(checked) checked,
              sum(revisions) revisions,sum(unclear) unclear,sum(unavailable) unavailable,
              count(*) FILTER(WHERE checked=0) unchecked,count(initial) first_graded,
              count(*) FILTER(WHERE initial=2) first_full,sum(initial) first_points,
              sum(zeros) zeros,sum(ones) ones,sum(twos) twos,sum(points) points
            FROM by_issue GROUP BY number,title ORDER BY number,title""",
        owner,
    )
    result: dict[int, dict[str, Any]] = {}
    for row in rows:
        group = result.setdefault(row["number"], {"subtypes": []})
        values = {k: int(v or 0) for k, v in row.items() if k not in {"number", "title"}}
        for k, v in values.items():
            group[k] = group.get(k, 0) + v
        group["subtypes"].append({"title": row["title"], **values})
    return result


async def history(pool: asyncpg.Pool, owner: int, offset: int) -> list[asyncpg.Record]:
    return list(
        await pool.fetch(
            """SELECT i.id,i.number,s.title,i.issued_at FROM part2_issues i
        JOIN part2_subtypes s USING(subtype_id) WHERE i.owner=$1 ORDER BY i.id DESC
        LIMIT 7 OFFSET $2""",
            owner,
            offset,
        )
    )


async def revision(
    pool: asyncpg.Pool, owner: int, issue: int, attempt: int
) -> tuple[asyncpg.Record, list[asyncpg.Record]] | None:
    row = await pool.fetchrow(
        """SELECT v.payload->>'statement' statement, v.payload->'visuals' visuals, i.number,
        (SELECT max(n) FROM (SELECT revision AS n FROM part2_grades WHERE issue_id=i.id
          UNION ALL SELECT revision FROM part2_work WHERE issue_id=i.id
          ) revisions) last_work, g.result,g.status,g.score,
        g.created_at,g.model,g.prompt_version,g.rubric_version FROM part2_issues i
        JOIN part2_versions v USING(task_id,version)
        LEFT JOIN part2_grades g ON g.issue_id=i.id AND g.revision=$3
        WHERE i.owner=$1 AND i.id=$2 AND $3 BETWEEN 1 AND i.revision""",
        owner,
        issue,
        attempt,
    )
    if not row:
        return None
    work = await pool.fetch(
        """SELECT w.body,CASE WHEN w.created_at>now()-interval '7 days' THEN w.photo END photo,
        w.photo_expired OR (w.photo IS NOT NULL AND w.created_at<=now()-interval '7 days') expired
        FROM part2_work w JOIN part2_issues i ON i.id=w.issue_id
        WHERE i.owner=$1 AND i.id=$2 AND w.revision=$3 AND NOT w.superseded
        ORDER BY message_id""",
        owner,
        issue,
        attempt,
    )
    return row, list(work)
