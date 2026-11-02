"""Optional family selection; preferences apply only to the next generated task."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.presentation import send_text
from app.bot.training_engine import NUMERIC_TRAININGS
from app.persistence.repository import Repository
from app.persistence.training_insights import family_name


def _button(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def family_keyboard(number: int) -> InlineKeyboardMarkup:
    adapter = NUMERIC_TRAININGS[number]
    rows = [[_button("🎲 Все типы", f"nav:family:{number}:random")]]
    rows.extend(
        [_button(family_name(family), f"nav:family:{number}:{index}")]
        for index, family in enumerate(adapter.families)
    )
    rows.append([_button("← К номерам", "nav:numbers")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def selected_keyboard(number: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button(f"▶ Открыть №{number}", f"nav:begin:{number}")],
            [_button("Выбрать тип", f"nav:families:{number}"), _button("В меню", "nav:main")],
        ]
    )


async def show_families(message: Message, repository: Repository, number: int) -> None:
    if message.from_user is None:
        return
    await repository.save_user_state(message.from_user.id, f"family_selection:{number}")
    selected = await repository.training_family(message.from_user.id, number)
    current = family_name(selected) if selected else "Все типы"
    await send_text(
        message,
        repository,
        f"Задание №{number} · выберите тип\nСейчас: {current}\n\n"
        "Выбор применяется к следующим заданиям. Сохранённая задача остаётся прежней.",
        reply_markup=family_keyboard(number),
    )


async def select_family(
    message: Message, repository: Repository, number: int, selection: str
) -> None:
    if message.from_user is None:
        return
    families = NUMERIC_TRAININGS[number].families
    if selection == "random":
        family = None
    elif selection.isascii() and selection.isdigit() and int(selection) < len(families):
        family = families[int(selection)]
    else:
        await show_families(message, repository, number)
        return
    await repository.save_user_state(message.from_user.id, f"family_selection:{number}")
    await repository.set_training_family(message.from_user.id, number, family)
    label = family_name(family) if family else "Все типы"
    await send_text(
        message,
        repository,
        f"№{number} · {label}\n\n"
        "Настройка сохранена для следующих заданий. Если есть текущая задача, "
        "она продолжится с прежними попытками и подсказками.",
        reply_markup=selected_keyboard(number),
    )


async def family_exhausted(
    message: Message, repository: Repository, user_id: int, number: int
) -> None:
    await repository.save_user_state(user_id, f"family_selection:{number}")
    await send_text(
        message,
        repository,
        "Не удалось подготовить новый вариант выбранного типа. "
        "Текущая задача сохранена. Выберите другой тип или «Все типы».",
        reply_markup=family_keyboard(number),
        user_id_override=user_id,
    )
