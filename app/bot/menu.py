from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

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


def task6_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💡 Подсказка"), KeyboardButton(text="📘 Разбор")],
            [KeyboardButton(text="➡ Следующее"), KeyboardButton(text="⏭ Пропустить")],
            [KeyboardButton(text="↩ В меню")],
        ],
        resize_keyboard=True,
    )
