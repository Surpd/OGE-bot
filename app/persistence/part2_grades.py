"""Reserve the worst-case charge before submission. Unknown provider costs keep the hold."""

import asyncio
import json
import logging
from decimal import Decimal
from typing import Any

import asyncpg

from app.config import Settings
from app.part2_grading import PROMPT_VERSION, Grade, ceiling


async def budget_usage(conn: Any, owner: int) -> asyncpg.Record:
    return await conn.fetchrow(
        """WITH charges AS (
          SELECT i.owner,g.created_at,g.dispatched_at,g.status,g.cost_usd,g.reserved_usd
          FROM part2_grades g JOIN part2_issues i ON i.id=g.issue_id
          UNION ALL
          SELECT owner,created_at,dispatched_at,status,cost_usd,reserved_usd FROM part2_api_tests
        )
        SELECT count(*) FILTER(WHERE owner=$1 AND
            coalesce(dispatched_at,created_at)>=date_trunc('day',now(),'UTC')) daily,
          count(*) FILTER(WHERE owner=$1 AND
            coalesce(dispatched_at,created_at)>=date_trunc('month',now(),'UTC')) monthly,
          coalesce(bool_or(status='pending') FILTER(WHERE owner=$1),false) pending,
          coalesce(bool_or(coalesce(dispatched_at,created_at)>now()-interval '20 seconds')
            FILTER(WHERE owner=$1),false) cooldown,
          coalesce(sum(cost_usd) FILTER(WHERE created_at>=date_trunc('month',now(),'UTC')
            OR dispatched_at>=date_trunc('month',now(),'UTC')),0) spent,
          coalesce(sum(reserved_usd) FILTER(WHERE cost_usd IS NULL),0) held
          FROM charges WHERE cost_usd IS NULL OR created_at>=date_trunc('month',now(),'UTC')
            OR dispatched_at>=date_trunc('month',now(),'UTC')""",
        owner,
    )


def budget_notice(s: Settings, usage: asyncpg.Record) -> str:
    if ceiling(s) > s.oge_grading_request_budget_usd:
        return "Стоимость проверки превышает лимит на один запрос."
    if usage["monthly"] >= s.oge_grading_monthly_user_limit:
        return "Месячный лимит проверок исчерпан."
    if usage["daily"] >= s.oge_grading_daily_user_limit:
        return "Дневной лимит проверок исчерпан."
    if usage["pending"]:
        return "Одна проверка уже выполняется. Дождитесь результата."
    if usage["cooldown"]:
        return "Между запусками проверок должно пройти не менее 20 секунд."
    if usage["spent"] + usage["held"] + ceiling(s) > s.oge_grading_monthly_budget_usd:
        return "Лимит бюджета проверок исчерпан."
    return ""


async def reserve_test(pool: asyncpg.Pool, s: Settings, owner: int, confirmation: int) -> str:
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("SELECT pg_advisory_xact_lock(202725,1)")
        if await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM part2_api_tests WHERE owner=$1 AND confirmation=$2)",
            owner,
            confirmation,
        ):
            return "Этот тест уже отправлен."
        notice = budget_notice(s, await budget_usage(conn, owner))
        if notice:
            return notice
        accepted = await conn.fetchval(
            """INSERT INTO part2_api_tests(owner,confirmation,model,reserved_usd)
            VALUES($1,$2,$3,$4) ON CONFLICT DO NOTHING RETURNING true""",
            owner,
            confirmation,
            s.oge_grading_model,
            ceiling(s),
        )
        return "" if accepted else "Этот тест уже отправлен."


async def reserve(
    pool: asyncpg.Pool,
    s: Settings,
    owner: int,
    issue: int,
    revision: int,
    *,
    photo_message: int | None = None,
) -> tuple[str, list[asyncpg.Record]]:
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("SELECT pg_advisory_xact_lock($1)", owner)
        await conn.execute("SELECT pg_advisory_xact_lock(202725, 1)")
        if photo_message is not None and issue != await conn.fetchval(
            """SELECT id FROM part2_issues WHERE owner=$1 AND NOT closed
            ORDER BY touched_at DESC,id DESC LIMIT 1""",
            owner,
        ):
            return "Эта кнопка устарела. Текущее фото не изменено.", []
        version = await conn.fetchval(
            """SELECT version FROM part2_issues WHERE owner=$1 AND id=$2 AND NOT closed
               AND revision=$3 AND solution_viewed_at IS NULL FOR UPDATE""",
            owner,
            issue,
            revision,
        )
        if photo_message is not None and not await conn.fetchval(
            """SELECT EXISTS(SELECT 1 FROM part2_work WHERE issue_id=$1 AND revision=$2
            AND message_id=$3 AND photo IS NOT NULL AND NOT superseded)""",
            issue,
            revision,
            photo_message,
        ):
            return "Эта кнопка устарела. Текущее фото не изменено.", []
        if version is None:
            return "Эта работа уже отправлена или открыт разбор.", []
        if await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM part2_work WHERE issue_id=$1 AND revision=$2"
            " AND NOT superseded AND (photo_expired OR "
            "(photo IS NOT NULL AND created_at < now()-interval '7 days')))",
            issue,
            revision,
        ):
            await conn.execute("UPDATE part2_issues SET revision=revision+1 WHERE id=$1", issue)
            return "Срок хранения истёк. Пришлите решение целиком.", []
        work = await conn.fetch(
            """SELECT body,photo,media_group FROM part2_work
               WHERE issue_id=$1 AND revision=$2 AND NOT superseded ORDER BY message_id""",
            issue,
            revision,
        )
        if any(item["media_group"] for item in work):
            return "Альбом нельзя проверить частично. Уберите фото и пришлите один снимок.", []
        photo_count = sum(bool(item["photo"]) for item in work)
        if photo_count > 1:
            return "В черновике несколько фото. Ответьте на одно из них новым общим снимком.", []
        if not photo_count:
            return "Для проверки пришлите одно фото с ходом решения.", []
        notice = budget_notice(s, await budget_usage(conn, owner))
        if notice:
            return notice + " Работа сохранена.", []
        await conn.execute(
            """INSERT INTO part2_grades(issue_id,revision,model,prompt_version,rubric_version,
            status,reserved_usd) VALUES ($1,$2,$3,$4,$5,'pending',$6)""",
            issue,
            revision,
            s.oge_grading_model,
            PROMPT_VERSION,
            version,
            ceiling(s),
        )
        await conn.execute("UPDATE part2_issues SET revision=revision+1 WHERE id=$1", issue)
        return "", list(work)


async def mark_dispatched(
    pool: asyncpg.Pool, identity: int, revision: int, *, diagnostic: bool = False
) -> None:
    query = (
        """UPDATE part2_api_tests SET dispatched_at=clock_timestamp()
        WHERE owner=$1 AND confirmation=$2 AND status='pending' AND dispatched_at IS NULL
        RETURNING true"""
        if diagnostic
        else """UPDATE part2_grades SET dispatched_at=clock_timestamp()
        WHERE issue_id=$1 AND revision=$2 AND status='pending' AND dispatched_at IS NULL
        RETURNING true"""
    )
    if not await pool.fetchval(query, identity, revision):
        raise ValueError("No active reservation")


async def finish(
    pool: asyncpg.Pool,
    s: Settings,
    issue: int,
    revision: int,
    result: Grade | None,
    *,
    dispatched: bool,
    reason: str | None = None,
) -> None:
    report: dict[str, Any] | None = None
    inputs = outputs = None
    amount: Decimal | None = None if dispatched else Decimal(0)
    if result:
        assessment, inputs, outputs, model, amount = result
        report = {**assessment.model_dump(), "model_id": model, "prompt_version": PROMPT_VERSION}
    await pool.execute(
        """UPDATE part2_grades SET status=$3,score=$4,
        result=CASE WHEN $5::jsonb IS NULL THEN NULL ELSE
        $5::jsonb || jsonb_build_object('rubric_version',rubric_version) END,
        input_tokens=$6,output_tokens=$7,cost_usd=$8,failure_reason=$9
        WHERE issue_id=$1 AND revision=$2
        AND status='pending'""",
        issue,
        revision,
        report["status"] if report else "error",
        report["score"] if report else None,
        json.dumps(report) if report else None,
        inputs,
        outputs,
        amount,
        reason,
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
            "UPDATE part2_api_tests SET status='error', failure_reason='Проверка прервана' "
            "WHERE status='pending' AND created_at < now()-interval '10 minutes'"
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
