from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

MAIN_MENU = (
    "⚡ 5 минут",
    "🧮 По номеру",
    "🔁 Мои ошибки",
    "🏆 Марафон",
    "📊 Прогресс",
    "📚 Как решать",
    "▶ Продолжить",
)

TASK6_MENU = (
    "💡 Подсказка",
    "📘 Разбор",
    "➡ Следующее",
    "⏭ Пропустить",
    "↩ В меню",
)


def main_menu(*, has_session: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text="⚡ 5 минут"), KeyboardButton(text="🧮 По номеру")],
        [KeyboardButton(text="🔁 Мои ошибки"), KeyboardButton(text="🏆 Марафон")],
        [KeyboardButton(text="📊 Прогресс"), KeyboardButton(text="📚 Как решать")],
    ]
    if has_session:
        rows.append([KeyboardButton(text="▶ Продолжить")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def number_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="№6 · Вычисления")],
            [KeyboardButton(text="↩ В меню")],
        ],
        resize_keyboard=True,
    )


def task6_menu(problem_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="💡 Подсказка", callback_data=f"t6:hint:{problem_id}"),
                InlineKeyboardButton(text="📘 Разбор", callback_data=f"t6:solution:{problem_id}"),
            ],
            [
                InlineKeyboardButton(text="➡ Следующее", callback_data=f"t6:next:{problem_id}"),
                InlineKeyboardButton(text="⏭ Пропустить", callback_data=f"t6:skip:{problem_id}"),
            ],
            [InlineKeyboardButton(text="↩ В меню", callback_data=f"t6:menu:{problem_id}")],
        ]
    )
