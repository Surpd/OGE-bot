"""One Telegram flow for all six written-response tasks."""

import asyncio
import hashlib
from typing import Any, Literal

from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.explicit_math import plain_text
from app.bot.presentation import hint_message, send_photo, send_text
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


TITLES = {
    20: "Уравнения и неравенства",
    21: "Текстовые задачи",
    22: "Графики функций",
    23: "Геометрические вычисления",
    24: "Доказательства",
    25: "Геометрические задачи",
}
PAGE_SIZE = 5
INTRO = (
    "Письменная тренировка\n\n"
    "Запишите ход решения на бумаге и пришлите одно чёткое фото. Чтобы заменить фото, "
    "ответьте на него "
    "новым снимком. Нажмите «Проверить решение» для предварительной оценки.\n\n"
    "Только при проверке снимок передаётся OpenAI. Не указывайте имя на работе."
)


def controls(row: dict[str, Any]) -> InlineKeyboardMarkup:
    issue, number = row["id"], row["number"]
    if row["solution_viewed_at"]:
        rows = [[("Разбор", f"p2:solution:{issue}"), ("Завершить", f"p2:finish:{issue}")]]
    else:
        rows = [
            [("Проверить решение", f"p2:check:{issue}")],
            [("Подсказка", f"p2:hint:{issue}"), ("Разбор", f"p2:solution:{issue}")],
            [
                ("Завершить", f"p2:finish:{issue}")
                if row["scored"]
                else ("Пропустить", f"p2:skip:{issue}"),
                ("К выбору", f"p2:menu:{number}"),
            ],
        ]
    if row["solution_viewed_at"]:
        rows.append([("К выбору", f"p2:menu:{number}")])
    if row["draft"] and not row["solution_viewed_at"]:
        rows.insert(1, [("Моя работа", f"p2:draft:{issue}")])
    return keyboard(rows)


def image_bytes(visual: dict[str, Any]) -> bytes:
    data = figure(visual["path"])
    if hashlib.sha256(data).hexdigest() != visual["sha256"]:
        raise ValueError("Atlas figure checksum mismatch")
    return data


async def card_message(
    message: Message,
    repo: Repository,
    owner: int,
    card: dict[str, Any],
    role: str,
    text: str,
    markup: InlineKeyboardMarkup,
) -> None:
    photos = [
        BufferedInputFile(await asyncio.to_thread(image_bytes, visual), filename=f"{role}.png")
        for visual in card["visuals"]
        if visual["role"] == role
    ]
    if photos:
        for extra in photos[:-1]:
            await message.answer_photo(extra)
        await send_photo(
            message,
            repo,
            photos[-1],
            caption=text,
            reply_markup=markup,
            user_id_override=owner,
            diagram_caption="Чертёж к условию" if role == "condition" else "Рисунок к разбору",
        )
    else:
        await send_text(
            message,
            repo,
            text,
            reply_markup=markup,
            user_id_override=owner,
            rich_with_navigation=True,
        )


def statement_text(card: dict[str, Any], status: str = "Пришлите решение одним фото.") -> str:
    number = card["number"]
    label = "\nУчебная задача" if card["bank_scope"] == "training_only" else ""
    return f"№{number} · {TITLES[number]}{label}\n\n{card['statement']}\n\n{status}"


def solution_text(card: dict[str, Any]) -> str:
    steps = "\n".join(f"{i}. {step}" for i, step in enumerate(card["solution_steps"], 1))
    return f"Разбор:\n\n{steps}\n\nОтвет: {card['answer_or_claim']}"


async def render(message: Message, repo: Repository, owner: int, row: dict[str, Any]) -> None:
    card = row["card"]
    repetition = "Повторная тренировка. " if row["repeat_kind"] else ""
    if row["solution_viewed_at"]:
        status = "Разбор открыт."
    elif row["draft"]:
        status = "Черновик сохранён."
    else:
        status = "Пришлите решение одним фото."
    await repo.save_user_state(owner, "part2")
    await card_message(
        message,
        repo,
        owner,
        card,
        "condition",
        statement_text(card, repetition + status),
        controls(row),
    )


async def resume(message: Message, repo: Repository, owner: int, issue: int | None = None) -> bool:
    bank = store(repo)
    row = await bank.current(owner, issue, activate=issue is not None) if bank else None
    if not row:
        return False
    if bank and await bank.show_intro(owner):
        await message.answer(INTRO)
    await render(message, repo, owner, row)
    return True


async def show_choices(
    message: Message,
    repo: Repository,
    bank: Part2Training,
    owner: int,
    number: int,
    page: int = 0,
    notice: str = "",
) -> None:
    choices = await bank.choices(number, owner)
    draft = await bank.unfinished(owner, number)
    page = min(page, max(0, (len(choices) - 1) // PAGE_SIZE))
    start = page * PAGE_SIZE
    lines = [f"№{number} · {TITLES[number]}"]
    if notice:
        lines.append(notice)
    rows = [[("Новая случайная", f"p2:open:{number}")]]
    if draft:
        callback = f"p2:resume:{draft[0]['id']}" if len(draft) == 1 else f"p2:drafts:{number}"
        rows.insert(0, [("Продолжить" if len(draft) == 1 else "Продолжить работу", callback)])
        lines.append(f"Сохранённые работы: {len(draft)}.")
    lines.append("Выберите тип. Справа указано, сколько задач вы ещё не получали.")
    indexes = []
    for index, choice in enumerate(choices[start : start + PAGE_SIZE], start + 1):
        lines.append(f"{index}. {choice['title']} · {choice['unseen']}/{choice['total']}")
        indexes.append((str(index), f"p2:open:{number}:{choice['subtype_id']}"))
    if indexes:
        rows.append(indexes)
    arrows = []
    if page:
        arrows.append(("←", f"p2:menu:{number}:{page - 1}"))
    if start + PAGE_SIZE < len(choices):
        arrows.append(("→", f"p2:menu:{number}:{page + 1}"))
    if arrows:
        rows.append(arrows)
    rows.append([("Как отправить решение", f"p2:intro:{number}"), ("К номерам", "nav:numbers")])
    await repo.save_user_state(owner, "part2_menu")
    await send_text(message, repo, "\n\n".join(lines), reply_markup=keyboard(rows))


async def show_drafts(
    message: Message, repo: Repository, bank: Part2Training, owner: int, number: int, page: int
) -> None:
    items = await bank.unfinished(owner, number)
    page = min(page, max(0, (len(items) - 1) // PAGE_SIZE))
    start = page * PAGE_SIZE
    lines = [f"№{number} · Сохранённые работы"]
    rows = []
    for index, issue in enumerate(items[start : start + PAGE_SIZE], start + 1):
        status = (
            "разбор открыт"
            if issue["solution_viewed_at"]
            else ("черновик" if issue["draft"] else "в работе")
        )
        statement = " ".join(plain_text(issue["statement"]).split())
        excerpt = statement if len(statement) <= 100 else statement[:97].rstrip() + "…"
        lines.append(f"{index}. {issue['title']} · {status}\n{excerpt}")
        rows.append((str(index), f"p2:resume:{issue['id']}"))
    buttons = [rows] if rows else []
    arrows = []
    if page:
        arrows.append(("←", f"p2:drafts:{number}:{page - 1}"))
    if start + PAGE_SIZE < len(items):
        arrows.append(("→", f"p2:drafts:{number}:{page + 1}"))
    if arrows:
        buttons.append(arrows)
    buttons.append([("К выбору", f"p2:menu:{number}"), ("К номерам", "nav:numbers")])
    await repo.save_user_state(owner, "part2_menu")
    await send_text(message, repo, "\n\n".join(lines), reply_markup=keyboard(buttons))


async def exhausted(
    message: Message,
    repo: Repository,
    number: int,
    subtype: str | None,
    notice: str = "",
) -> None:
    tail = f":{subtype}" if subtype else ""
    if message.from_user:
        await repo.save_user_state(message.from_user.id, "part2_menu")
    await send_text(
        message,
        repo,
        notice or "Новые задания здесь закончились. Выберите, что повторить.",
        reply_markup=keyboard(
            [
                [("Повторить ошибки", f"p2:r:{number}:e{tail}")],
                [("Вернуться к пропущенным", f"p2:r:{number}:s{tail}")],
                [("Повторить все", f"p2:r:{number}:a{tail}")],
                [("К выбору", f"p2:menu:{number}"), ("К номерам", "nav:numbers")],
            ]
        ),
    )


async def action(message: Message, repo: Repository, owner: int, data: str) -> None:
    if message.chat.type != "private":
        await message.answer("Отправляйте письменную работу в личном чате с ботом.")
        return
    bank = store(repo)
    if bank is None:
        await message.answer("Вторая часть сейчас недоступна. Откройте /start.")
        return
    parts = data.split(":")
    if len(parts) not in (3, 4, 5) or not (
        parts[2].isascii() and parts[2].isdigit() and len(parts[2]) <= 18
    ):
        return
    command, value = parts[1], int(parts[2])
    arg = parts[3] if len(parts) >= 4 else ""
    if command == "apitest" and len(parts) == 3:
        from app.bot.api_diagnostics import confirmed_test
        from app.bot.router import return_to_menu

        await confirmed_test(message, bank.pool, owner, value)
        if await repo.user_state(owner) == "api_test":
            await return_to_menu(message, repo, user_id_override=owner)
        return
    if command in {"menu", "drafts", "open", "r", "intro"} and value in TITLES:
        page = int(arg) if arg.isascii() and arg.isdigit() and len(arg) <= 3 else 0
        if command == "menu":
            await show_choices(message, repo, bank, owner, value, page)
        elif command == "drafts":
            await show_drafts(message, repo, bank, owner, value, page)
        elif command == "intro":
            await bank.show_intro(owner)
            await send_text(
                message,
                repo,
                INTRO,
                reply_markup=keyboard(
                    [[("К выбору", f"p2:menu:{value}"), ("К номерам", "nav:numbers")]]
                ),
            )
        elif command == "open" and len(parts) <= 4:
            subtype = arg or None
            if subtype and subtype not in {
                r["subtype_id"] for r in await bank.choices(value, owner)
            }:
                await show_choices(message, repo, bank, owner, value, notice="Этот тип недоступен.")
                return
            issue = await bank.open(owner, value, subtype)
            if issue is None:
                await exhausted(message, repo, value, subtype)
            else:
                await resume(message, repo, owner, issue)
        elif command == "r" and arg in ("e", "s", "a"):
            subtype = parts[4] if len(parts) == 5 else None
            if subtype and subtype not in {
                r["subtype_id"] for r in await bank.choices(value, owner)
            }:
                await show_choices(message, repo, bank, owner, value, notice="Этот тип недоступен.")
                return
            repeat: Literal["errors", "skipped", "all"] = (
                "errors" if arg == "e" else "skipped" if arg == "s" else "all"
            )
            issue = await bank.open(owner, value, subtype, repeat=repeat)
            if issue is None:
                await exhausted(
                    message,
                    repo,
                    value,
                    subtype,
                    "Для этого повтора нет завершённых работ. Проверьте сохранённые задания "
                    "или выберите другой вариант.",
                )
            else:
                await resume(message, repo, owner, issue)
        return
    if len(parts) != 3:
        return
    row = await bank.current(owner, value if value else None)
    if row is None or row["id"] != value:
        await send_text(
            message,
            repo,
            "Эта работа уже завершена. Выберите номер.",
            reply_markup=keyboard([[("К номерам", "nav:numbers")]]),
        )
        return
    number = row["number"]
    if command == "resume":
        await resume(message, repo, owner, value)
    elif command == "draft":
        from app.bot.part2_progress import page as written_page

        await repo.save_user_state(owner, "part2_menu")
        await written_page(
            message,
            repo,
            owner,
            ["work", str(value), str(row["revision"]), "0"],
            resume_issue=True,
        )
    elif command == "next":
        await show_choices(message, repo, bank, owner, number)
    elif command == "skip":
        await repo.save_user_state(owner, "part2_menu")
        skipped = await bank.skip(owner, value, row["revision"])
        await show_choices(
            message,
            repo,
            bank,
            owner,
            number,
            notice="Задача пропущена." if skipped else "Эту работу уже проверяют или завершили.",
        )
    elif command == "finish":
        await repo.save_user_state(owner, "part2_menu")
        await bank.finish(owner, value)
        await show_choices(message, repo, bank, owner, number)
    elif command in {"solution", "reveal"}:
        if not row["solution_viewed_at"] and command == "solution":
            await send_text(
                message,
                repo,
                "После открытия разбора эту работу уже нельзя будет проверить как самостоятельную.",
                reply_markup=keyboard(
                    [
                        [("Открыть разбор", f"p2:reveal:{value}")],
                        [("К заданию", f"p2:resume:{value}")],
                    ]
                ),
            )
            return
        await bank.pool.execute(
            """UPDATE part2_issues SET solution_viewed_at=coalesce(solution_viewed_at,now())
               WHERE id=$1 AND owner=$2 AND NOT closed""",
            value,
            owner,
        )
        revealed = await bank.current(owner, value)
        if revealed:
            card = row["card"]
            text = solution_text(card)
            await card_message(message, repo, owner, card, "solution", text, controls(revealed))
    elif command == "hint" and not row["solution_viewed_at"]:
        used = await bank.pool.fetchval(
            """UPDATE part2_issues SET hints=least(2,hints+1)
               WHERE owner=$1 AND id=$2 AND NOT closed AND solution_viewed_at IS NULL
               RETURNING hints""",
            owner,
            value,
        )
        if used:
            await send_text(
                message,
                repo,
                hint_message(row["card"]["hints"][used - 1], row["card"]),
                reply_markup=controls(row),
                rich_with_navigation=True,
            )
    elif command == "check":
        from app.bot.part2_check import check

        await check(message, repo, owner, row, bank)


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
    if photo is None:
        await message.answer("Запишите решение на бумаге и пришлите его одним фото.")
        return
    if photo.file_size is None or photo.file_size > 4_000_000:
        await message.answer("Пришлите фотографию решения до 4 МБ.")
        return
    reply = message.reply_to_message
    result = await bank.append(
        actor.id,
        row["id"],
        row["revision"],
        message.message_id,
        message.caption,
        photo.file_id,
        message.media_group_id,
        replace_photo=reply.message_id if reply and reply.photo else None,
    )
    if result == "photo_limit":
        await message.answer(
            "Для одной работы можно прикрепить только одну фотографию. "
            "Можете заменить предыдущий снимок. Для этого отправьте новый снимок ответом "
            "на предыдущее фото."
        )
    elif result == "saved":
        await message.answer("Добавлено к решению.")
    elif result == "stale":
        await message.answer("Фото не добавлено. Проверьте текущее задание и лимит.")
