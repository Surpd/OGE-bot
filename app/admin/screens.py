"""Compact Telegram presentation for the private analytics desk."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal, DecimalException
from typing import Any
from zoneinfo import ZoneInfo

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.persistence.training_insights import family_name

MOSCOW = ZoneInfo("Europe/Moscow")

LABELS = {
    "home": "Обзор",
    "usage": "Использование",
    "learners": "Ученики",
    "tasks": "Задания",
    "replays": "Повторы",
    "written": "Письменные работы",
    "system": "Состояние системы",
    "cost": "ИИ и расходы",
    "tools": "Инструменты",
    "learner": "Карточка ученика",
    "types": "Типы заданий",
    "task": "Статистика номера",
}


def _value(data: Mapping[str, Any], key: str, default: Any = 0) -> Any:
    value = data.get(key, default)
    return default if value is None else value


def _money(value: object) -> str:
    try:
        amount = Decimal(str(value))
    except (DecimalException, ValueError):
        return "—"
    if not amount.is_finite():
        return "—"
    scale = 7 if 0 < amount.copy_abs() < Decimal("0.0001") else 4
    return f"${amount:.{scale}f}"


def _learner_time(value: object) -> str:
    if isinstance(value, datetime):
        return f"{value.astimezone(MOSCOW):%d.%m %H:%M} МСК"
    return "—"


def _family_label(value: object) -> str:
    if not isinstance(value, str) or not value:
        return "Тип неизвестен"
    label = family_name(value)
    return value if label == "Тип из прежней версии" else label

def _mode(value: Any) -> str:
    name = str(value)
    known = {
        "unknown": "режим неизвестен",
        "personal": "персональная пятёрка",
        "mixed": "смешанная пятёрка",
        "number": "по номеру",
        "family": "по типу",
        "full_part": "первая часть целиком",
        "scenario_single": "один вопрос сюжета",
        "scenario_full": "сюжетная пятёрка",
        "replay": "повтор ошибки",
        "written": "письменная работа",
    }
    if name in known:
        return known[name]
    if name.startswith("task") and name[4:].isdigit():
        return f"№{name[4:]}"
    return name


def _utc_label(value: object) -> str:
    if not isinstance(value, datetime):
        return "—"
    return value.astimezone(UTC).strftime("%d.%m %H:%M UTC")


def _companion(value: Any) -> str:
    return {
        "ready": "готов",
        "starting": "запускается",
        "unavailable": "недоступен",
        "disabled": "отключён",
    }.get(str(value), str(value))


def _kb(rows: list[list[tuple[str, str]]], revision: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=label,
                    callback_data=f"adm:{revision}:{action}",
                    style="success" if action.startswith("period:") and label.startswith("✓")
                    else None,
                )
                for label, action in row
            ]
            for row in rows
        ]
    )


def _nav(screen: str, period: str) -> list[list[tuple[str, str]]]:
    if screen == "home":
        rows = [
            [("Использование", "usage"), ("Задания", "tasks")],
            [("Письменные работы", "written")],
            [("Состояние системы", "system")],
            [("Инструменты", "tools"), ("ИИ и расходы", "cost")],
            [("↻ Обновить", "refresh")],
        ]
    else:
        rows = [[("← Назад", "back"), ("⌂ Главная", "home"), ("↻ Обновить", "refresh")]]
        if screen == "usage":
            rows.append([("Ученики", "learners:0")])
        if screen == "tasks":
            rows.append([("Повторы ошибок", "replays")])
        if screen == "system":
            rows.append([("ИИ и расходы", "cost")])
    rows.append(
        [
            (f"{'✓ ' if key == period else ''}{label}", f"period:{key}")
            for key, label in (("today", "Сегодня"), ("7", "7 дней"), ("28", "28 дней"))
        ]
    )
    return rows

def render_screen(
    screen: str,
    data: Mapping[str, Any] | None = None,
    *,
    revision: str = "preview",
    period: str = "7",
    companion_status: str = "unavailable",
    release: str = "",
    tools_url: str | None = None,
    **context: Any,
) -> tuple[str, InlineKeyboardMarkup]:
    """Render one report and its actual Telegram inline keyboard without I/O."""
    data = data or {}
    if screen not in {"learner", "types", "task", "written", "replays"} | set(LABELS):
        screen = "home"
    header = f"bop Admin · {LABELS.get(screen, 'Обзор')}"
    number = context.get("number")
    if number and screen in {"types", "task", "written"}:
        header += f" · №{number}"
    window = context.get("window")
    if window is not None:
        start, end = getattr(window, "start", None), getattr(window, "end", None)
        if start is not None and end is not None:
            header += f"\n{start:%d.%m %H:%M} — {end:%d.%m %H:%M} МСК"
    updated_at = context.get("updated_at")
    if updated_at is not None:
        header += f"\nОбновлено: {updated_at:%H:%M:%S} МСК"
    lines = [header]
    unavailable = data.get("unavailable")
    if unavailable and screen != "system":
        reason = {
            "unconfigured": "Источник аналитики не настроен.",
            "timeout": "Источник аналитики не ответил вовремя.",
        }.get(str(unavailable), "Источник аналитики временно недоступен.")
        lines += ["", reason, "Можно повторить обновление позже."]
        if screen == "home":
            lines.insert(-2, "Требует внимания")
        return "\n".join(lines), _kb(_nav(screen, period), revision)
    if screen in {"home", "usage"}:
        lines.extend(
            [
                f"Всего зарегистрировано: {_value(data, 'registered')}",
                f"Активны за период: {_value(data, 'active')}",
                f"Начали впервые: {_value(data, 'first')}",
                f"Ответы: {_value(data, 'answered')} · попытки: {_value(data, 'attempts')}",
                f"Проверено работ: {_value(data, 'graded')} · ошибки: {_value(data, 'errors')}",
            ]
        )
        if period != "today":
            lines.append(f"Занимались в разные дни: {_value(data, 'repeat_days')}")
        known = _value(data, "known_cost", None)
        unknown = _value(data, "unknown_cost", 0)
        lines.append(f"ИИ: {_money(known)} учтено · без стоимости записей: {unknown}")
        if screen == "home":
            attention = []
            if data.get("unknown_cost"):
                attention.append(f"Без стоимости: {data['unknown_cost']} записей")
            if data.get("errors"):
                attention.append(f"Ошибки письменных проверок: {data['errors']}")
            if companion_status not in {"ready", "disabled"}:
                attention.append(f"Тестовый бот: {_companion(companion_status)}")
            lines.append("Требует внимания")
            lines.extend(attention[:3] if attention else ["По доступным данным замечаний нет."])
        if screen == "usage":
            modes = data.get("modes", [])
            if modes:
                lines.append("Режимы")
                lines.extend(
                    f"{_mode(m.get('mode', '—'))}: {m.get('users', 0)} уч. · "
                    f"{m.get('answered', 0)} ответов · работ: {m.get('submitted', 0)}"
                    for m in modes
                )
            retention = data.get("retention") or {}
            eligible = retention.get("eligible", 0)
            returned = retention.get("returned", 0)
            ratio = f" ({returned / eligible:.0%})" if eligible else ""
            lines.append(f"Возврат на второй неделе: {returned} из {eligible}{ratio}")
            if retention.get("first_day") and retention.get("last_day"):
                lines.append(
                    f"Когорты: {retention['first_day']:%d.%m} — {retention['last_day']:%d.%m}"
                )
            days = data.get("days", [])
            if days:

                def day_label(row: Mapping[str, Any]) -> str:
                    day = row.get("day", "—")
                    if hasattr(day, "strftime"):
                        day = day.strftime("%d.%m")
                    return f"{day}: {row.get('active', 0)}"

                lines.append("Активные дни (дата: ученики):")
                lines.extend(
                    " · ".join(day_label(row) for row in days[offset : offset + 7])
                    for offset in range(0, min(len(days), 28), 7)
                )
    elif screen == "learners":
        rows = data.get("rows", [])
        if not rows:
            lines.append("За период учеников нет.")
        learner_buttons: list[list[tuple[str, str]]] = []
        for row in rows[:8]:
            opaque = str(row.get("user_id", ""))
            lines.append(f"{_learner_time(row.get('last_activity'))} · …{opaque[-6:]}")
            if opaque:
                learner_buttons.append([(f"…{opaque[-6:]}", f"learner:{opaque}")])
        if data.get("more"):
            lines.append("Показаны последние записи.")
    elif screen == "learner":
        if not data.get("found", False):
            lines.append("Карточка недоступна или устарела.")
        else:
            lines.extend(
                [
                    f"ID: {context.get('learner_id', '—')}",
                    f"Активность: {_learner_time(data.get('last_activity'))} · "
                    f"дней: {data.get('days', 0)}",
                    f"Решено: {data.get('solved', 0)} · ответы: {data.get('answered', 0)}",
                    f"Письменных работ: {data.get('submitted', 0)}",
                    f"Работ проверено: {data.get('graded', 0)} · баллы: {data.get('points', '—')}",
                    "По номерам: "
                    + (", ".join(map(str, data.get("numbers", [])[:8])) or "нет данных"),
                ]
            )
    elif screen == "tasks":
        all_rows = data.get("rows", [])
        page = int(context.get("page", 0) or 0)
        rows = all_rows[page * 10 : page * 10 + 10]
        lines.extend(
            [
                f"№{r.get('number')} · решено {r.get('solved', 0)} / ответов {r.get('answered', 0)}"
                for r in rows[:10]
            ]
        )
        if not rows:
            lines.append("За период данных нет.")
        task_buttons = [
            [(f"№{r.get('number')}", f"types:{r.get('number')}:0:sample")]
            for r in rows[:10]
            if r.get("number")
        ]
        task_page = []
        if page:
            task_page.append(("←", f"tasks:{page - 1}"))
        if (page + 1) * 10 < len(all_rows):
            task_page.append(("→", f"tasks:{page + 1}"))
        if task_page:
            task_buttons.append(task_page)
    elif screen == "types":
        rows = data.get("rows", [])
        lines.extend(
            [
                f"{_family_label(r.get('family_id'))} · решено {r.get('solved', 0)} "
                f"/ n={r.get('answered', 0)} · подсказки "
                f"{r.get('hinted', 0)}/{r.get('hint_known', 0)} известных"
                for r in rows[:8]
            ]
        )
        if not rows:
            lines.append("Типов с результатами нет.")
        lines.append("Рейтинг опирается на выборку; для малых n ранжирование неустойчиво.")
        lines.append("Сведения о помощи в старых записях могут быть неизвестны.")
        type_buttons = [
            [
                (
                    f"{_family_label(r.get('family_id'))} · n={r.get('answered', 0)}",
                    f"detail:{context.get('number', 0)}:{i}",
                )
            ]
            for i, r in enumerate(rows[:8])
            if r.get("family_id")
        ]
        type_buttons.append(
            [
                ("По наблюдениям", f"types:{context.get('number', 0)}:0:sample"),
                ("По результату", f"types:{context.get('number', 0)}:0:success"),
            ]
        )
        type_buttons.append([("По помощи", f"types:{context.get('number', 0)}:0:help")])
    elif screen == "task":
        if context.get("family_id"):
            lines.append(_family_label(context["family_id"]))
        task_buttons = (
            [[("Точная проверка этого типа", "qa_family")]] if context.get("family_id") else []
        )
        lines.extend(
            [
                f"Ученики: {data.get('users', 0)} · выдано: {data.get('issued', 0)}",
                f"Ответы: {data.get('answered', 0)} · решено: {data.get('solved', 0)}",
                f"Верно с 1-й попытки: {data.get('first_correct', 0)} · "
                f"без помощи: {data.get('unassisted', 0)}",
                f"Первая попытка без помощи: {data.get('first_unassisted', 0)} · "
                f"новые варианты: {data.get('novel_first_unassisted', 0)}",
                f"Подсказки: {data.get('hinted', 0)} из {data.get('hint_known', 0)} "
                f"известных · помощь неизвестна: {data.get('assistance_unknown', 0)}",
                f"Пропуски: {data.get('skipped', 0)} · разборы: {data.get('solution_views', 0)}",
                f"Повторные ошибки: {data.get('repeat_errors', 0)}",
                f"Повтор ошибки: {data.get('replay_solved', 0)} решено / "
                f"{data.get('replay_answered', 0)} ответов",
            ]
        )
        lines.append("Малая выборка описывает наблюдения, а не уровень освоения.")
        if data.get("novelty_unknown"):
            lines.append(f"Новизна неизвестна для {data['novelty_unknown']} вариантов.")
    elif screen == "written":
        lines.append("Начаты в периоде. Статус на момент обновления.")
        written_labels = {
            "issued": "выдано",
            "submitted": "отправлено",
            "revisions": "версий",
            "graded": "проверено",
            "unreadable": "не читается",
            "uncertain": "неясно",
            "error": "ошибка",
            "pending": "ожидает",
        }
        lines.append(
            f"Заданий с отправкой: {data.get('issues_submitted', 0)} · "
            f"всего отправок: {data.get('submitted', 0)} · версий: {data.get('revisions', 0)}"
        )
        lines.append(
            "Статусы: "
            + " · ".join(
                f"{label} {data.get(key, 0)}"
                for key, label in written_labels.items()
                if key not in {"submitted", "revisions"}
            )
        )
        for row in data.get("rows", [])[:8]:
            title = row.get("subtype_id") or row.get("number") or row.get("title", "—")
            lines.append(
                f"{title}: 0 — {row.get('zero', 0)} · 1 — {row.get('one', 0)} "
                f"· 2 — {row.get('two', 0)}"
            )
    elif screen == "system":
        db_status = {
            "unconfigured": "не настроена",
            "unavailable": "недоступна",
            "timeout": "тайм-аут",
        }.get(str(unavailable), "подключена")
        lines.append(f"Аналитическая БД: {db_status}")
        lines.append(f"Ошибки письменных запросов: {data.get('errors', '—' if unavailable else 0)}")
        lines.append(
            f"Релиз: {release or 'не указан'} · тестовый бот: {_companion(companion_status)}"
        )
        lines.append("Мониторинг ограничен сохранёнными статусами и ошибками за выбранное окно.")
        operations = data.get("operations", [])
        if operations:
            status_labels = {
                "ok": "успешно",
                "retry": "повтор",
                "processed": "обработано",
                "processing": "обрабатывается",
                "error": "ошибка",
                "failed": "ошибка",
            }
            lines.extend(
                f"{status_labels.get(str(r.get('status')), r.get('status', '—'))}: "
                f"{r.get('count', 0)}"
                for r in operations[:5]
            )
    elif screen == "cost":
        cost_label = (
            "Известные затраты (неполная сумма)"
            if data.get("unknown_cost")
            else "Известные затраты"
        )
        lines.extend(
            [
                f"{cost_label}: {_money(data.get('known_cost'))} · "
                f"записей без стоимости: {data.get('unknown_cost', 0)}",
                f"Бюджет UTC: {_money(data.get('budget'))} · резерв: {_money(data.get('held'))}",
                f"Месяц: {_utc_label(data.get('month_start'))} — "
                f"{_utc_label(data.get('month_end'))}",
                f"Проверок: {data.get('graded', 0)} · результат: "
                f"{_money(data.get('known_cost_per_result'))}",
                f"Диагностика: {data.get('diagnostics', 0)} · "
                f"{_money(data.get('diagnostic_cost'))} · неизвестно "
                f"без стоимости: {data.get('diagnostic_unknown', 0)}",
                f"Доступно: {data.get('available', '—')} · неизвестные работы: "
                f"{data.get('unknown_written', 0)}",
                "Сумма уточняется после закрытия неизвестных расходов.",
            ]
        )
    elif screen == "replays":
        rows = data.get("rows", [])
        lines.extend(
            [
                f"№{r.get('number', '—')} · {_family_label(r.get('family_id'))} · "
                f"ответов {r.get('answered', 0)} · решено {r.get('solved', 0)} · "
                f"ошибок {r.get('repeat_errors', 0)}"
                for r in rows[:8]
            ]
        )
        if not rows:
            lines.append("Записей повторного решения за период нет.")
    elif screen == "tools":
        lines.append("Точные проверки живут отдельно в companion и тестовой истории.")
        lines.append("История учеников не изменяется.")
        if not tools_url:
            lines.append("Откройте точные проверки командой /qa в тестовом боте.")
    if unavailable and screen == "system":
        lines += ["", "Аналитика недоступна; метрики не заменены нулями."]
    dynamic: list[list[tuple[str, str]]] = []
    if screen == "learners":
        dynamic = locals().get("learner_buttons", [])
        page = int(context.get("page", 0) or 0)
        if page or data.get("more"):
            page_buttons = []
            if page:
                page_buttons.append(("←", f"learners:{page - 1}"))
            if data.get("more"):
                page_buttons.append(("→", f"learners:{page + 1}"))
            dynamic.append(page_buttons)
    elif screen == "tasks":
        dynamic = locals().get("task_buttons", [])
    elif screen == "types":
        dynamic = locals().get("type_buttons", [])
        page = int(context.get("page", 0) or 0)
        type_number = context.get("number", 0)
        type_sort = context.get("sort", "sample")
        if page or data.get("more"):
            page_buttons = []
            if page:
                page_buttons.append(("←", f"types:{type_number}:{page - 1}:{type_sort}"))
            if data.get("more"):
                page_buttons.append(("→", f"types:{type_number}:{page + 1}:{type_sort}"))
            dynamic.append(page_buttons)
    elif screen == "written" and not context.get("number"):
        dynamic = [
            [(f"№{r.get('number')}", f"written:{r.get('number')}")]
            for r in data.get("rows", [])[:10]
            if r.get("number")
        ]
        page = int(context.get("page", 0) or 0)
        if page or data.get("more"):
            page_buttons = []
            if page:
                page_buttons.append(("←", f"written:0:{page - 1}"))
            if data.get("more"):
                page_buttons.append(("→", f"written:0:{page + 1}"))
            dynamic.append(page_buttons)
    elif screen == "written":
        page = int(context.get("page", 0) or 0)
        if page or data.get("more"):
            page_buttons = []
            if page:
                page_buttons.append(("←", f"written:{context.get('number', 0)}:{page - 1}"))
            if data.get("more"):
                page_buttons.append(("→", f"written:{context.get('number', 0)}:{page + 1}"))
            dynamic = [page_buttons]
    elif screen == "replays":
        page = int(context.get("page", 0) or 0)
        if page or data.get("more"):
            page_buttons = []
            if page:
                page_buttons.append(("←", f"replays:{page - 1}"))
            if data.get("more"):
                page_buttons.append(("→", f"replays:{page + 1}"))
            dynamic = [page_buttons]
    elif screen == "task":
        dynamic = locals().get("task_buttons", [])
    if screen == "tools":
        keyboard = _kb(
            [
                [("Открыть точные проверки", "tools_open")],
                [("← Назад", "back"), ("⌂ Главная", "home")],
                [("↻ Обновить", "refresh")],
            ],
            revision,
        )
        if tools_url:
            keyboard.inline_keyboard.insert(
                1, [InlineKeyboardButton(text="Открыть через /qa", url=tools_url)]
            )
    else:
        keyboard = _kb(dynamic + _nav(screen, period), revision)
    return "\n".join(lines), keyboard
