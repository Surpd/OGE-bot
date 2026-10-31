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


def main_menu(*, has_session: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text="⚡ 5 минут"), KeyboardButton(text="🧮 По номеру")],
        [KeyboardButton(text="🔁 Мои ошибки"), KeyboardButton(text="🏆 Марафон")],
        [KeyboardButton(text="📊 Прогресс"), KeyboardButton(text="📚 Как решать")],
    ]
    if has_session:
        rows.append([KeyboardButton(text="▶ Продолжить")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)
