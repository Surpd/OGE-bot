"""Record an authorized teacher's independent review of the original card, rubric and work."""

import argparse
import asyncio
import os
import re

import asyncpg

from app.adaptive.store import sync

REASONS = (
    "calculation",
    "lost_root",
    "equivalence",
    "domain",
    "justification",
    "theorem",
    "incomplete_proof",
    "graph",
    "model",
)


async def confirm(
    conn: asyncpg.Connection,
    learner: int,
    issue: int,
    revision: int,
    score: int,
    reasons: list[str],
) -> None:
    reasons = sorted(set(reasons))
    if score not in (0, 1, 2) or set(reasons) - set(REASONS) or score == 2 and reasons:
        raise ValueError("Invalid score or reason codes")
    async with conn.transaction():
        grade = await conn.fetchrow(
            """SELECT u.id,g.score,g.status FROM part2_grades g
            JOIN part2_issues i ON i.id=g.issue_id JOIN users u ON u.telegram_user_id=i.owner
            WHERE i.owner=$1 AND i.id=$2 AND g.revision=$3 FOR UPDATE OF g""",
            learner,
            issue,
            revision,
        )
        if not grade or grade["status"] != "graded" or grade["score"] != score:
            raise ValueError("Confirmation requires a matching final grade for this learner")
        await conn.execute(
            """INSERT INTO adaptive_grade_reviews(issue_id,revision,score,reasons)
            VALUES($1,$2,$3,$4) ON CONFLICT DO NOTHING""",
            issue,
            revision,
            score,
            reasons,
        )
        stored = await conn.fetchrow(
            """SELECT score,reasons FROM adaptive_grade_reviews
            WHERE issue_id=$1 AND revision=$2""",
            issue,
            revision,
        )
        if stored["score"] != score or stored["reasons"] != reasons:
            raise ValueError("A different confirmation already exists")
        await conn.execute(
            """INSERT INTO adaptive_dirty(owner,source,task) VALUES($1,'written',$2)
            ON CONFLICT DO NOTHING""",
            grade["id"],
            str(issue),
        )
        await sync(conn, grade["id"])


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", default="public")
    for name in ("user", "issue", "revision", "score"):
        parser.add_argument(f"--{name}", type=int, required=True)
    parser.add_argument("--reason", choices=REASONS, action="append", default=[])
    args = parser.parse_args()
    if not re.fullmatch(r"public|oge_test_bot_[1-9][0-9]{0,19}", args.schema):
        parser.error("Unknown bot namespace")
    conn = await asyncpg.connect(
        os.environ["DATABASE_URL"], server_settings={"search_path": args.schema}
    )
    try:
        await confirm(conn, args.user, args.issue, args.revision, args.score, args.reason)
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
