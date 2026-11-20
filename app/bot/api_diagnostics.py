"""Private, read-only account status and a separately metered, confirmed test."""

import asyncio
import json
from time import monotonic

import asyncpg
from aiogram.types import Message
from openai import APIError, APIStatusError

from app.bot.part2 import keyboard
from app.bot.presentation import send_text
from app.config import Settings, get_settings
from app.part2_grading import (
    MODEL,
    assess,
    available,
    ceiling,
    check_size,
    failure_reason,
    inputs,
    open_client,
)
from app.persistence.part2_grades import budget_notice, budget_usage, reserve_test
from app.persistence.repository import PostgresRepository, Repository

TEST_ID = "oge-part2-reshu-438301"
TEST_WORK = (
    "Перенесу всё влево: (x+1)(x²+x−2)=0, то есть (x+1)(x+2)(x−1)=0. "
    "Произведение равно нулю тогда и только тогда, когда один из множителей равен нулю. "
    "Все три значения допустимы. Ответ: −2, −1, 1."
)


async def model_status(s: Settings) -> str:
    if not s.openai_api_key:
        return "ключ отсутствует"
    if s.oge_grading_model != MODEL:
        return "модель не поддерживается"
    try:
        async with asyncio.timeout(8), open_client(s) as client:
            model = await client.models.retrieve(MODEL)
        return "доступна" if model.id == MODEL else "метаданные не подтвердили модель"
    except (APIError, TimeoutError, ValueError) as exc:
        return failure_reason(exc)


async def api_status(message: Message, repository: Repository) -> None:
    if message.chat.type != "private" or not message.from_user:
        return
    s = get_settings()
    meta = await model_status(s)
    lines = [
        f"Ключ OpenAI: {'есть' if s.openai_api_key else 'нет'}",
        f"Модель: {s.oge_grading_model} · {meta}",
        f"GPT-проверка: {'включена' if s.oge_grading_enabled else 'выключена'}",
        f"Месячный бюджет бота: ${s.oge_grading_monthly_budget_usd}",
    ]
    if isinstance(repository, PostgresRepository):
        pool, owner = repository._pool, message.from_user.id
        u = await budget_usage(pool, owner)
        remaining = max(0, s.oge_grading_monthly_budget_usd - u["spent"] - u["held"])
        last = await pool.fetchrow(
            """SELECT * FROM (SELECT g.created_at,g.status,g.failure_reason FROM part2_grades g
               JOIN part2_issues i ON i.id=g.issue_id WHERE i.owner=$1 UNION ALL SELECT
               created_at,status,failure_reason FROM part2_api_tests WHERE owner=$1) entries
               ORDER BY created_at DESC LIMIT 1""",
            owner,
        )
        lines.extend(
            [
                f"Учтено: ${u['spent']:.6f} · в резерве: ${u['held']:.6f}",
                f"Остаток бюджета бота: ${remaining:.6f}",
                f"Сегодня: {u['daily']}/{s.oge_grading_daily_user_limit}",
                "Последняя проверка: "
                + (
                    f"{last['created_at']:%d.%m %H:%M} UTC · "
                    f"{last['failure_reason'] or last['status']}"
                    if last
                    else "ещё не было"
                ),
            ]
        )
        notice = budget_notice(s, u)
        if notice:
            lines.append(notice)
    lines.append("Баланс API-кредитов: проверьте в OpenAI Platform.")
    await message.answer("\n".join(lines))


async def api_test(message: Message, repository: Repository) -> None:
    if message.chat.type != "private" or not message.from_user:
        return
    s = get_settings()
    if not available(s) or not isinstance(repository, PostgresRepository):
        await message.answer("Тест сейчас недоступен. Причина и бюджет — /api_status.")
        return
    notice = budget_notice(s, await budget_usage(repository._pool, message.from_user.id))
    if notice:
        await message.answer(notice)
        return
    await repository.register_user(message.from_user.id)
    await repository.save_user_state(message.from_user.id, "api_test")
    await send_text(
        message,
        repository,
        f"Проверить готовое решение №20? Будет один платный запрос к {MODEL}. "
        f"Максимальный резерв ${ceiling(s):.5f}.",
        reply_markup=keyboard(
            [
                [("Подтвердить платный тест", f"p2:apitest:{message.message_id}")],
                [("В меню", "nav:main")],
            ]
        ),
    )


async def confirmed_test(
    message: Message, pool: asyncpg.Pool, owner: int, confirmation: int
) -> None:
    s = get_settings()
    if not available(s):
        await message.answer("Проверка выключена или ключ не настроен. /api_status")
        return
    payload = await pool.fetchval(
        "SELECT payload FROM part2_versions WHERE task_id=$1 AND version=2 AND reviewed", TEST_ID
    )
    if not payload:
        await message.answer("Контрольная версия задачи недоступна.")
        return
    notice = await reserve_test(pool, s, owner, confirmation)
    if notice:
        await message.answer(notice)
        return
    result = None
    reason = None
    sent = False
    start = monotonic()
    try:
        async with asyncio.timeout(s.oge_grading_timeout_seconds), open_client(s) as client:
            work = inputs(json.loads(payload), [], [TEST_WORK], [])
            await check_size(client, s, work)
            sent = True
            result = await assess(client, MODEL, work)
    except (APIError, TimeoutError, ValueError) as exc:
        reason = failure_reason(exc)
        if isinstance(exc, APIStatusError) and exc.status_code in (400, 401, 403, 404, 429):
            sent = False
    finally:
        elapsed = round((monotonic() - start) * 1000)
        await pool.execute(
            """UPDATE part2_api_tests SET status=$3,cost_usd=$4,input_tokens=$5,
            output_tokens=$6,score=$7,failure_reason=$8,elapsed_ms=$9
            WHERE owner=$1 AND confirmation=$2 AND status='pending'""",
            owner,
            confirmation,
            result.assessment.status if result else "error",
            result.amount if result else (None if sent else 0),
            result.inputs if result else None,
            result.outputs if result else None,
            result.assessment.score if result else None,
            reason,
            elapsed,
        )
    if result:
        score = (
            f"{result.assessment.score}/2" if result.assessment.score is not None else "без балла"
        )
        await message.answer(
            f"Тест №20 · {result.assessment.status} · {score}\n"
            f"Вход: {result.inputs}, выход: {result.outputs} токенов\n"
            f"Стоимость: ${result.amount:.7f} · {elapsed / 1000:.1f} с\n"
            + result.assessment.feedback,
            parse_mode=None,
        )
    else:
        await message.answer(f"Тест не завершён. {reason} Учёт резерва — /api_status.")
