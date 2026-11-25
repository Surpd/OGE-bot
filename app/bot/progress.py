"""Text screens and compact navigation for the unified progress dashboard."""

from __future__ import annotations

import asyncio
import base64
from datetime import UTC, date, datetime
from typing import Any, TypedDict
from uuid import UUID

from aiogram.exceptions import TelegramBadRequest, TelegramNotFound
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, ReplyParameters
from aiogram.utils.formatting import Bold, Text, as_list

from app.persistence.training_insights import (
    _STORY_NAMES,
    MIN_ANSWERED_SAMPLE,
    family_name,
    has_recommendation_sample,
    recommendation_sample_count,
    recommended_number,
    record_story_code,
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


class _ReplyOptions(TypedDict, total=False):
    reply_parameters: ReplyParameters


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
    replay_action: tuple[str, str] | None = None,
    similar_action: str | None = None,
    insights: dict[str, Any] | None = None,
) -> InlineKeyboardMarkup:
    """Build one revision-bound keyboard for the current text/photo screen."""
    parts = page.split(":")
    section = parts[0]
    rows: list[list[InlineKeyboardButton]] = []
    from app.config import get_settings

    if section == "summary":
        if get_settings().oge_adaptive_enabled:
            rows.append([_button("Сводка по типам задач", "nav:gaps:0")])
        action = _summary_action(insights) if insights is not None else None
        if action is not None:
            rows.append([_button(*action)])
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
        if get_settings().oge_part2_enabled:
            rows.insert(-1, [_button("Письменные работы", "progress:works:0")])
    elif section == "details":
        buttons = [_button(f"№{n}", f"progress:number:{n}") for n in range(1, 20)]
        if get_settings().oge_part2_enabled:
            buttons.extend(_button(f"№{n}", f"progress:written:{n}") for n in range(20,26))
        rows.extend(buttons[i : i + 4] for i in range(0, len(buttons), 4))
        rows.append([_button("📊 Мой прогресс", "progress:summary")])
    elif section == "number" and number is not None:
        if number in range(1, 6):
            rows.append([_button(f"Тренировать №{number}", f"nav:oge15:{number}")])
        else:
            rows.append([_button(f"Тренировать №{number}", f"nav:task:{number}")])
        if has_errors:
            rows.append([_button(f"⚠️ Ошибки №{number}", f"progress:numerr:{number}:0")])
        if family_total:
            rows.append([_button("Все типы задач", f"progress:family:{number}:0")])
        rows.append([_button("↩ К номерам", "progress:details")])
        rows.append([_button("📊 Мой прогресс", "progress:summary")])
    elif section == "family" and number is not None:
        offset = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
        if number in range(1, 6):
            rows.append([_button(f"Тренировать №{number}", f"nav:oge15:{number}")])
        else:
            rows.append([_button(f"Тренировать №{number}", f"nav:task:{number}")])
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
        numbered_buttons: list[InlineKeyboardButton] = []
        for index, record in enumerate(records or [], offset + 1):
            record_id = record.get("record_id")
            if not isinstance(record_id, str):
                continue
            try:
                token = encode_record_ref(record_id)
            except (ValueError, TypeError):
                continue
            callback = f"progress:item:{token}:{origin}"
            if len(callback.encode("utf-8")) <= 64:
                numbered_buttons.append(_button(str(index), callback))
        rows.extend(numbered_buttons[i : i + 3] for i in range(0, len(numbered_buttons), 3))
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
        if replay_action is not None:
            rows.append([_button(replay_action[0], replay_action[1])])
        if similar_action is not None:
            rows.append([_button("Решить похожее", similar_action)])
        back = "↩ К истории" if origin.startswith("history") else "↩ К ошибкам"
        rows.append([_button(back, f"progress:return:{encode_return_page(origin)}")])
        rows.append([_button("📊 Мой прогресс", "progress:summary")])
    else:
        rows.append([_button("📊 Мой прогресс", "progress:summary")])
    if section in {"number", "family"} and insights and get_settings().oge_adaptive_enabled:
        rows[0] = [_button(f"Тренировать №{number}", f"train:number:{number}")]
        start = (
            int(parts[2]) if section == "family" and len(parts) > 2 and parts[2].isdigit() else 0
        )
        families = _number_families(insights, number)
        if section == "number":
            families = [family for family in families if _has_family_results(family)]
        practice = [
            [_button(f"Тренировать · {r['name']}", f"train:family:{r['family_id']}")]
            for r in families[start:start + PAGE_SIZE] if r.get("practice_priority")
        ]
        rows[1:1] = practice
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _summary_action(insights: dict[str, Any]) -> tuple[str, str] | None:
    from app.config import get_settings

    if action := insights.get("personal_action"):
        return str(action[0]), str(action[1])
    if insights["total"]["answered_tasks"] == 0:
        if get_settings().oge_adaptive_enabled:
            return "Смешанная тренировка · 5 задач", "train:mixed"
        return "🎲 Смешанная тренировка", "nav:mixed"
    number = recommended_number(insights["numbers"], insights.get("families"))
    if number is None:
        return None
    if get_settings().oge_adaptive_enabled:
        return f"Тренировать №{number}", f"train:number:{number}"
    route = "nav:oge15" if number <= 5 else "nav:task"
    return f"▶ Тренировать №{number}", f"{route}:{number}"


def _recommendation(insights: dict[str, Any]) -> str:
    if insights.get("personal_tip"):
        return str(insights["personal_tip"])
    if insights["total"]["answered_tasks"] == 0:
        return "Начни со смешанной тренировки или выбери номер."
    number = recommended_number(insights["numbers"], insights.get("families"))
    if number is not None:
        return f"Можно потренировать №{number}: у него сейчас самая низкая успешность."
    sampled_count = recommendation_sample_count(insights["numbers"])
    if sampled_count < 2 or not has_recommendation_sample(insights["numbers"]):
        return f"Пока недостаточно данных для оценки: нужно {MIN_ANSWERED_SAMPLE} ответов на номер."
    return "По изученным номерам явной слабой темы нет."


def _record_title(record: dict[str, Any]) -> str:
    family = str(record.get("family_id", ""))
    story_code = record_story_code(record)
    if family.startswith("OGE15:") or story_code is not None or _is_mixed_practical_record(record):
        story = _STORY_NAMES.get(story_code or "", "сюжет неизвестного формата")
        return f"№1–5 · {story}, вопрос {record.get('number', '?')}"
    number = record.get("number", "?")
    name = record.get("family_name") or family_name(family)
    return f"№{number} · {name}"


def _is_mixed_practical_record(record: dict[str, Any]) -> bool:
    if not str(record.get("record_id", "")).startswith("m:"):
        return False
    number = str(record.get("number", "")).removeprefix("№")
    return number.isascii() and number.isdigit() and int(number) in range(1, 6)


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


def _record_list(insights: dict[str, Any], page: str) -> Text:
    section, parts = _progress_page_parts(page)
    errors = section != "history"
    title = "Мои ошибки" if errors else "История"
    if section == "numerr" and parts:
        title += f" · №{parts[0]}"
    records = insights.get("errors" if errors else "history", [])
    if not records:
        empty = "Пока нет задач с ошибками." if errors else "Здесь появятся выданные вам задания."
        return Text(Bold(title), "\n\n", empty)
    offset = int(parts[-1]) if parts and parts[-1].isdigit() else 0
    rows = []
    for index, record in enumerate(records, offset + 1):
        result = _outcome_label(record)
        if record.get("has_error"):
            if record.get("outcome") == "solved":
                result = "решено после ошибки"
            elif record.get("outcome") != "failed":
                result += " · была ошибка"
        rows.append(Text(Bold(f"{index}. {_record_title(record)}"), "\n",
                         _date_label(record.get("issued_at")), " · ", result))
    count = int(insights.get("page_total", len(records)))
    return Text(Bold(title), "\n", f"Записи {offset + 1}–{offset + len(rows)} из {count}",
                "\n\n", as_list(*rows, sep="\n\n"), "\n\nВыберите номер записи ниже.")


_FAMILY_PRIORITY = {"gap": 0, "reopened": 0, "check": 1, "practice": 2, "confirmed": 3}


def _number_families(insights: dict[str, Any], number: int | None) -> list[dict[str, Any]]:
    return sorted(
        (row for row in insights.get("families", []) if row["number"] == number),
        key=lambda row: (
            _FAMILY_PRIORITY.get(row.get("diagnosis_key", ""), 4),
            -int(row.get("answered_tasks", 0)),
            str(row["name"]).casefold(),
            str(row["family_id"]),
        ),
    )


def _has_family_results(row: dict[str, Any]) -> bool:
    return bool(row.get("answered_tasks")) or (
        row.get("diagnosis_key") not in {None, "unchecked"}
    )


def _family_line(row: dict[str, Any]) -> str:
    line = f"• {row['name']}"
    if row.get("answered_tasks") or "diagnosis" not in row:
        line += f": {row['correct']}/{row['answered_tasks']} · {success_label(row)}"
    if "diagnosis" in row and row.get("diagnosis_key") != "unchecked":
        line += f" · {row['diagnosis']}"
    return line


async def _include_family_states(
    insights: dict[str, Any], repository: Any, user_id: int, number: int,
) -> None:
    from app.adaptive.engine import State, family_status
    from app.adaptive.skills import title
    from app.adaptive.store import overview
    from app.bot.adaptive import catalog
    from app.config import get_settings

    if not get_settings().oge_adaptive_enabled:
        return
    states = {f: state for n, f, state, _ in await overview(repository, user_id) if n == number}
    insights["independent_count"] = sum(state.independent_count for state in states.values())
    rows = {r["family_id"]: r for r in insights["families"] if r["number"] == number}
    for family, position in catalog().items():
        if position != number:
            continue
        row = rows.get(family)
        if row is None:
            row = {"family_id": family, "number": number, "correct": 0, "answered_tasks": 0}
            insights["families"].append(row)
        row["name"] = title(family)
        state = states.get(family, State())
        status = family_status(state)
        label = status.label
        if status.practice:
            label += f", {status.practice}/{status.target}"
        if state.reviewed_at is not None:
            day = datetime.fromtimestamp(state.reviewed_at, UTC)
            label += f" · повторено самостоятельно {day:%d.%m.%Y}"
        row["diagnosis"] = label
        row["diagnosis_key"] = status.key
        row["practice_priority"] = status.key in {"check", "gap", "reopened", "practice"}


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
        families = [row for row in _number_families(insights, number) if _has_family_results(row)]
        answered = values.get("answered_tasks", 0)
        lines = [
            f"№{number} · {_number_title(number)}", "",
            f"Решено правильно: {values.get('correct', 0)} из {answered}",
            f"Успешность: {success_label(values)}",
        ]
        if values.get("skipped"):
            lines.append(f"Пропущено: {values['skipped']}")
        if "independent_count" in insights:
            lines.append(f"Новых вариантов самостоятельно: {insights['independent_count']}")
        if int(answered) < MIN_ANSWERED_SAMPLE:
            lines.append(
                f"Данных недостаточно для оценки: нужно {MIN_ANSWERED_SAMPLE} задач с ответом."
            )
        if answered:
            lines.extend((
                "", "Попытки",
                f"Верно с первой: {values.get('first_correct', 0)}",
                f"Верно со второй: {values.get('second_correct', 0)}",
                f"С подсказкой: {values.get('assisted_correct', 0)}",
                f"Без подсказки: {values.get('unassisted_correct', 0)}",
            ))
            if values.get("unknown_assistance", 0):
                lines.append(f"Подсказка неизвестна: {values['unknown_assistance']}")
        if families:
            lines.extend(("", "Типы задач", *map(_family_line, families[:PAGE_SIZE])))
        return "\n".join(lines)
    if section == "family" and len(parts) >= 2:
        number = int(parts[0]) if parts[0].isdigit() else 0
        offset = int(parts[1]) if parts[1].isdigit() else 0
        families = _number_families(insights, number)
        visible = families[offset : offset + PAGE_SIZE]
        observed = [_family_line(row) for row in visible if _has_family_results(row)]
        unchecked = [_family_line(row) for row in visible if not _has_family_results(row)]
        lines = [f"№{number} · Типы задач", "", *observed]
        if unchecked:
            lines.extend(("", "Нет данных", *unchecked))
        if len(families) > PAGE_SIZE:
            lines.append(f"\nТипы {offset + 1}–{offset + len(visible)} из {len(families)}")
        return "\n".join(lines)
    if section in {"history", "errors", "numerr"}:
        return _record_list(insights, page).render()[0]
    if section == "item":
        detail = insights.get("detail")
        if not isinstance(detail, dict):
            return "Запись не найдена или недоступна."
        family = str(detail.get("family_id", ""))
        story_code = record_story_code(detail)
        if (
            family.startswith("OGE15:")
            or story_code is not None
            or _is_mixed_practical_record(detail)
        ):
            story = _STORY_NAMES.get(story_code or "", "сюжет неизвестного формата")
            position = str(detail.get("number", "?")).removeprefix("№")
            title = f"Практика №1–5 · {story} · вопрос {position}"
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
        if detail.get("drawing_unavailable") is True:
            lines.extend(("", "Исходный чертёж в сохранённой истории недоступен."))
        replay_status = detail.get("replay_status")
        if replay_status == "available":
            lines.extend(("", "Доступен один учебный повтор исходной задачи."))
        elif replay_status == "active":
            lines.extend(("", "Исходный повтор можно продолжить."))
        elif replay_status == "solved":
            lines.extend(("", "✅ Ошибка исправлена в учебном повторе."))
        elif replay_status == "used":
            lines.extend(("", "Повтор исходной задачи уже использован."))
        elif replay_status == "unavailable":
            lines.extend(("", "Исходное задание недоступно для точного восстановления."))
        return "\n".join(lines)
    return "Страница прогресса недоступна. Открой «Мой прогресс»."


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
    if section in {"written", "works", "work"}:
        from app.bot.part2_progress import page as written_page

        await written_page(message, repository, user_id, parts)
        return
    old_message = getattr(message, "_message", message)
    was_photo = bool(getattr(old_message, "photo", None))
    reply = getattr(old_message, "reply_to_message", None)
    overview = reply if isinstance(reply, Message) and reply.photo else None
    if section in {"summary", "refresh"}:
        if overview is not None and await send_progress_image(
            overview, repository, user_id, "summary", edit_existing=True, viewer=message.from_user
        ):
            try:
                await old_message.delete()
            except (TelegramBadRequest, TelegramNotFound):
                pass
            return
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
            reply_markup=progress_keyboard("summary", insights=insights),
            user_id_override=user_id,
        )
        if was_photo:
            try:
                await old_message.delete()
            except (TelegramBadRequest, TelegramNotFound):
                pass
        return

    math_family: object = None
    math_system_rows: tuple[str, ...] | None = None
    if section in {"item"} and len(parts) == 3:
        from aiogram.types import BufferedInputFile

        from app.bot.diagram_layout import mobile_diagram
        from app.bot.error_replay import _materials
        from app.bot.presentation import send_photo
        from app.bot.task_view import question_text, system_rows
        from app.persistence.error_replay import ErrorReplayRepository, load_original_source

        replay_action = None
        similar_action = None
        scenario_data_action = None
        photos: tuple[bytes, ...]
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
                has_error = detail["has_error"] or detail.get("outcome") == "failed"
                try:
                    source = await load_original_source(repository, user_id, record_id)
                    if source.scenario_snapshot is not None:
                        from app.bot.scenario_materials import send_scenario_materials
                        from app.math.scenario_engine import ScenarioSnapshot

                        if not await send_scenario_materials(
                            message, repository,
                            ScenarioSnapshot.from_snapshot(source.scenario_snapshot),
                            source.number, user_id=user_id,
                        ):
                            return
                        context, photos = "", ()
                        scenario_data_action = f"progress:{page}"
                    else:
                        context, photos = await asyncio.to_thread(_materials, source)
                except (ValueError, KeyError, TypeError, RuntimeError):
                    if has_error:
                        detail["replay_status"] = "unavailable"
                else:
                    math_family = source.snapshot
                    detail["condition"] = question_text(source.number, source.snapshot)
                    detail["drawing_unavailable"] = False
                    math_system_rows = system_rows(source.number, source.snapshot)
                    if context:
                        await send_text(
                            message, repository, context, user_id_override=user_id,
                            math_family=source.snapshot,
                        )
                    for png in photos:
                        png = await asyncio.to_thread(mobile_diagram, png, source.snapshot)
                        await send_photo(
                            message, repository, BufferedInputFile(png, filename="original.png"),
                            caption=f"Исходные данные №{source.number}", user_id_override=user_id,
                        )
                    if has_error:
                        from app.bot.similar_practice import supports_similar

                        if supports_similar(source):
                            similar_action = f"progress:similar:{encode_record_ref(record_id)}"
                        replay_store = ErrorReplayRepository(repository)
                        existing = await replay_store.status_for_source(
                            user_id, source.source_type, source.source_id, source.source_position
                        )
                        if existing is None:
                            detail["replay_status"] = "available"
                            replay_action = (
                                "🔄 Повторить исходное",
                                f"progress:replay:{encode_record_ref(record_id)}",
                            )
                        elif existing["status"] == "active":
                            detail["replay_status"] = "active"
                            replay_action = (
                                "▶ Продолжить повтор",
                                f"progress:replay:{encode_record_ref(record_id)}",
                            )
                        elif existing["status"] == "solved":
                            detail["replay_status"] = "solved"
                        else:
                            detail["replay_status"] = "used"
            insights = {"detail": detail}
        output_page = "item"
        markup = progress_keyboard(
            output_page, return_page=return_page, replay_action=replay_action,
            similar_action=similar_action
        )
        if scenario_data_action is not None:
            markup.inline_keyboard.insert(0, [InlineKeyboardButton(
                text="📷 Схема / данные", callback_data=scenario_data_action,
            )])
    elif section == "return" and len(parts) == 2:
        try:
            page = decode_return_page(parts[1])
        except ValueError:
            page = "summary"
        return await progress_navigation(message, repository, user_id, page)
    elif section == "replay" and len(parts) == 2:
        from app.bot.error_replay import start_from_progress

        try:
            record_id = decode_record_ref(parts[1])
        except ValueError:
            return await progress_navigation(message, repository, user_id, "errors:0")
        return await start_from_progress(message, repository, user_id, record_id)
    elif section == "similar" and (len(parts) == 2 or len(parts) == 3 and parts[2] == "y"):
        from app.bot.similar_practice import start_similar

        return await start_similar(
            message, repository, user_id, parts[1], confirmed=len(parts) == 3,
        )
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
        await _include_family_states(insights, repository, user_id, number)
        family_total = sum(int(row["number"]) == number for row in insights["families"])
        errors = await training_insights(repository, user_id, "errors:0", 1, number_filter=number)
        has_errors = int(errors.get("page_total", 0)) > 0
        output_page = f"number:{number}:{offset}"
        markup = progress_keyboard(
            output_page, number=number, family_total=family_total, has_errors=has_errors,
            insights=insights,
        )
    elif section == "family" and len(parts) == 3 and all(p.isdigit() for p in parts[1:]):
        number, offset = map(int, parts[1:])
        insights = await training_insights(repository, user_id, "summary")
        await _include_family_states(insights, repository, user_id, number)
        family_total = sum(int(row["number"]) == number for row in insights["families"])
        output_page = f"family:{number}:{offset}"
        markup = progress_keyboard(
            output_page, number=number, family_total=family_total, insights=insights
        )
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

    open_below_overview = section == "details" and was_photo
    reply_options: _ReplyOptions = {}
    if open_below_overview:
        overview = old_message
        try:
            await old_message.edit_reply_markup(reply_markup=None)
        except (TelegramBadRequest, TelegramNotFound):
            pass
    if overview is not None:
        # Telegram carries this anchor on subsequent callbacks and text edits.
        reply_options["reply_parameters"] = ReplyParameters(
            message_id=overview.message_id, allow_sending_without_reply=True
        )
    sent = await send_text(
        old_message if open_below_overview else message,
        repository,
        (_record_list(insights, output_page) if section in {"history", "errors", "numerr"}
         else render_progress(insights, output_page)),
        reply_markup=markup,
        math_family=math_family,
        # Only a record detail may include an original mathematical condition.
        # Keep navigation and list pages as ordinary Telegram text so their
        # keyboards and copy remain available to clients without Rich Messages.
        rich_with_navigation=(section == "item"),
        math_system_rows=math_system_rows,
        user_id_override=user_id,
        **reply_options,
    )
    if not open_below_overview and sent.message_id != old_message.message_id:
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
        reply_markup=progress_keyboard("summary", insights=insights),
        parse_mode=None,
    )


def progress_widget_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button("📊 Мой прогресс", "progress:summary")],
            [_button("↩ В меню", "nav:main")],
        ]
    )
