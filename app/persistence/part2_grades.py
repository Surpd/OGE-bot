"""Reserve the worst-case charge before submission. Unknown provider costs keep the hold."""

import asyncio
import json
import logging
from decimal import Decimal
from typing import Any

import asyncpg

from app.config import Settings
from app.part2_grading import OUTPUT_LIMIT, PROMPT_VERSION, Assessment, cost


async def reserve(
    pool: asyncpg.Pool, s: Settings, owner: int, issue: int, revision: int
) -> tuple[str, list[asyncpg.Record]]:
    ceiling = cost(s, s.oge_grading_context_tokens, OUTPUT_LIMIT)
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("SELECT pg_advisory_xact_lock(202725, 1)")
        version = await conn.fetchval(
            """SELECT version FROM part2_issues WHERE owner=$1 AND id=$2 AND NOT closed
               AND revision=$3 FOR UPDATE""",
            owner,
            issue,
            revision,
        )
        if version is None:
            return "Эта работа уже отправлена.", []
        if await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM part2_work WHERE issue_id=$1 AND revision=$2"
            " AND (photo_expired OR (photo IS NOT NULL AND created_at < now()-interval '7 days')))",
            issue,
            revision,
        ):
            await conn.execute("UPDATE part2_issues SET revision=revision+1 WHERE id=$1", issue)
            return "Срок хранения истёк. Пришлите решение целиком.", []
        work = await conn.fetch(
            """SELECT body,photo FROM part2_work WHERE issue_id=$1 AND revision=$2
               ORDER BY message_id""",
            issue,
            revision,
        )
        if not work:
            return "Пришлите текст или фото решения.", []
        usage = await conn.fetchrow(
            """SELECT count(*) FILTER (WHERE i.owner=$1 AND
            g.created_at >= date_trunc('day',now(),'UTC')) AS daily,
            coalesce(sum(coalesce(cost_usd,reserved_usd)),0) AS monthly
            FROM part2_grades g JOIN part2_issues i ON i.id=g.issue_id
            WHERE g.created_at >= date_trunc('month',now(),'UTC')""",
            owner,
        )
        if usage["daily"] >= s.oge_grading_daily_user_limit:
            return "Дневной лимит проверок исчерпан. Работа сохранена.", []
        if usage["monthly"] + ceiling > s.oge_grading_monthly_budget_usd:
            return "Лимит проверки исчерпан. Работа сохранена.", []
        await conn.execute(
            """INSERT INTO part2_grades(issue_id,revision,model,prompt_version,rubric_version,
            status,reserved_usd) VALUES ($1,$2,$3,$4,$5,'pending',$6)""",
            issue,
            revision,
            s.oge_grading_model,
            PROMPT_VERSION,
            version,
            ceiling,
        )
        await conn.execute("UPDATE part2_issues SET revision=revision+1 WHERE id=$1", issue)
        return "", list(work)


async def finish(
    pool: asyncpg.Pool,
    s: Settings,
    issue: int,
    revision: int,
    result: tuple[Assessment, int, int, str] | None,
    *,
    dispatched: bool,
) -> None:
    report: dict[str, Any] | None = None
    inputs = outputs = None
    amount: Decimal | None = None if dispatched else Decimal(0)
    if result:
        assessment, inputs, outputs, model = result
        report = {**assessment.model_dump(), "model_id": model, "prompt_version": PROMPT_VERSION}
        amount = cost(s, inputs, outputs)
    await pool.execute(
        """UPDATE part2_grades SET status=$3,score=$4,
        result=CASE WHEN $5::jsonb IS NULL THEN NULL ELSE
        $5::jsonb || jsonb_build_object('rubric_version',rubric_version) END,
        input_tokens=$6,output_tokens=$7,cost_usd=$8 WHERE issue_id=$1 AND revision=$2
        AND status='pending'""",
        issue,
        revision,
        report["status"] if report else "error",
        report["score"] if report else None,
        json.dumps(report) if report else None,
        inputs,
        outputs,
        amount,
    )


async def expire_work(pool: asyncpg.Pool) -> None:
    # Only Telegram photo handles expire. Preserve the original text and its history.
    async with pool.acquire() as conn, conn.transaction():
        # Expiring one page invalidates that draft as a whole. Never grade the surviving
        # fragments as if the student had submitted a complete solution.
        await conn.execute(
            """UPDATE part2_issues i SET revision=revision+1
            WHERE EXISTS (SELECT 1 FROM part2_work w WHERE w.issue_id=i.id
              AND w.revision=i.revision AND w.photo IS NOT NULL
              AND w.created_at < now()-interval '7 days')"""
        )
        await conn.execute(
            "UPDATE part2_work SET photo=NULL,photo_expired=true WHERE photo IS NOT NULL"
            " AND created_at < now()-interval '7 days'"
        )
        await conn.execute(
            "UPDATE part2_grades SET status='error' WHERE status='pending' "
            "AND created_at < now() - interval '10 minutes'"
        )


async def maintain_work(pool: asyncpg.Pool) -> None:
    while True:
        try:
            await expire_work(pool)
        except (asyncpg.PostgresError, OSError, TimeoutError):
            logging.getLogger(__name__).warning("part2_retention_retry")
            await asyncio.sleep(60)
        else:
            await asyncio.sleep(3600)
