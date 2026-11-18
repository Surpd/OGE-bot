"""Readable text fallback and navigation for the unified progress view."""
from __future__ import annotations

from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.persistence.training_insights import (
    MIN_ANSWERED_SAMPLE,
    has_recommendation_sample,
    recommended_number,
    success_label,
    training_insights,
)

PAGES = {
    "summary": "Обзор",
    "numbers": "По номерам",
    "history": "История",
    "errors": "Ошибки",
}
OUTCOMES = {
    "issued": "в процессе",
    "active": "в процессе",
    "solved": "решено",
    "failed": "две ошибки",
    "skipped": "пропущено",
    "solution_viewed": "открыт разбор",
    "unknown": "результат неизвестен",
}
PAGE_SIZE = 6


def _button(text: str, callback: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=callback)


def progress_keyboard(page: str = "summary", total: int = 0) -> InlineKeyboardMarkup:
    section, _, value = page.partition(":")
    offset = int(value) if value.isascii() and value.isdigit() else 0
    rows = [[
        _button(title, f"progress:{key}")
        for key, title in PAGES.items()
        if key != section
    ]]
    if section == "numbers":
        number_buttons = [
            _button(f"№{number}", f"progress:number:{number}")
            for number in range(1, 20)
        ]
        rows.extend(number_buttons[index:index + 2] for index in range(0, len(number_buttons), 2))
    if section in {"families", "history", "errors"}:
        navigation = []
        if offset > 0:
            navigation.append(
                _button("← Назад", f"progress:{section}:{max(0, offset - PAGE_SIZE)}")
            )
        if offset + PAGE_SIZE < total:
            navigation.append(_button("Дальше →", f"progress:{section}:{offset + PAGE_SIZE}"))
        if navigation:
            rows.append(navigation)
    rows.append([_button("📄 Текстовая версия", "nav:progress_text")])
    rows.append([_button("↩ В меню", "nav:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _recommendation(
    total: dict[str, Any], numbers: dict[int, dict[str, Any]],
    families: list[dict[str, Any]] | None = None,
) -> str:
    number = recommended_number(numbers, families)
    if number is not None:
        return (f"Можно поработать над №{number}: у него самая низкая успешность среди "
                f"номеров с выборкой не менее {MIN_ANSWERED_SAMPLE} ответов.")
    if not has_recommendation_sample(numbers):
        return (f"Пока недостаточно ответов для оценки номеров: нужно не менее "
                f"{MIN_ANSWERED_SAMPLE} ответов на номер. Пропуски учитываются отдельно.")
    return "По текущим ответам явного слабого номера нет. Пропуски показаны отдельно."


def render_progress(insights: dict[str, Any], page: str = "summary") -> str:
    section, _, value = page.partition(":")
    numeric = int(value) if value.isascii() and value.isdigit() else 0
    if section not in {*PAGES, "families", "number"}:
        section = "summary"
    if section == "summary":
        total = insights["total"]
        return "\n".join((
            "Мой прогресс",
            "",
            f"Завершено заданий: {total['completed']}",
            f"Ответили: {total['answered_tasks']} · верно: {total['correct']} · "
            f"успешность: {success_label(total)}",
            f"Решено без подсказки: {total['unassisted_correct']}",
            f"Решено с подсказкой: {total['assisted_correct']}",
            f"Заданий с ошибками: {total['error_tasks']} · Пропущено: {total['skipped']}",
            "",
            "Что попробовать дальше",
            _recommendation(total, insights["numbers"], insights.get("families")),
            "",
            "Решёнными считаются только задания со статусом «решено». Просмотр разбора "
            "самостоятельным решением не считается.",
        ))
    if section in {"numbers", "number"}:
        selected = numeric if section == "number" else 0
        if selected:
            values = insights["numbers"].get(selected, {})
            if not values or not values["issued"]:
                return f"№{selected}\n\nПо этому номеру пока нет выданных заданий."
            return "\n".join((
                f"№{selected}",
                f"Ответили: {values['answered_tasks']} · верно: {values['correct']} · "
                f"успешность: {success_label(values)}",
                f"Без подсказки: {values['unassisted_correct']} · "
                f"С подсказкой: {values['assisted_correct']}",
                f"Были ошибки: {values['error_tasks']} · Пропуски: {values['skipped']}",
                f"Верно с первой попытки: {values['first_correct']} · "
                f"Со второй: {values['second_correct']}",
                (f"Для оценки нужно не менее {MIN_ANSWERED_SAMPLE} задач с ответом."
                 if values["answered_tasks"] < MIN_ANSWERED_SAMPLE else
                 f"Верно {values['correct']} из {values['answered_tasks']} задач с ответом."),
            ))
        lines = ["По номерам", ""]
        for number, values in insights["numbers"].items():
            label = (
                f"№{number} · ответили {values['answered_tasks']} · верно {values['correct']} · "
                f"{success_label(values)} · пропущено {values['skipped']}"
            )
            if values["answered_tasks"] < MIN_ANSWERED_SAMPLE:
                label += f" · нужно {MIN_ANSWERED_SAMPLE} ответов"
            lines.append(label)
        return "\n".join(lines)
    if section == "families":
        entries = insights["families"]
        if not entries:
            return "По типам заданий\n\nПока нет завершённых заданий."
        visible = entries if insights.get("paginated") else entries[numeric:numeric + PAGE_SIZE]
        lines = ["По типам заданий"]
        for family in visible:
            lines.append(
                f"\n№{family['number']} · {family['name']} · "
                f"ответили {family['answered_tasks']} · верно {family['correct']} · "
                f"успешность {success_label(family)} · пропущено {family['skipped']}"
            )
        total = int(insights.get("page_total", len(entries)))
        if total:
            lines.append(
                f"\nЗаписи {min(numeric + 1, total)}–{min(numeric + PAGE_SIZE, total)} "
                f"из {total}"
            )
        return "\n".join(lines)
    entries = insights[section]
    title = "История занятий" if section == "history" else "Задания с ошибками"
    lines = [title]
    if not entries:
        return "\n".join((title, "", "Пока нет записей."))
    visible = entries if insights.get("paginated") else entries[numeric:numeric + PAGE_SIZE]
    for record in visible:
        stamp = record.get("issued_at")
        date = stamp.strftime("%d.%m.%Y") if stamp else "дата неизвестна"
        condition = " ".join(str(record.get("condition") or "").split())[:90]
        family = record.get("family_name", record.get("name", "Тип задания"))
        if str(record["family_id"]).startswith("OGE15:"):
            position = str(record.get("record_id", "")).rsplit(":", 1)[-1]
            family = f"{family} · вопрос {position}"
            label = "№1–5"
        else:
            label = f"№{record['number']}"
        lines.extend((
            "",
            f"{label} · {family}",
            f"{date} · {OUTCOMES.get(record['outcome'], 'результат неизвестен')}"
            f"{' · была ошибка' if record.get('has_error') else ''}",
            condition,
        ))
    total = int(insights.get("page_total", len(entries)))
    if total:
        lines.append(
            f"\nЗаписи {min(numeric + 1, total)}–{min(numeric + PAGE_SIZE, total)} из {total}"
        )
    return "\n".join(lines)


async def show_progress(message: Message, repository: Any, telegram_user_id: int,
                        page: str = "summary") -> None:
    insights = await training_insights(repository, telegram_user_id, page)
    section = page.partition(":")[0]
    total = insights["page_total"] if section in {"families", "history", "errors"} else 0
    await message.answer(
        render_progress(insights, page),
        reply_markup=progress_keyboard(page, total),
        parse_mode=None,
    )


def progress_widget_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_button("📄 Текстовая версия", "nav:progress_text")],
        [_button("↩ В меню", "nav:main")],
    ])
