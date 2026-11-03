"""Compact, read-only progress pages shared by all training numbers."""
from __future__ import annotations

from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.persistence.training_insights import training_insights

PAGES = {"summary": "Общий прогресс", "numbers": "По номерам", "families": "По типам",
         "history": "История", "errors": "Ошибки"}
OUTCOMES = {"issued": "не завершено", "solved": "решено", "failed": "две ошибки",
            "skipped": "пропущено", "solution_viewed": "открыт разбор",
            "unknown": "результат неизвестен"}
PAGE_SIZE = 6


def progress_keyboard(page: str = "summary", total: int = 0) -> InlineKeyboardMarkup:
    section, _, offset_text = page.partition(":")
    offset = int(offset_text) if offset_text.isdigit() else 0
    rows = [[InlineKeyboardButton(text=title, callback_data=f"progress:{key}")]
            for key, title in PAGES.items() if key != section]
    navigation = []
    if section in {"families", "history", "errors"}:
        if offset > 0:
            navigation.append(InlineKeyboardButton(
                text="←", callback_data=f"progress:{section}:{max(0, offset - PAGE_SIZE)}"))
        if offset + PAGE_SIZE < total:
            navigation.append(InlineKeyboardButton(
                text="→", callback_data=f"progress:{section}:{offset + PAGE_SIZE}"))
    if navigation:
        rows.append(navigation)
    rows.append([InlineKeyboardButton(text="В меню", callback_data="nav:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _counts(values: dict[str, Any]) -> str:
    result = (f"Выдано: {values['issued']} · Решено: {values['correct']}\n"
            f"С 1-й: {values['first_correct']} · Со 2-й: {values['second_correct']}\n"
            f"Без подсказки: {values['unassisted_correct']} · "
            f"С подсказкой: {values['assisted_correct']}\n"
            f"Две ошибки: {values['failed']} · Пропуски: {values['skipped']}\n"
            f"Ответов: {values['attempts']} · Подсказок: {values['hints_used']} · "
            f"Разборов: {values['solutions_viewed']}")
    if values['unknown_assistance'] or values['unknown_correct_attempt']:
        result += (f"\nСтарые данные: подсказка неизвестна у {values['unknown_assistance']}, "
                   f"попытка — у {values['unknown_correct_attempt']} решений.")
    return result


def render_progress(insights: dict[str, Any], page: str = "summary") -> str:
    section, _, offset_text = page.partition(":")
    offset = int(offset_text) if offset_text.isdigit() else 0
    if section not in PAGES:
        section = "summary"
    lines = [PAGES[section]]
    if section == "summary":
        lines.extend(["", _counts(insights["total"])])
        if insights["total"]["unknown_assistance"]:
            lines.append("Для части старых решений использование подсказки неизвестно: "
                         f"{insights['total']['unknown_assistance']}.")
        lines.append("Решено — верный ответ до открытия разбора; подсказки учтены отдельно.")
    elif section == "numbers":
        for number, values in insights["numbers"].items():
            lines.append(f"№{number}: решено {values['correct']} из {values['issued']} · "
                         f"1-я/2-я: {values['first_correct']}/{values['second_correct']}")
    else:
        entries = insights[section]
        if not entries:
            lines.append("Пока нет записей.")
        visible = entries if insights.get("paginated") else entries[offset:offset + PAGE_SIZE]
        for record in visible:
            if section == "families":
                lines.extend(["", f"№{record['number']} · {record['name']}", _counts(record)])
            else:
                outcome = OUTCOMES.get(record["outcome"], "результат неизвестен")
                date = record.get("issued_at")
                stamp = date.strftime("%d.%m %H:%M") if date else "дата неизвестна"
                condition = " ".join(str(record.get("condition", "")).split())[:120]
                lines.extend(["", f"№{record['number']} · {record['family_name']}",
                              f"{stamp} · {outcome}", condition])
        total = insights.get("page_total", len(entries))
        if entries:
            lines.append(f"\nЗаписи {min(offset + 1, total)}–"
                         f"{min(offset + PAGE_SIZE, total)} из {total}")
    return "\n".join(lines)


async def show_progress(message: Message, repository: Any, telegram_user_id: int,
                        page: str = "summary") -> None:
    insights = await training_insights(repository, telegram_user_id, page)
    section = page.partition(":")[0]
    total = insights["page_total"] if section in {"families", "history", "errors"} else 0
    await message.answer(render_progress(insights, page),
                         reply_markup=progress_keyboard(page, total), parse_mode=None)

