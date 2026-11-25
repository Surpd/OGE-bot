from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.bop_copy import LABELS

# Legacy reply text remains accepted by the router, but unavailable modes are hidden.
MAIN_MENU = ("🧮 По номеру", "📊 Мой прогресс", "⚙️ Настройки", "▶ Продолжить")
TASK6_MENU = ("💡 Подсказка", "📘 Разбор", "⏭ Пропустить", "↩ В меню")


def _button(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def main_menu(*, has_session: bool = False) -> InlineKeyboardMarkup:
    from app.config import get_settings

    if get_settings().oge_adaptive_enabled:
        rows = [[_button("🎯 Тренировки", "nav:trainings")]]
    else:
        rows = [
            [_button("🎲 Смешанная тренировка", "nav:mixed")],
            [_button("🧮 По номеру", "nav:numbers")],
        ]
    rows.append([_button(LABELS["progress"], "nav:progress")])
    rows.append([_button("⚙️ Настройки", "nav:display")])
    if has_session:
        rows.insert(0, [_button("▶ Продолжить", "nav:resume")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def trainings_hub(
    *, personal_enabled: bool = True, short_enabled: bool = True
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if short_enabled and personal_enabled:
        rows.append([_button("Персональная тренировка", "train:personal")])
    if short_enabled:
        rows.extend([
            [_button("🧮 По номеру или типу · 5 задач", "train:areas")],
            [_button("Смешанная тренировка · 5 задач", "train:mixed")],
        ])
    rows.extend(
        [
            [_button("📝 Свободная практика", "nav:numbers")],
            [_button("📚 Полный Mix №1–19", "nav:mixed")],
            [_button(LABELS["menu"], "nav:main")],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def number_page(
    *,
    include_task7: bool = False,
    include_task13: bool = False,
    include_task11: bool = False,
    page: int = 0,
) -> tuple[str, InlineKeyboardMarkup]:
    from app.bot.trainings import PART2_TRAININGS, TRAININGS
    from app.config import get_settings

    flags = {7: include_task7, 11: include_task11, 13: include_task13}
    options = [("№1–5", "Практические задания", "nav:oge15")]
    options.extend(
        (f"№{t.number}", t.title, f"nav:task:{t.number}")
        for t in TRAININGS
        if flags.get(t.number, t.available)
    )
    if get_settings().oge_part2_enabled:
        options.extend((f"№{t.number}", t.title, f"p2:menu:{t.number}") for t in PART2_TRAININGS)
    pages = (len(options) + 5) // 6
    page = min(max(0, page), pages - 1)
    entries = options[page * 6 : (page + 1) * 6]
    text = "\n".join(f"{label} · {title}" for label, title, _ in entries)
    buttons = [_button(label, callback) for label, _, callback in entries]
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    arrows = []
    if page:
        arrows.append(_button("←", f"nav:numbers:{page - 1}"))
    if page + 1 < pages:
        arrows.append(_button("→", f"nav:numbers:{page + 1}"))
    if arrows:
        rows.append(arrows)
    rows.append([_button(LABELS["menu"], "nav:main")])
    return (
        f"Выберите номер задания\n\n{text}\n\nСтраница {page + 1} из {pages}",
        InlineKeyboardMarkup(inline_keyboard=rows),
    )


def number_menu(
    *,
    include_task7: bool = False,
    include_task13: bool = False,
    include_task11: bool = False,
    page: int = 0,
) -> InlineKeyboardMarkup:
    return number_page(
        include_task7=include_task7,
        include_task11=include_task11,
        include_task13=include_task13,
        page=page,
    )[1]


def progress_menu(*, has_session: bool = False) -> InlineKeyboardMarkup:
    rows = [[_button("📊 Подробнее", "nav:details"), _button(LABELS["menu"], "nav:main")]]
    if has_session:
        rows.insert(0, [_button("▶ Продолжить", "nav:resume")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def training_menu(
    number: int, problem_id: str, *, completed: bool = False, choices: bool = False
) -> InlineKeyboardMarkup:
    prefix = f"t{number}"
    if completed:
        rows = [[_button(LABELS["next"], f"{prefix}:next:{problem_id}")]]
    else:
        rows = [
            [
                _button(LABELS["hint"], f"{prefix}:hint:{problem_id}"),
                _button(LABELS["solution"], f"{prefix}:solution:{problem_id}"),
            ],
            [_button(LABELS["skip"], f"{prefix}:skip:{problem_id}")],
        ]
        if choices:
            rows.insert(
                0, [_button(str(n), f"{prefix}:choose:{problem_id}:{n}") for n in range(1, 5)]
            )
    rows.append([_button(LABELS["menu"], f"{prefix}:menu:{problem_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def saved_training_menu(
    number: int, problem_id: str, *, confirm_restart: bool = False
) -> InlineKeyboardMarkup:
    if confirm_restart:
        rows = [
            [_button("🆕 Подтвердить", f"nav:tr:y:{number}:{problem_id}")],
            [_button("↩ Отмена", f"nav:tr:n:{number}:{problem_id}")],
        ]
    else:
        rows = [
            [_button("▶ Продолжить", f"nav:tr:c:{number}:{problem_id}")],
            [_button("🆕 Начать заново", f"nav:tr:r:{number}:{problem_id}")],
            *(
                [
                    [
                        _button(
                            "Выбрать тему" if number == 19 else "Выбрать тип",
                            f"nav:families:{number}",
                        )
                    ]
                ]
                if number in range(6, 20)
                else []
            ),
            [_button("↩ Назад к номерам", "nav:numbers")],
        ]
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
