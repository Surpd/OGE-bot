"""Explicit, bounded checking of the saved revision. No paid retries on redelivery."""

import asyncio
import io
from typing import Any

from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message
from openai import APIError
from PIL import UnidentifiedImageError

from app.bot.explicit_math import display_feedback
from app.bot.part2 import controls, image_bytes
from app.bot.presentation import has_mathematics, send_text
from app.config import get_settings
from app.part2_grading import (
    Assessment,
    assess,
    available,
    check_size,
    clean_photo,
    failure_reason,
    inputs,
    open_client,
)
from app.persistence.part2_grades import finish, mark_dispatched, reserve
from app.persistence.part2_training import Part2Training
from app.persistence.repository import Repository


async def check(
    message: Message,
    repo: Repository,
    owner: int,
    row: dict[str, Any],
    bank: Part2Training,
    *,
    photo_message: int | None = None,
) -> None:
    s = get_settings()
    issue, revision = row["id"], row["revision"]
    if not available(s) or s.openai_api_key is None:
        await send_text(
            message,
            repo,
            "Автопроверка временно недоступна. Работа сохранена.",
            reply_markup=controls(row),
        )
        return
    notice, work = await reserve(bank.pool, s, owner, issue, revision, photo_message=photo_message)
    if notice:
        await send_text(message, repo, notice, reply_markup=controls(row))
        return
    reason = None
    dispatched = False
    result = None
    try:
        await message.answer("Проверяю решение…")
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
            refs = [
                await asyncio.to_thread(image_bytes, v)
                for v in row["card"]["visuals"]
                if v["role"] == "condition"
            ]
            content = await asyncio.to_thread(inputs, row["card"], refs, [], photos)
            async with open_client(s) as client:
                await check_size(client, s, content)
                await mark_dispatched(bank.pool, issue, revision)
                dispatched = True
                result = await assess(client, s, row["card"], content)
    except (
        APIError,
        TelegramAPIError,
        ValueError,
        TimeoutError,
        OSError,
        UnidentifiedImageError,
    ) as exc:
        reason = failure_reason(exc)
    finally:
        if result and result.assessment.status == "error":
            reason = result.assessment.feedback
        await finish(bank.pool, s, issue, revision, result, dispatched=dispatched, reason=reason)
    reply = (
        f"{reason} Работа сохранена, балл не выставлен."
        if result is None
        else grading_reply(result.assessment, row["card"]["rubric"]["kind"])
    )
    active = await bank.current(owner)
    markup = (
        controls(active)
        if (await repo.user_state(owner) == "part2" and active and active["id"] == issue)
        else None
    )
    own = await bank.current(owner, issue)
    if result is not None and result.assessment.score is not None:
        reply += "\n\nПроверка сохранена в «Письменных работах»."
    reply += "\n\nЗадача открыта. «Завершить» закрывает задание." if own else "\n\nЗадача закрыта."
    if own and (result is None or result.assessment.score is None):
        reply += (
            "\nОтправьте одно чёткое фото решения ответом на сообщение с заданием. "
            "Затем нажмите «Проверить решение»."
        )
    await send_text(
        message,
        repo,
        reply,
        reply_markup=markup,
        user_id_override=owner,
        rich_with_navigation=True,
        text_on_photo_rejection=result is not None,
        math_family="written-feedback" if has_mathematics(reply) else None,
    )


def grading_reply(assessment: Assessment, rubric_kind: str) -> str:
    if assessment.score is None:
        status = {
            "unreadable": "Не удалось прочитать решение.",
            "uncertain": "Не удалось уверенно оценить решение.",
            "error": "Проверка не завершилась.",
        }.get(assessment.status, "Не удалось оценить решение.")
        return f"{status} Балл не выставлен.\n\n{display_feedback(assessment.feedback, 800)}"
    score = assessment.score
    evidence = [
        f"{item.criterion} — {item.student_evidence}" for item in assessment.criterion_evidence
    ]
    points = ("0 баллов", "1 балл", "2 балла")[score]
    blocks = [
        ("Что правильно", "\n".join(assessment.correct_steps)),
        ("Где ошибка", "\n".join(assessment.errors) if score < 2 else ""),
        (f"Почему именно {points}", "\n".join([assessment.feedback, *evidence])),
        ("Как исправить", assessment.next_step if score < 2 else ""),
    ]
    rubric = (
        "Критерии демоверсии ФИПИ"
        if rubric_kind == "fipi_demo_summary"
        else "Учебные критерии карточки"
    )
    return "\n\n".join(
        [
            f"Оценка: {score} из 2 баллов (предварительная)\n{rubric}",
            *(f"{title}: {display_feedback(body, 650)}" for title, body in blocks if body),
        ]
    )
