"""Required inputs from the saved scenario, delivered before its question."""
from __future__ import annotations

import asyncio

from aiogram.exceptions import TelegramAPIError
from aiogram.types import BufferedInputFile, Message

from app.bot.presentation import send_photo, send_text
from app.math.scenario_engine import ScenarioSnapshot
from app.math.scenarios.mobile_photos import _photo_indexes, scenario_photos_for_question
from app.math.scenarios.stories import STOVE
from app.persistence.repository import Repository

MATERIALS_UNAVAILABLE = (
    "Не удалось загрузить обязательные данные задачи. "
    "Повторите загрузку: /start → Продолжить. "
    "Для повтора ошибки снова откройте эту задачу в списке ошибок."
)


def scenario_context_for_question(snapshot: ScenarioSnapshot, position: int) -> str:
    context = snapshot.shared_context
    question = next(
        item for item in snapshot.questions if item.position == position
    )
    if snapshot.story_code == "TYRES":
        context = "\n".join(line for line in context.splitlines() if not line.startswith("|"))
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
    elif snapshot.story_code == "FLAT":
        context = context.replace("Это собственная SVG/PNG схема фиксированной топологии.", "")
        if "первая лоджия" in snapshot.questions[2].condition:
            context += " На плане первая лоджия расположена слева."
    return context



def prepare_scenario_materials(
    snapshot: ScenarioSnapshot, position: int,
) -> tuple[str, tuple[bytes, ...]]:
    context = scenario_context_for_question(snapshot, position)
    try:
        return context, scenario_photos_for_question(snapshot, position)
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
        return context + "\n\nКаталог печей\n" + "\n".join(rows), ()


async def send_scenario_materials(
    message: Message, repository: Repository | None, snapshot: ScenarioSnapshot,
    position: int, *, user_id: int | None,
) -> bool:
    async def text(body: str) -> None:
        if repository is None:
            await message.answer(body)
        else:
            await send_text(message, repository, body, user_id_override=user_id,
                            math_family=next(q.family_id for q in snapshot.questions
                                             if q.position == position))

    try:
        context, photos = await asyncio.to_thread(prepare_scenario_materials, snapshot, position)
        await text(context)
        for index, data in enumerate(photos, 1):
            upload = BufferedInputFile(data, filename=f"scenario-{index}.png")
            if repository is None:
                await message.answer_photo(upload, caption=f"Данные задачи №{position}")
            else:
                await send_photo(message, repository, upload,
                                 caption=f"Данные задачи №{position}",
                                 user_id_override=user_id)
    except (TelegramAPIError, OSError, ValueError, RuntimeError):
        # Do not blindly resend a photo after an ambiguous network failure.
        # Never continue to the question without all of its required inputs.
        await text(MATERIALS_UNAVAILABLE)
        return False
    return True
