"""One Telegram flow for all six written-response tasks."""

import asyncio
import hashlib
from typing import Any

from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.presentation import send_text
from app.config import get_settings
from app.persistence.part2_bank import figure
from app.persistence.part2_training import Part2Training
from app.persistence.repository import PostgresRepository, Repository


def store(repository: Repository) -> Part2Training | None:
    if get_settings().oge_part2_enabled and isinstance(repository, PostgresRepository):
        return Part2Training(repository._pool)
    return None


def keyboard(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=text, callback_data=data) for text, data in row]
            for row in rows
        ]
    )


def controls(issue: int) -> InlineKeyboardMarkup:
    return keyboard(
        [
            [("Проверить решение", f"p2:check:{issue}"), ("Подсказка", f"p2:hint:{issue}")],
            [("Следующее", f"p2:next:{issue}"), ("В меню", "nav:main")],
        ]
    )


def image_bytes(visual: dict[str, Any]) -> bytes:
    data = figure(visual["path"])
    if hashlib.sha256(data).hexdigest() != visual["sha256"]:
        raise ValueError("Atlas figure checksum mismatch")
    return data


async def render(message: Message, repo: Repository, owner: int, row: dict[str, Any]) -> None:
    card = row["card"]
    for v in card["visuals"]:
        if v["role"] == "condition":
            data = await asyncio.to_thread(image_bytes, v)
            await message.answer_photo(BufferedInputFile(data, filename="condition.png"))
    label = " · авторская тренировка" if card["bank_scope"] == "training_only" else ""
    await repo.save_user_state(owner, "part2")
    await send_text(
        message,
        repo,
        f"Задание №{row['number']}{label}\n\n{card['statement']}\n\n"
        "Пришлите решение текстом или фотографиями, затем нажмите «Проверить решение».",
        reply_markup=controls(row["id"]),
        user_id_override=owner,
        rich_with_navigation=True,
    )


async def resume(message: Message, repo: Repository, owner: int) -> bool:
    bank = store(repo)
    row = await bank.current(owner) if bank else None
    if not row:
        return False
    await render(message, repo, owner, row)
    return True


async def action(message: Message, repo: Repository, owner: int, data: str) -> None:
    if message.chat.type != "private":
        await message.answer("Отправляйте письменную работу в личном чате с ботом.")
        return
    bank = store(repo)
    if bank is None:
        await message.answer("Вторая часть сейчас недоступна. Откройте /start.")
        return
    parts = data.split(":")
    if len(parts) not in (3, 4) or not parts[2].isascii() or not parts[2].isdigit():
        return
    command, value = parts[1], int(parts[2])
    if command in {"menu", "open"} and value in range(20, 26):
        choices = await bank.choices(value)
        if command == "menu":
            await repo.save_user_state(owner, "part2_menu")
            rows = (
                [[("Случайное задание / продолжить", f"p2:open:{value}")]]
                if choices
                else [[("Обновить", f"p2:menu:{value}")]]
            )
            for choice in choices:
                rows.append([(choice["title"], f"p2:open:{value}:{choice['subtype_id']}")])
            rows.append([("К номерам", "nav:numbers")])
            await send_text(
                message,
                repo,
                f"Задание №{value}. Выберите тип."
                if choices
                else "Проверенные карточки пока недоступны.",
                reply_markup=keyboard(rows),
            )
            return
        subtype = parts[3] if len(parts) == 4 else None
        if subtype is not None and subtype not in {r["subtype_id"] for r in choices}:
            return
        if await bank.open(owner, value, subtype):
            await resume(message, repo, owner)
        return
    row = await bank.current(owner, value)
    if not row:
        await message.answer("Задание уже сменилось. Откройте его через меню.")
        return
    if command == "next":
        if await bank.open(owner, row["number"], replace=value):
            await resume(message, repo, owner)
    elif command == "hint":
        used = await bank.pool.fetchval(
            "UPDATE part2_issues SET hints=least(2,hints+1) WHERE owner=$1 AND id=$2"
            " AND NOT closed RETURNING hints",
            owner,
            value,
        )
        if used:
            await send_text(
                message,
                repo,
                row["card"]["hints"][used - 1],
                reply_markup=controls(value),
                rich_with_navigation=True,
            )
    elif command == "check":
        await send_text(
            message,
            repo,
            "Проверка пока недоступна. Работа сохранена.",
            reply_markup=controls(value),
        )


async def collect(message: Message, repository: Repository) -> None:
    bank = store(repository)
    actor = message.from_user
    if message.chat.type != "private":
        raise SkipHandler
    if bank is None or actor is None or await repository.user_state(actor.id) != "part2":
        raise SkipHandler
    row = await bank.current(actor.id)
    if row is None:
        raise SkipHandler
    photo = message.photo[-1] if message.photo else None
    body = message.caption if photo else message.text
    if (photo and (photo.file_size is None or photo.file_size > 4_000_000)) or (
        body and len(body) > 4000
    ):
        await message.answer("Пришлите до 4000 знаков или фотографию до 4 МБ.")
        return
    saved = await bank.append(
        actor.id,
        row["id"],
        row["revision"],
        message.message_id,
        body,
        photo.file_id if photo else None,
        get_settings().oge_grading_max_images,
        message.media_group_id,
    )
    await message.answer(
        "Добавлено к решению."
        if saved
        else "Фото или текст не добавлены. Проверьте текущее задание и лимит."
    )
