"""Required inputs from the saved scenario, delivered before its question."""
from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping
from textwrap import fill

from aiogram.exceptions import TelegramAPIError
from aiogram.types import BufferedInputFile, InlineKeyboardMarkup, Message

from app.bot.math_layout import TrainingMessage
from app.bot.presentation import send_photo, send_text
from app.math.scenario_engine import ScenarioSnapshot
from app.math.scenarios.mobile_photos import _photo_indexes, scenario_photos_for_question, table
from app.math.scenarios.stories import GARDEN, STOVE
from app.persistence.repository import Repository

MATERIALS_UNAVAILABLE = (
    "Не удалось загрузить обязательные данные задачи. "
    "Открой меню и нажми «Продолжить». "
    "Для повтора ошибки снова открой задачу в списке ошибок."
)


def scenario_context_for_question(snapshot: ScenarioSnapshot, position: int) -> str:
    context = snapshot.shared_context
    question = next(
        item for item in snapshot.questions if item.position == position
    )
    if snapshot.story_code == "TYRES":
        context = "\n".join(
            line for line in context.splitlines()
            if not line.startswith(("|", "В таблице приведены разрешённые размеры шин:"))
        )
        context = context.replace("**", "")
    elif snapshot.story_code == "PAPER":
        context = context.partition("Таблица размеров")[0].rstrip()
    elif snapshot.story_code == "STOVE":
        context = context.partition("Печь | Тип |")[0].rstrip()
    elif snapshot.story_code == "TARIFF":
        context = "\n".join(
            line for line in context.splitlines()
            if not line.startswith((
                "Минуты по месяцам:", "Мобильный интернет по месяцам:",
            ))
        )
    elif snapshot.story_code == "GARDEN" and snapshot.generator_version in {
        "garden-sosnovka-1.0", "garden-sosnovka-1.1",
    }:
        context += (
            "\nДом с выступом у верхней границы. Баня ниже яблонь слева, "
            "гараж ниже ворот справа, теплица внутри огорода."
        )
    elif snapshot.story_code == "GARDEN" and question.family_id != "GARDEN-09-HEAT-BREAKEVEN":
        prefix, separator, remainder = context.partition("Отопление одного дома")
        if separator:
            _, shared_questions, closing = remainder.partition("Все пять вопросов")
            context = prefix + ("\nВсе пять вопросов" + closing if shared_questions else "")
    if (
        snapshot.story_code == "GARDEN"
        and snapshot.generator_version in GARDEN.SOURCE_PLAN_VERSIONS
        and snapshot.generator_version != GARDEN.VERSION
        and position == 3
    ):
        context += "\nЖилой дом — здание с выступом у верхней стороны плана."
    if snapshot.story_code == "FLAT":
        context = context.replace("Это собственная SVG/PNG схема фиксированной топологии.", "")
        if "первая лоджия" in snapshot.questions[2].condition:
            context += " На плане первая лоджия расположена слева."
    context = re.sub(r"Все пять вопросов относятся к [^.]+\.\s*", "", context)
    return re.sub(r"\n{3,}", "\n\n", context.replace("Аналог ОГЭ.", "")).strip()


def answer_grid_photo(snapshot: ScenarioSnapshot, position: int) -> bytes | None:
    question = snapshot.questions[position - 1]
    grid = question.math_model.get("answer_grid")
    if grid is None:
        return None
    if not isinstance(grid, Mapping):
        raise ValueError("Invalid answer grid")
    columns, header, row = grid.get("columns"), grid.get("header"), grid.get("row")
    if not (
        isinstance(columns, list | tuple) and 2 <= len(columns) <= 6
        and all(isinstance(label, str) and label.strip() for label in columns)
        and isinstance(header, str) and isinstance(row, str) and header and row
    ):
        raise ValueError("Invalid answer grid labels")
    width = 690 // len(columns)
    labels = [fill(str(label), max(9, width // 17), break_on_hyphens=False) for label in columns]
    return table(
        "Таблица для ответа",
        [[header, *labels], [fill(row, 14), *("" for _ in columns)]],
        (250, *(width for _ in columns)),
    )


def prepare_scenario_materials(
    snapshot: ScenarioSnapshot, position: int, *, previous_position: int | None = None,
) -> tuple[str, tuple[bytes, ...]]:
    context = scenario_context_for_question(snapshot, position)
    if previous_position is not None:
        if context == scenario_context_for_question(snapshot, previous_position):
            context = ""
    grid = answer_grid_photo(snapshot, position)
    try:
        photos = (
            scenario_photos_for_question(snapshot, position)
            if previous_position is None
            else scenario_photos_for_question(
                snapshot, position, previous_position=previous_position,
            )
        )
        return context, (*photos, grid) if grid is not None else photos
    except (ValueError, RuntimeError, OSError):
        # A catalogue can be transcribed without doing any student calculation.
        # Plans/charts and PAPER's unlabeled matching table cannot be replaced
        # with derived answers or the labeled internal shared_context.
        if snapshot.story_code != "STOVE" or _photo_indexes(snapshot, position) != (0,):
            raise
        rows = [
            f"Печь №{r['id']}: {r['kind']}; объём {r['min_m3']}–{r['max_m3']} м³; "
            f"масса {r['mass_kg']} кг; цена {r['price_rub']} руб."
            for r in STOVE._rows(snapshot.context)
        ]
        return context + "\n\nКаталог печей\n" + "\n".join(rows), (grid,) if grid else ()


async def send_scenario_materials(
    message: Message, repository: Repository | None, snapshot: ScenarioSnapshot,
    position: int, *, user_id: int | None, previous_position: int | None = None,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> bool:
    async def text(body: str, markup: InlineKeyboardMarkup | None = None) -> None:
        if repository is None:
            await message.answer(body, reply_markup=markup)
        else:
            await send_text(message, repository, body, user_id_override=user_id,
                            math_family=next(q.family_id for q in snapshot.questions
                                             if q.position == position), reply_markup=markup)

    try:
        context, photos = await asyncio.to_thread(
            prepare_scenario_materials, snapshot, position, previous_position=previous_position,
        )
        if context:
            await text(TrainingMessage(("context", context)), reply_markup if not photos else None)
        for index, data in enumerate(photos, 1):
            upload = BufferedInputFile(data, filename=f"scenario-{index}.png")
            markup = reply_markup if index == len(photos) else None
            if repository is None:
                await message.answer_photo(upload, caption=f"Данные задачи №{position}",
                                           reply_markup=markup)
            else:
                await send_photo(message, repository, upload,
                                 caption=f"Данные задачи №{position}",
                                 user_id_override=user_id, reply_markup=markup)
    except (TelegramAPIError, OSError, ValueError, RuntimeError):
        # Do not blindly resend a photo after an ambiguous network failure.
        # Never continue to the question without all of its required inputs.
        await text(MATERIALS_UNAVAILABLE, reply_markup)
        return False
    return True
