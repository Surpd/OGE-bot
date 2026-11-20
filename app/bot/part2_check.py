"""Explicit, bounded checking of the saved revision. No paid retries on redelivery."""

import asyncio
import io
from typing import Any

from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message
from openai import APIError, AsyncOpenAI
from PIL import UnidentifiedImageError

from app.bot.part2 import controls, image_bytes
from app.bot.presentation import send_text
from app.config import get_settings
from app.part2_grading import assess, available, clean_photo, inputs
from app.persistence.part2_grades import finish, reserve
from app.persistence.part2_training import Part2Training
from app.persistence.repository import Repository


async def check(
    message: Message, repo: Repository, owner: int, row: dict[str, Any], bank: Part2Training
) -> None:
    s = get_settings()
    issue, revision = row["id"], row["revision"]
    if not available(s) or s.openai_api_key is None:
        await send_text(
            message,
            repo,
            "Автопроверка временно недоступна. Работа сохранена.",
            reply_markup=controls(issue),
        )
        return
    notice, work = await reserve(bank.pool, s, owner, issue, revision)
    if notice:
        await send_text(message, repo, notice, reply_markup=controls(issue))
        return
    dispatched = False
    result = None
    try:
        await message.answer("Проверяю ход решения по критериям задания…")
        async with asyncio.timeout(s.oge_grading_timeout_seconds):
            photos = []
            for item in work:
                if item["photo"]:
                    if not message.bot:
                        raise ValueError("Missing bot")
                    file = await message.bot.get_file(item["photo"])
                    if not file.file_path or not file.file_size or file.file_size > 4_000_000:
                        raise ValueError("Photo unavailable")
                    buf = io.BytesIO()
                    await message.bot.download_file(file.file_path, destination=buf)
                    photos.append(await asyncio.to_thread(clean_photo, buf.getvalue()))
            refs = [await asyncio.to_thread(image_bytes, v) for v in row["card"]["visuals"]]
            content = await asyncio.to_thread(
                inputs, row["card"], refs, [r["body"] for r in work if r["body"]], photos
            )
            async with AsyncOpenAI(
                api_key=s.openai_api_key.get_secret_value(),
                max_retries=0,
                timeout=s.oge_grading_timeout_seconds,
            ) as client:
                dispatched = True
                result = await assess(client, s.oge_grading_model, content)
    except (APIError, TelegramAPIError, ValueError, TimeoutError, OSError, UnidentifiedImageError):
        pass
    finally:
        await finish(bank.pool, s, issue, revision, result, dispatched=dispatched)
    if result is None:
        reply = "Проверка не завершилась. Балл не выставлен. Можно прислать работу ещё раз."
    else:
        assessment = result[0]
        label = (
            f"Предварительная оценка: {assessment.score}/2"
            if assessment.status == "graded"
            else "Балл не выставлен"
        )
        reply = "\n\n".join(
            filter(
                None,
                [
                    label,
                    assessment.feedback,
                    "\n".join(assessment.correct_steps),
                    "\n".join(assessment.errors),
                    assessment.next_step,
                    "Чтобы исправить работу, пришлите новое решение целиком.",
                ],
            )
        )
    active = await bank.current(owner, issue)
    if await repo.user_state(owner) == "part2" and active:
        await send_text(message, repo, reply[:3200], reply_markup=controls(issue))
    else:
        await message.answer(reply[:3200], parse_mode=None)
