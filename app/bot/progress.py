"""Text screens and compact navigation for the unified progress dashboard."""

from __future__ import annotations

import base64
from datetime import date, datetime
from typing import Any
from uuid import UUID

from aiogram.exceptions import TelegramBadRequest, TelegramNotFound
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.persistence.training_insights import (
    _STORY_NAMES,
    MIN_ANSWERED_SAMPLE,
    family_name,
    has_recommendation_sample,
    recommendation_sample_count,
    recommended_number,
    success_label,
    training_insights,
    training_record_detail,
)

PAGE_SIZE = 6
_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"
OUTCOMES = {
    "issued": "в процессе",
    "active": "в процессе",
    "solved": "решено",
    "failed": "две ошибки",
    "skipped": "пропущено",
    "solution_viewed": "открыт разбор",
    "unknown": "результат неизвестен",
}


def _button(text: str, callback: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=callback)


def _base36(value: int) -> str:
    if value < 0:
        raise ValueError("Negative progress navigation value")
    if value < 36:
        return _ALPHABET[value]
    result = ""
    while value:
        value, remainder = divmod(value, 36)
        result = _ALPHABET[remainder] + result
    return result


def _from_base36(value: str) -> int:
    if not value or any(char not in _ALPHABET for char in value):
        raise ValueError("Invalid compact progress navigation value")
    return int(value, 36)


def encode_record_ref(record_id: str) -> str:
    """Encode source + UUID + scenario position in a reversible short token."""
    parts = record_id.split(":")
    kind = parts[0] if parts else ""
    if kind in {"o", "m"} and len(parts) == 2:
        position = 0
    elif kind == "s" and len(parts) == 3 and parts[2].isascii() and parts[2].isdigit():
        position = int(parts[2])
        if position not in range(1, 6):
            raise ValueError("Invalid scenario position")
    else:
        raise ValueError("Unsupported progress record reference")
    payload = kind.encode("ascii") + UUID(parts[1]).bytes + bytes([position])
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_record_ref(token: str) -> str:
    try:
        payload = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        kind = payload[:1].decode("ascii")
        if len(payload) != 18 or kind not in {"o", "m", "s"}:
            raise ValueError("Malformed progress record token")
        problem_id = str(UUID(bytes=payload[1:17]))
        position = payload[17]
        if kind == "s":
            if position not in range(1, 6):
                raise ValueError("Malformed scenario position")
            return f"s:{problem_id}:{position}"
        if position != 0:
            raise ValueError("Malformed ordinary record token")
        return f"{kind}:{problem_id}"
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("Invalid progress record token") from exc


def encode_return_page(page: str) -> str:
    parts = page.split(":")
    if len(parts) == 2 and parts[0] in {"history", "errors"}:
        prefix = "h" if parts[0] == "history" else "e"
        offset = int(parts[1])
        return prefix + _base36(offset)
    if len(parts) == 3 and parts[0] == "numerr":
        return f"n{_base36(int(parts[1]))}.{_base36(int(parts[2]))}"
    raise ValueError("Unsupported progress return page")


def decode_return_page(value: str) -> str:
    if len(value) > 1 and value[0] in {"h", "e"}:
        section = "history" if value[0] == "h" else "errors"
        return f"{section}:{_from_base36(value[1:])}"
    if value.startswith("n") and "." in value:
        number, offset = value[1:].split(".", 1)
        parsed_number = _from_base36(number)
        if parsed_number not in range(1, 20):
            raise ValueError("Invalid return number")
        return f"numerr:{parsed_number}:{_from_base36(offset)}"
    raise ValueError("Invalid progress return page")


def _number_title(number: int) -> str:
    if number in range(1, 6):
        return "Практические вопросы связанных сюжетов"
    from app.bot.trainings import BY_NUMBER

    training = BY_NUMBER.get(number)
    return training.title if training else "Задание"


def progress_keyboard(
    page: str = "summary",
    total: int = 0,
    *,
    number: int | None = None,
    records: list[dict[str, Any]] | None = None,
    family_total: int = 0,
    has_errors: bool = False,
    return_page: str | None = None,
) -> InlineKeyboardMarkup:
    """Build one revision-bound keyboard for the current text/photo screen."""
    parts = page.split(":")
    section = parts[0]
    rows: list[list[InlineKeyboardButton]] = []
    if section == "summary":
        rows.append([_button("📊 Подробнее о номере", "progress:details")])
        rows.append(
            [
                _button("⚠️ Мои ошибки", "progress:errors:0"),
                _button("🕘 История", "progress:history:0"),
            ]
        )
        rows.append(
            [
                _button("🔄 Обновить", "progress:refresh"),
                _button("↩ В меню", "nav:main"),
            ]
        )
    elif section == "details":
        buttons = [_button(f"№{n}", f"progress:number:{n}") for n in range(1, 20)]
        rows.extend(buttons[i : i + 4] for i in range(0, len(buttons), 4))
        rows.append([_button("📊 Мой прогресс", "progress:summary")])
    elif section == "number" and number is not None:
        if number in range(1, 6):
            rows.append([_button("Тренировать №1–5", "nav:oge15")])
        else:
            rows.append([_button(f"Тренировать №{number}", f"nav:task:{number}")])
        if has_errors:
            rows.append([_button(f"⚠️ Ошибки №{number}", f"progress:numerr:{number}:0")])
        if family_total > PAGE_SIZE:
            rows.append([_button("Семейства: дальше →", f"progress:family:{number}:{PAGE_SIZE}")])
        rows.append([_button("↩ К номерам", "progress:details")])
        rows.append([_button("📊 Мой прогресс", "progress:summary")])
    elif section == "family" and number is not None:
        offset = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
        nav: list[InlineKeyboardButton] = []
        if offset:
            nav.append(_button("← Назад", f"progress:family:{number}:{max(0, offset - PAGE_SIZE)}"))
        if offset + PAGE_SIZE < family_total:
            nav.append(_button("Дальше →", f"progress:family:{number}:{offset + PAGE_SIZE}"))
        if nav:
            rows.append(nav)
        rows.append([_button(f"↩ К №{number}", f"progress:number:{number}")])
        rows.append([_button("📊 Мой прогресс", "progress:summary")])
    elif section in {"history", "errors", "numerr"}:
        offset = int(parts[-1]) if parts[-1].isdigit() else 0
        if number is None and section == "numerr" and len(parts) > 1:
            number = int(parts[1])
        origin = encode_return_page(page)
        for record in records or []:
            record_id = record.get("record_id")
            if not isinstance(record_id, str):
                continue
            try:
                token = encode_record_ref(record_id)
            except (ValueError, TypeError):
                continue
            label = _record_button_label(record)
            callback = f"progress:item:{token}:{origin}"
            if len(callback.encode("utf-8")) <= 64:
                rows.append([_button(label, callback)])
        navigation: list[InlineKeyboardButton] = []
        prefix = "progress:" + ":".join(parts[:-1]) + ":"
        if offset:
            navigation.append(_button("← Назад", f"{prefix}{max(0, offset - PAGE_SIZE)}"))
        if offset + PAGE_SIZE < total:
            navigation.append(_button("Дальше →", f"{prefix}{offset + PAGE_SIZE}"))
        if navigation:
            rows.append(navigation)
        if number is not None:
            rows.append([_button(f"↩ К №{number}", f"progress:number:{number}")])
        rows.append([_button("📊 Мой прогресс", "progress:summary")])
    elif section == "item":
        origin = return_page or "summary"
        rows.append([_button("↩ Назад к списку", f"progress:return:{encode_return_page(origin)}")])
        rows.append([_button("📊 Мой прогресс", "progress:summary")])
    else:
        rows.append([_button("📊 Мой прогресс", "progress:summary")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _recommendation(insights: dict[str, Any]) -> str:
    number = recommended_number(insights["numbers"], insights.get("families"))
    if number is not None:
        return f"Можно потренировать №{number}: у него сейчас самая низкая успешность."
    sampled_count = recommendation_sample_count(insights["numbers"])
    if sampled_count < 2 or not has_recommendation_sample(insights["numbers"]):
        return f"Пока недостаточно данных для оценки: нужно {MIN_ANSWERED_SAMPLE} ответов на номер."
    return "По изученным номерам явной слабой темы нет."


def _record_title(record: dict[str, Any]) -> str:
    family = str(record.get("family_id", ""))
    if family.startswith("OGE15:"):
        story = _STORY_NAMES.get(family.partition(":")[2], "Практический сюжет")
        return f"№1–5 · {story}, вопрос {record.get('number', '?')}"
    number = record.get("number", "?")
    name = record.get("family_name") or family_name(family)
    return f"№{number} · {name}"


def _record_button_label(record: dict[str, Any]) -> str:
    label = _record_title(record)
    return label if len(label) <= 48 else label[:47].rstrip() + "…"


def _date_label(value: Any) -> str:
    return value.strftime("%d.%m.%Y") if isinstance(value, date | datetime) else "дата неизвестна"


def _outcome_label(record: dict[str, Any]) -> str:
    return OUTCOMES.get(str(record.get("outcome")), "результат неизвестен")


def _attempt_help_label(value: Any) -> str:
    if value is True:
        return "подсказка была"
    if value is False:
        return "без подсказки"
    return "подсказка неизвестна"


def _progress_page_parts(page: str) -> tuple[str, list[str]]:
    parts = page.split(":")
    return parts[0], parts[1:]


def render_progress(insights: dict[str, Any], page: str = "summary") -> str:
    """Render text fallback, number details, history/error lists, or a record."""
    section, parts = _progress_page_parts(page)
    if section == "summary":
        total = insights["total"]
        return "\n".join(
            (
                "Мой прогресс · ОГЭ №1–19",
                "",
                f"Верно: {total['correct']} · Успешность: {success_label(total)} · "
                f"Пропущено: {total['skipped']}",
                f"Задач с ответом: {total['answered_tasks']} · Выдано: {total['issued']}",
                "",
                _recommendation(insights),
            )
        )
    if section == "details":
        return "Подробнее о номере\n\nВыберите №1–19."
    if section == "number" and parts and parts[0].isdigit():
        number = int(parts[0])
        values = insights["numbers"].get(number, {})
        families = sorted(
            (row for row in insights.get("families", []) if int(row["number"]) == number),
            key=lambda row: str(row["family_id"]),
        )
        family_offset = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
        lines = [f"№{number} · {_number_title(number)}", ""]
        lines.extend(
            (
                f"Решено правильно: {values.get('correct', 0)}",
                f"Задач с ответом: {values.get('answered_tasks', 0)}",
                f"Успешность: {success_label(values)}",
                f"С первой попытки: {values.get('first_correct', 0)}",
                f"Со второй попытки: {values.get('second_correct', 0)}",
                f"С подсказкой: {values.get('assisted_correct', 0)}",
                f"Без подсказки: {values.get('unassisted_correct', 0)}",
            )
        )
        if values.get("unknown_assistance", 0):
            lines.append(f"Подсказка неизвестна: {values['unknown_assistance']}")
        lines.extend(
            (
                f"Пропущено: {values.get('skipped', 0)}",
                "",
                "По семействам:",
            )
        )
        visible = families[family_offset : family_offset + PAGE_SIZE]
        if visible:
            for family in visible:
                lines.append(
                    f"• {family['name']}: {family['correct']}/{family['answered_tasks']} · "
                    f"{success_label(family)}"
                )
        else:
            lines.append("• Пока нет результатов по семействам.")
        if len(families) > PAGE_SIZE:
            start = min(family_offset + 1, len(families))
            stop = min(family_offset + PAGE_SIZE, len(families))
            lines.append(f"\nТипы {start}–{stop} из {len(families)}")
        return "\n".join(lines)
    if section == "family" and len(parts) >= 2:
        number = int(parts[0]) if parts[0].isdigit() else 0
        offset = int(parts[1]) if parts[1].isdigit() else 0
        families = sorted(
            (row for row in insights.get("families", []) if int(row["number"]) == number),
            key=lambda row: str(row["family_id"]),
        )
        return "\n".join(
            [
                f"№{number} · результаты по семействам",
                "",
                *[
                    f"• {row['name']}: {row['correct']}/{row['answered_tasks']} · "
                    f"{success_label(row)}"
                    for row in families[offset : offset + PAGE_SIZE]
                ],
                f"\nТипов заданий: {len(families)}",
            ]
        )
    if section in {"history", "errors", "numerr"}:
        is_errors = section in {"errors", "numerr"}
        title = "Мои ошибки" if is_errors else "История"
        records = insights.get("errors" if is_errors else "history", [])
        count = int(insights.get("page_total", len(records)))
        number_filter = parts[0] if section == "numerr" and parts else None
        if number_filter and number_filter.isdigit():
            title += f" · №{number_filter}"
        lines = [title, ""]
        if not records:
            return f"{title}\n\nПока нет записей."
        offset = int(parts[-1]) if parts and parts[-1].isdigit() else 0
        for index, record in enumerate(records, offset + 1):
            error_note = " · была ошибка" if record.get("has_error") else ""
            lines.extend(
                (
                    f"{index}. {_record_title(record)}",
                    f"   {_date_label(record.get('issued_at'))} · "
                    f"{_outcome_label(record)}{error_note}",
                )
            )
            lines.append("")
        stop = min(offset + len(records), count)
        lines.append(f"Записи {offset + 1}–{stop} из {count}")
        return "\n".join(lines).rstrip()
    if section == "item":
        detail = insights.get("detail")
        if not isinstance(detail, dict):
            return "Запись не найдена или недоступна."
        family = str(detail.get("family_id", ""))
        if family.startswith("OGE15:"):
            story = _STORY_NAMES.get(family.partition(":")[2], "Практический сюжет")
            title = f"Практика №1–5 · {story} · вопрос {detail.get('number', '?')}"
        else:
            raw_number = str(detail.get("number", "0"))
            number = (
                int(raw_number.removeprefix("№")) if raw_number.removeprefix("№").isdigit() else 0
            )
            title = f"№{number} · {family_name(family)}"
        lines = [title, _date_label(detail.get("issued_at")), ""]
        detail_condition = detail.get("condition")
        lines.append("Исходное условие:")
        lines.append(
            str(detail_condition)
            if isinstance(detail_condition, str) and detail_condition
            else "Исходное условие в сохранённой записи недоступно."
        )
        lines.extend(("", "Результат: " + _outcome_label(detail)))
        attempts = detail.get("attempt_records") or []
        if attempts:
            error_status = "да" if detail.get("has_error") else "нет"
        elif detail.get("outcome") in {"solved", "failed"}:
            error_status = "неизвестно: журнал попыток не сохранился"
        else:
            error_status = "нет"
        lines.append("Ошибка была: " + error_status)
        if attempts:
            lines.extend(("", "Попытки:"))
            for attempt in attempts:
                attempt_no = attempt.get("attempt_no")
                answer = "верно" if attempt.get("is_correct") is True else "неверно"
                help_label = _attempt_help_label(attempt.get("used_hint"))
                lines.append(f"{attempt_no}. {answer} · {help_label}")
        elif detail.get("outcome") in {"solved", "failed"}:
            lines.extend(("", "Для этой старой записи журнал попыток не сохранился."))
        else:
            lines.extend(("", "Принятых попыток нет."))
        lines.extend(("", "Чертёж в этом просмотре не восстанавливается из истории."))
        return "\n".join(lines)
    return "Страница прогресса недоступна. Откройте «Мой прогресс»."


def _record_has_error(record: dict[str, Any]) -> bool:
    if "has_error" in record:
        return bool(record["has_error"])
    return any(item.get("is_correct") is False for item in record.get("attempt_records", []))


async def load_progress_text_page(
    repository: Any,
    user_id: int,
    page: str,
    *,
    number_filter: int | None = None,
) -> dict[str, Any]:
    section = page.partition(":")[0]
    query_page = page
    if section == "numerr":
        offset = page.rpartition(":")[2]
        query_page = f"errors:{offset}"
    insights = await training_insights(
        repository,
        user_id,
        query_page if section in {"history", "errors", "numerr"} else "summary",
        PAGE_SIZE,
        number_filter=number_filter,
    )
    return insights


async def progress_navigation(
    message: Message,
    repository: Any,
    user_id: int,
    page: str,
) -> None:
    """Serve a single revision-bound progress page from the existing records."""
    from app.bot.presentation import send_text
    from app.bot.progress_image import send_progress_image

    await repository.save_user_state(user_id, "progress")
    parts = page.split(":")
    section = parts[0]
    if section in {"summary", "refresh"}:
        old_message = getattr(message, "_message", message)
        was_photo = bool(getattr(old_message, "photo", None))
        if await send_progress_image(
            message, repository, user_id, "summary", edit_existing=was_photo
        ):
            if not was_photo:
                try:
                    await old_message.delete()
                except (TelegramBadRequest, TelegramNotFound):
                    pass
            return
        insights = await training_insights(repository, user_id, "summary")
        await send_text(
            message,
            repository,
            render_progress(insights),
            reply_markup=progress_keyboard("summary"),
        )
        if was_photo:
            try:
                await old_message.delete()
            except (TelegramBadRequest, TelegramNotFound):
                pass
        return

    if section in {"item"} and len(parts) == 3:
        try:
            record_id = decode_record_ref(parts[1])
            return_page = decode_return_page(parts[2])
        except ValueError:
            insights = {"detail": None}
            return_page = "summary"
        else:
            detail = await training_record_detail(repository, user_id, record_id)
            if detail is not None:
                detail["has_error"] = _record_has_error(detail)
            insights = {"detail": detail}
        output_page = "item"
        markup = progress_keyboard(output_page, return_page=return_page)
    elif section == "return" and len(parts) == 2:
        try:
            page = decode_return_page(parts[1])
        except ValueError:
            page = "summary"
        return await progress_navigation(message, repository, user_id, page)
    elif section == "details":
        insights = await training_insights(repository, user_id, "summary")
        output_page = "details"
        markup = progress_keyboard(output_page)
    elif section == "number" and len(parts) >= 2 and parts[1].isdigit():
        number = int(parts[1])
        if number not in range(1, 20):
            return await progress_navigation(message, repository, user_id, "details")
        offset = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
        insights = await training_insights(repository, user_id, "summary")
        family_total = sum(int(row["number"]) == number for row in insights["families"])
        errors = await training_insights(repository, user_id, "errors:0", 1, number_filter=number)
        has_errors = int(errors.get("page_total", 0)) > 0
        output_page = f"number:{number}:{offset}"
        markup = progress_keyboard(
            output_page, number=number, family_total=family_total, has_errors=has_errors
        )
    elif section == "family" and len(parts) == 3 and all(p.isdigit() for p in parts[1:]):
        number, offset = map(int, parts[1:])
        insights = await training_insights(repository, user_id, "summary")
        family_total = sum(int(row["number"]) == number for row in insights["families"])
        output_page = f"family:{number}:{offset}"
        markup = progress_keyboard(output_page, number=number, family_total=family_total)
    elif section in {"history", "errors"} and len(parts) == 2 and parts[1].isdigit():
        output_page = page
        insights = await load_progress_text_page(repository, user_id, page)
        markup = progress_keyboard(
            output_page, insights.get("page_total", 0), records=insights.get(section, [])
        )
    elif section == "numerr" and len(parts) == 3 and all(p.isdigit() for p in parts[1:]):
        number, offset = map(int, parts[1:])
        output_page = page
        insights = await load_progress_text_page(repository, user_id, page, number_filter=number)
        markup = progress_keyboard(
            output_page,
            insights.get("page_total", 0),
            number=number,
            records=insights.get("errors", []),
        )
    else:
        return await progress_navigation(message, repository, user_id, "summary")

    sent = await send_text(
        message,
        repository,
        render_progress(insights, output_page),
        reply_markup=markup,
    )
    old_message = getattr(message, "_message", message)
    if sent.message_id != old_message.message_id:
        try:
            await old_message.delete()
        except (TelegramBadRequest, TelegramNotFound):
            pass


async def show_progress(
    message: Message, repository: Any, telegram_user_id: int, page: str = "summary"
) -> None:
    insights = await training_insights(repository, telegram_user_id, "summary")
    await message.answer(
        render_progress(insights, "summary"),
        reply_markup=progress_keyboard("summary"),
        parse_mode=None,
    )


def progress_widget_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button("📊 Мой прогресс", "progress:summary")],
            [_button("↩ В меню", "nav:main")],
        ]
    )
