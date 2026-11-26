"""Optional family selection; preferences apply only to the next generated task."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.presentation import send_text
from app.bot.visual_delivery import build_visual, visual_enabled
from app.bot.visual_models import VisualCard, VisualEntry, VisualSection
from app.persistence.repository import Repository
from app.persistence.rotation_history import enabled
from app.persistence.training_insights import family_name


def _button(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def _selection_name(number: int, family: str | None) -> str:
    if number == 19 and family == "OGE19-MIXED":
        return "Разные темы в одном задании"
    if family is None:
        return "Чередовать темы" if number == 19 else "Все типы"
    return family_name(family)


PAGE_SIZE = 6


def _page(number: int, page: int) -> tuple[int, list[str], int]:
    families = enabled(number)
    pages = max(1, (len(families) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, pages - 1))
    return page, families[page * PAGE_SIZE : (page + 1) * PAGE_SIZE], pages


def family_keyboard(number: int, page: int = 0) -> InlineKeyboardMarkup:
    page, entries, pages = _page(number, page)
    start = page * PAGE_SIZE
    rows = [[_button("🎲 " + _selection_name(number, None), f"nav:family:{number}:random")]]
    indexes = [
        _button(str(i + 1), f"nav:family:{number}:{i}") for i in range(start, start + len(entries))
    ]
    rows.extend(indexes[i : i + 3] for i in range(0, len(indexes), 3))
    arrows = []
    if page:
        arrows.append(_button("←", f"nav:families:{number}:{page - 1}"))
    if page + 1 < pages:
        arrows.append(_button("→", f"nav:families:{number}:{page + 1}"))
    if arrows:
        rows.append(arrows)
    rows.append([_button("← К номерам", "nav:numbers")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def selected_keyboard(number: int, page: int = 0) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button(f"▶ Открыть №{number}", f"nav:begin:{number}")],
            [
                _button(
                    "Выбрать тему" if number == 19 else "Выбрать тип",
                    f"nav:families:{number}:{page}" if page else f"nav:families:{number}",
                ),
                _button("В меню", "nav:main"),
            ],
        ]
    )


async def show_families(
    message: Message, repository: Repository, number: int, page: int = 0
) -> None:
    if message.from_user is None:
        return
    await repository.save_user_state(message.from_user.id, f"family_selection:{number}")
    selected = await repository.training_family(message.from_user.id, number)
    current = _selection_name(number, selected)
    page, entries, pages = _page(number, page)
    catalog = "\n".join(
        f"{i}. {_selection_name(number, f)}" for i, f in enumerate(entries, page * PAGE_SIZE + 1)
    )
    await send_text(
        message,
        repository,
        f"Задание №{number} · выберите тип\nСейчас: {current}\n\n"
        f"{catalog}\n\nСтраница {page + 1} из {pages}",
        reply_markup=family_keyboard(number, page),
        visual=build_visual("types", lambda: VisualCard(
            screen="types", title="Выбери тип", subtitle=f"Задание №{number}",
            sections=(VisualSection("", tuple(
                VisualEntry(_selection_name(number, family), key=str(index))
                for index, family in enumerate(entries, page * PAGE_SIZE + 1)
            )),),
            note=f"Сейчас: {current} · Страница {page + 1} из {pages}",
            personalized=True,
        )) if visual_enabled("types", message) else None,
    )


async def select_family(
    message: Message, repository: Repository, number: int, selection: str
) -> None:
    if message.from_user is None:
        return
    families = enabled(number)
    if selection == "random":
        family = None
    elif selection.isascii() and selection.isdigit() and int(selection) < len(families):
        family = families[int(selection)]
    else:
        await show_families(message, repository, number)
        return
    await repository.save_user_state(message.from_user.id, f"family_selection:{number}")
    await repository.set_training_family(message.from_user.id, number, family)
    label = _selection_name(number, family)
    await send_text(
        message,
        repository,
        f"№{number} · {label}\n\n"
        "Настройка сохранена для следующих заданий. Если есть текущая задача, "
        "она продолжится с прежними попытками и подсказками.",
        reply_markup=selected_keyboard(
            number, families.index(family) // PAGE_SIZE if family else 0
        ),
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
        reply_markup=selected_keyboard(number),
        user_id_override=user_id,
    )
