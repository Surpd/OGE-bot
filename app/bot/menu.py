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


def number_menu(*, include_task13: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text="№6 · Вычисления")],
        [KeyboardButton(text="№9 · Уравнения")],
        [KeyboardButton(text="№10 · Вероятность")],
        [KeyboardButton(text="№12 · Формулы")],
        [KeyboardButton(text="№14 · Прогрессии")],
        [KeyboardButton(text="↩ В меню")],
    ]
    if include_task13:
        rows.insert(4, [KeyboardButton(text="№13 · Неравенства")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def progress_menu(*, has_session: bool = False) -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(text="📊 Подробнее")], [KeyboardButton(text="↩ В меню")]]
    if has_session:
        rows.append([KeyboardButton(text="▶ Продолжить")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def task6_menu(problem_id: str, *, completed: bool = False) -> InlineKeyboardMarkup:
    if completed:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="➡ Следующее", callback_data=f"t6:next:{problem_id}")],
                [InlineKeyboardButton(text="↩ В меню", callback_data=f"t6:menu:{problem_id}")],
            ]
        )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="💡 Подсказка", callback_data=f"t6:hint:{problem_id}"),
                InlineKeyboardButton(text="📘 Разбор", callback_data=f"t6:solution:{problem_id}"),
            ],
            [
                InlineKeyboardButton(text="⏭ Пропустить", callback_data=f"t6:skip:{problem_id}"),
            ],
            [InlineKeyboardButton(text="↩ В меню", callback_data=f"t6:menu:{problem_id}")],
        ]
    )


def task9_menu(problem_id: str, *, completed: bool = False) -> InlineKeyboardMarkup:
    if completed:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="➡ Следующее", callback_data=f"t9:next:{problem_id}")],
                [InlineKeyboardButton(text="↩ В меню", callback_data=f"t9:menu:{problem_id}")],
            ]
        )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="💡 Подсказка", callback_data=f"t9:hint:{problem_id}"),
                InlineKeyboardButton(text="📘 Разбор", callback_data=f"t9:solution:{problem_id}"),
            ],
            [
                InlineKeyboardButton(text="⏭ Пропустить", callback_data=f"t9:skip:{problem_id}"),
            ],
            [InlineKeyboardButton(text="↩ В меню", callback_data=f"t9:menu:{problem_id}")],
        ]
    )


def task10_menu(problem_id: str, *, completed: bool = False) -> InlineKeyboardMarkup:
    if completed:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="➡ Следующее", callback_data=f"t10:next:{problem_id}")],
                [InlineKeyboardButton(text="↩ В меню", callback_data=f"t10:menu:{problem_id}")],
            ]
        )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="💡 Подсказка", callback_data=f"t10:hint:{problem_id}"),
                InlineKeyboardButton(text="📘 Разбор", callback_data=f"t10:solution:{problem_id}"),
            ],
            [InlineKeyboardButton(text="⏭ Пропустить", callback_data=f"t10:skip:{problem_id}")],
            [InlineKeyboardButton(text="↩ В меню", callback_data=f"t10:menu:{problem_id}")],
        ]
    )


def task12_menu(problem_id: str, *, completed: bool = False) -> InlineKeyboardMarkup:
    if completed:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="➡ Следующее", callback_data=f"t12:next:{problem_id}")],
                [InlineKeyboardButton(text="↩ В меню", callback_data=f"t12:menu:{problem_id}")],
            ]
        )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="💡 Подсказка", callback_data=f"t12:hint:{problem_id}"),
                InlineKeyboardButton(text="📘 Разбор", callback_data=f"t12:solution:{problem_id}"),
            ],
            [InlineKeyboardButton(text="⏭ Пропустить", callback_data=f"t12:skip:{problem_id}")],
            [InlineKeyboardButton(text="↩ В меню", callback_data=f"t12:menu:{problem_id}")],
        ]
    )


def task14_menu(problem_id: str, *, completed: bool = False) -> InlineKeyboardMarkup:
    if completed:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="➡ Следующее", callback_data=f"t14:next:{problem_id}")],
                [InlineKeyboardButton(text="↩ В меню", callback_data=f"t14:menu:{problem_id}")],
            ]
        )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="💡 Подсказка", callback_data=f"t14:hint:{problem_id}"),
                InlineKeyboardButton(text="📘 Разбор", callback_data=f"t14:solution:{problem_id}"),
            ],
            [InlineKeyboardButton(text="⏭ Пропустить", callback_data=f"t14:skip:{problem_id}")],
            [InlineKeyboardButton(text="↩ В меню", callback_data=f"t14:menu:{problem_id}")],
        ]
    )


def task13_menu(
    problem_id: str,
    *,
    completed: bool = False,
    choices: bool = False,
) -> InlineKeyboardMarkup:
    if completed:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="➡ Следующее", callback_data=f"t13:next:{problem_id}")],
                [InlineKeyboardButton(text="↩ В меню", callback_data=f"t13:menu:{problem_id}")],
            ]
        )
    rows = [
        [
            InlineKeyboardButton(text="💡 Подсказка", callback_data=f"t13:hint:{problem_id}"),
            InlineKeyboardButton(text="📘 Разбор", callback_data=f"t13:solution:{problem_id}"),
        ],
        [InlineKeyboardButton(text="⏭ Пропустить", callback_data=f"t13:skip:{problem_id}")],
        [InlineKeyboardButton(text="↩ В меню", callback_data=f"t13:menu:{problem_id}")],
    ]
    if choices:
        rows.insert(
            0,
            [
                InlineKeyboardButton(
                    text=str(number), callback_data=f"t13:choose:{problem_id}:{number}"
                )
                for number in range(1, 5)
            ],
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)
