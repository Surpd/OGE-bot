from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

# Legacy reply text remains accepted by the router, but unavailable modes are hidden.
MAIN_MENU = ("🧮 По номеру", "📊 Прогресс", "Вид формул", "▶ Продолжить")
TASK6_MENU = ("💡 Подсказка", "📘 Разбор", "⏭ Пропустить", "↩ В меню")


def _button(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def main_menu(*, has_session: bool = False) -> InlineKeyboardMarkup:
    rows = [[_button("🧮 По номеру", "nav:numbers"), _button("📊 Прогресс", "nav:progress")]]
    rows.append([_button("Вид формул", "nav:display")])
    if has_session:
        rows.insert(0, [_button("▶ Продолжить", "nav:resume")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def number_menu(
    *, include_task7: bool = False, include_task13: bool = False, include_task11: bool = False,
) -> InlineKeyboardMarkup:
    from app.bot.trainings import TRAININGS

    release_flags = {7: include_task7, 11: include_task11, 13: include_task13}
    buttons = [
        _button(f"№{training.number} · {training.title}", f"nav:task:{training.number}")
        for training in TRAININGS
        if release_flags.get(training.number, training.available)
    ]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    rows.insert(0, [_button("№1–5 · Практические задания", "oge15:home")])
    rows.append([_button("↩ В меню", "nav:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def progress_menu(*, has_session: bool = False) -> InlineKeyboardMarkup:
    rows = [[_button("📊 Подробнее", "nav:details"), _button("↩ В меню", "nav:main")]]
    if has_session:
        rows.insert(0, [_button("▶ Продолжить", "nav:resume")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def training_menu(
    number: int, problem_id: str, *, completed: bool = False, choices: bool = False
) -> InlineKeyboardMarkup:
    prefix = f"t{number}"
    if completed:
        rows = [[_button("➡ Следующее", f"{prefix}:next:{problem_id}")]]
    else:
        rows = [
            [_button("💡 Подсказка", f"{prefix}:hint:{problem_id}"),
             _button("📘 Разбор", f"{prefix}:solution:{problem_id}")],
            [_button("⏭ Пропустить", f"{prefix}:skip:{problem_id}")],
        ]
        if choices:
            rows.insert(0, [_button(str(n), f"{prefix}:choose:{problem_id}:{n}")
                            for n in range(1, 5)])
    rows.append([_button("↩ В меню", f"{prefix}:menu:{problem_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def task6_menu(problem_id: str, *, completed: bool = False) -> InlineKeyboardMarkup:
    return training_menu(6, problem_id, completed=completed)


def task7_menu(problem_id: str, *, completed: bool = False) -> InlineKeyboardMarkup:
    return training_menu(7, problem_id, completed=completed)


def task8_menu(problem_id: str, *, completed: bool = False) -> InlineKeyboardMarkup:
    return training_menu(8, problem_id, completed=completed)


def task9_menu(problem_id: str, *, completed: bool = False) -> InlineKeyboardMarkup:
    return training_menu(9, problem_id, completed=completed)


def task10_menu(problem_id: str, *, completed: bool = False) -> InlineKeyboardMarkup:
    return training_menu(10, problem_id, completed=completed)


def task11_menu(problem_id: str, *, completed: bool = False) -> InlineKeyboardMarkup:
    return training_menu(11, problem_id, completed=completed)


def task12_menu(problem_id: str, *, completed: bool = False) -> InlineKeyboardMarkup:
    return training_menu(12, problem_id, completed=completed)


def task13_menu(
    problem_id: str, *, completed: bool = False, choices: bool = False
) -> InlineKeyboardMarkup:
    return training_menu(13, problem_id, completed=completed, choices=choices)


def task14_menu(problem_id: str, *, completed: bool = False) -> InlineKeyboardMarkup:
    return training_menu(14, problem_id, completed=completed)
