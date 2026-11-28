"""Telegram copy and navigation for the private analytics desk."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, DecimalException
from html import escape
from itertools import batched
from typing import Any
from zoneinfo import ZoneInfo

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.admin.queries import MIN_RANK_SAMPLE, PAGE_SIZE
from app.persistence.training_insights import family_name

MOSCOW = ZoneInfo("Europe/Moscow")
NUMBER_PAGE_SIZE = 10

LABELS = {
    "home": "Обзор",
    "usage": "Активность",
    "learners": "Ученики",
    "learner": "Карточка ученика",
    "tasks": "Задания по номерам",
    "types": "Типы заданий",
    "task": "Результаты по номеру",
    "replays": "Повторы ошибок",
    "written": "Письменные работы",
    "system": "Состояние системы",
    "cost": "ИИ и расходы",
    "tools": "Инструменты",
}
WRITTEN_STATUSES = (
    ("graded", "С оценкой"),
    ("unreadable", "Нечитаемые"),
    ("uncertain", "Не удалось оценить"),
    ("error", "Технические ошибки"),
    ("pending", "Ожидают завершения"),
)
SORT_LABELS = {"sample": "Объём выборки", "success": "Результат", "help": "Подсказки"}

ButtonRows = list[list[tuple[str, str]]]
Data = Mapping[str, Any]


def count(data: Data, key: str) -> str:
    return f"{int(data.get(key) or 0):,}".replace(",", "\N{NO-BREAK SPACE}")


def money(value: object) -> str:
    try:
        amount = Decimal(str(value))
    except (DecimalException, ValueError):
        return "—"
    if not amount.is_finite():
        return "—"
    scale = 7 if 0 < amount.copy_abs() < Decimal("0.0001") else 4
    return "$" + f"{amount:.{scale}f}".replace(".", ",")


def moscow_time(value: object) -> str:
    return f"{value.astimezone(MOSCOW):%d.%m %H:%M} МСК" if isinstance(value, datetime) else "—"


def budget_dates(data: Data) -> str:
    return " — ".join(
        value.astimezone(UTC).strftime("%d.%m %H:%M") if isinstance(value, datetime) else "—"
        for value in (data.get("month_start"), data.get("month_end"))
    )


def period_range(window: object) -> str:
    start, end = getattr(window, "start", None), getattr(window, "end", None)
    if isinstance(start, datetime) and isinstance(end, datetime):
        return f"{start:%d.%m %H:%M} — {end:%d.%m %H:%M} МСК"
    return ""


def family_label(value: object) -> str:
    if not isinstance(value, str) or not value:
        return "Тип неизвестен"
    label = family_name(value)
    return value if label == "Тип из прежней версии" else label


def _mode(value: object) -> str:
    name = str(value)
    labels = {
        "unknown": "Режим неизвестен",
        "personal": "Персональная пятёрка",
        "mixed": "Смешанная пятёрка",
        "number": "Практика по номеру",
        "family": "Практика по типу",
        "full_part": "Первая часть целиком",
        "scenario_single": "Один вопрос сюжета",
        "scenario_full": "Сюжетная пятёрка",
        "replay": "Повтор ошибки",
        "written": "Письменная работа",
    }
    if name.startswith("task") and name[4:].isdigit():
        return f"№{name[4:]}"
    return labels.get(name, name)


def _companion(value: str) -> str:
    return {
        "ready": "работает",
        "starting": "запускается",
        "unavailable": "недоступен",
        "disabled": "отключён",
    }.get(value, value)


def page_rows(screen: str, data: Data, page: int) -> Sequence[Data]:
    rows: Sequence[Data] = data.get("rows", [])
    if screen == "tasks":
        start = page * NUMBER_PAGE_SIZE
        return rows[start : start + NUMBER_PAGE_SIZE]
    return rows[:PAGE_SIZE]


def _bold(value: object) -> str:
    return f"<b>{escape(str(value), quote=False)}</b>"


def _code(value: object) -> str:
    return f"<code>{escape(str(value), quote=False)}</code>"


def _metric(label: str, value: object) -> str:
    return f"{label}  {_bold(value)}"


def _metrics(data: Data, pairs: Sequence[tuple[str, str]]) -> str:
    return "\n".join(_metric(label, count(data, key)) for key, label in pairs)


def _block(title: str, lines: Sequence[str]) -> str:
    return "\n".join([_bold(title), *lines])


def _join(*blocks: str) -> str:
    return "\n\n".join(block for block in blocks if block)


@dataclass(frozen=True)
class _Body:
    summary: str = ""
    details: str = ""


def _attention(data: Data, status: str) -> str:
    lines = []
    if data.get("errors"):
        lines.append(_metric("Ошибки письменных проверок", count(data, "errors")))
    if data.get("unknown_cost"):
        lines.append(_metric("Запросы с неизвестной стоимостью", count(data, "unknown_cost")))
    if status not in {"ready", "disabled"}:
        lines.append(f"Тестовый бот {escape(_companion(status))}")
    return _block("Требует внимания", lines[:3]) if lines else ""


def _activity(data: Data, period: str, *, home: bool, status: str) -> _Body:
    metrics = [("active", "Занимались"), ("first", "Начали впервые")]
    if period != "today":
        metrics.append(("repeat_days", "Занимались в разные дни"))
    if home:
        metrics.extend((("answered", "Задания с ответом"), ("graded", "Проверки с оценкой")))
    summary = _metrics(data, metrics)
    if home:
        summary += f"\n{_metric('Известные расходы на ИИ', money(data.get('known_cost')))}"
    if not data.get("active"):
        summary = _join(summary, "За этот период занятий пока нет.")
    additional = [("registered", "Аккаунтов всего"), ("attempts", "Попытки ответа")]
    if home:
        return _Body(summary, _join(_metrics(data, additional), _attention(data, status)))
    additional.extend(
        (
            ("answered", "Задания с ответом"),
            ("graded", "Проверки с оценкой"),
            ("errors", "Ошибки письменных проверок"),
        )
    )
    extra = [
        _metrics(data, additional),
        _metric("Известные расходы на ИИ", money(data.get("known_cost"))),
        _metric("Запросы с неизвестной стоимостью", count(data, "unknown_cost")),
    ]
    return _Body(summary, _join("\n".join(extra), _retention(data), _modes(data), _daily(data)))


def _retention(data: Data) -> str:
    retention = data.get("retention") or {}
    eligible = retention.get("eligible", 0)
    returned = retention.get("returned", 0)
    result = (
        _bold(f"{returned} из {eligible} · {returned / eligible:.0%}")
        if eligible
        else "Пока нет учеников с полной второй неделей."
    )
    first, last = retention.get("first_day"), retention.get("last_day")
    days = [f"Начали с {first:%d.%m} по {last:%d.%m}."] if first and last else []
    return _block("Вернулись на второй неделе", [result, *days])


def _modes(data: Data) -> str:
    modes = []
    written = []
    for row in data.get("modes", []):
        label = _bold(_mode(row.get("mode", "—")))
        users = count(row, "users")
        if row.get("answered") or not row.get("submitted"):
            modes.append(f"{label}  {users} · {count(row, 'answered')}")
        if row.get("submitted"):
            written.append(f"{label}  {users} уч. · отправок {count(row, 'submitted')}")
    legend = ["Ученики · задания с ответом"] if modes else []
    return _block("Режимы занятий", [*legend, *modes, *written]) if modes or written else ""


def day_label(day: object) -> str:
    return day.strftime("%d.%m") if hasattr(day, "strftime") else "—"


def _daily(data: Data) -> str:
    day_lines = []
    for week in batched(data.get("days", [])[:28], 7):
        labels = [day_label(row.get("day")) for row in week]
        values = " / ".join(count(row, "active") for row in week)
        date_range = labels[0] if len(labels) == 1 else f"{labels[0]}–{labels[-1]}"
        day_lines.append(f"{date_range}  {values}")
    return _block("По дням · число учеников", day_lines) if day_lines else ""


def _learners(data: Data, page: int) -> _Body:
    rows = page_rows("learners", data, page)
    if not rows:
        return _Body("За этот период никто не занимался.")
    return _Body(
        _block(
            "Последнее занятие",
            [
                f"{_bold('…' + str(row.get('user_id', ''))[-6:])} · "
                f"{moscow_time(row.get('last_activity'))}"
                for row in rows
            ],
        )
    )


def _learner(data: Data, learner_id: str) -> _Body:
    if not data.get("found"):
        return _Body("Карточка недоступна. Выберите ученика из списка ещё раз.")
    last = (
        f"Последнее занятие  {_bold(moscow_time(data.get('last_activity')))}"
        if data.get("last_activity")
        else "За выбранный период занятий не было."
    )
    short = _metrics(
        data, (("days", "Дни занятий"), ("solved", "Решено"), ("answered", "Задания с ответом"))
    )
    written = _metrics(data, (("submitted", "Отправлено"), ("graded", "С оценкой")))
    points = "—" if data.get("points") is None else count(data, "points")
    numbers = ", ".join(str(number) for number in data.get("numbers", [])[:25])
    return _Body(
        _join(last, short, _block("Письменные работы", [written, _metric("Всего баллов", points)])),
        _join(
            f"ID ученика  {_code(learner_id or '—')}", f"Номера заданий  {_bold(numbers or '—')}"
        ),
    )


def _tasks(data: Data, page: int) -> _Body:
    rows = page_rows("tasks", data, page)
    if not rows or not any(row.get("answered") for row in rows):
        summary = "На этой странице за период нет заданий с ответом."
    else:
        summary = "\n".join(
            f"{_bold(f'№{row.get("number", "—")}')} · {count(row, 'solved')} из "
            f"{count(row, 'answered')} решено · {count(row, 'users')} уч."
            for row in rows
        )
    return _Body(summary, "Выберите номер, чтобы открыть результаты по типам." if rows else "")


def _types(data: Data, page: int, sort: str) -> _Body:
    rows = page_rows("types", data, page)
    if not rows:
        return _Body("За этот период по типам нет данных.")
    entries = []
    for row in rows:
        hints = (
            f"Подсказки  {count(row, 'hinted')} из {count(row, 'hint_known')} с известными данными"
            if row.get("hint_known")
            else "Подсказки  нет сведений"
        )
        entries.append(
            _block(
                family_label(row.get("family_id")),
                [
                    f"Решено  {_bold(count(row, 'solved'))} из {count(row, 'answered')} · "
                    f"учеников {count(row, 'users')}",
                    hints,
                ],
            )
        )
    current = f"Порядок · {_bold(SORT_LABELS.get(sort, SORT_LABELS['sample']))}"
    return _Body(
        _join(current, *entries),
        "При малом числе ответов порядок легко меняется. "
        "О подсказках в старых записях известно не всегда.",
    )


def _task(data: Data, family_id: str) -> _Body:
    title = _bold(family_label(family_id)) if family_id else ""
    answered = count(data, "answered")
    result = _metric("Верно решено", f"{count(data, 'solved')} из {answered}")
    summary = _join(title, result, _metrics(data, (("users", "Ученики"), ("issued", "Выдано"))))
    if not data.get("answered"):
        summary = _join(summary, "За этот период ответов пока нет.")
    attempts = _metrics(
        data,
        (
            ("first_correct", "Верно с первой попытки"),
            ("unassisted", "Верно без помощи"),
            ("first_unassisted", "Верно с первой попытки без помощи"),
            ("novel_first_unassisted", "Из них новых вариантов"),
        ),
    )
    hints = (
        _metric("Брали подсказку", f"{count(data, 'hinted')} из {count(data, 'hint_known')}")
        + " с известными данными"
    )
    details = [
        _block(
            "Попытки и помощь",
            [
                attempts,
                hints,
                _metric("Помощь неизвестна", count(data, "assistance_unknown")),
            ],
        ),
        _block(
            "Пропуски и разборы",
            [
                _metrics(data, (("skipped", "Пропуски"), ("solution_views", "Просмотры разбора"))),
            ],
        ),
        _block(
            "Ошибки и повторы",
            [
                _metric("Повторные ошибки", count(data, "repeat_errors")),
                _metric(
                    "Решено при повторе ошибки",
                    f"{count(data, 'replay_solved')} из {count(data, 'replay_answered')}",
                ),
            ],
        ),
    ]
    notes = []
    if 0 < int(data.get("answered") or 0) < MIN_RANK_SAMPLE:
        notes.append("Ответов пока мало для устойчивого сравнения.")
    if data.get("novelty_unknown"):
        notes.append(f"Неизвестно, новые ли варианты  {_bold(count(data, 'novelty_unknown'))}")
    return _Body(summary, _join(*details, "\n".join(notes)))


def _written(data: Data, number: int, page: int) -> tuple[_Body, str]:
    summary = _join(
        _block(
            "Выдачи и отправки",
            [
                _metrics(
                    data,
                    (
                        ("issued", "Заданий выдано"),
                        ("issues_submitted", "Заданий с отправкой"),
                        ("submitted", "Всего отправок"),
                        ("revisions", "Повторные отправки"),
                    ),
                ),
            ],
        ),
        _block("Статусы проверок", [_metrics(data, WRITTEN_STATUSES)]),
    )
    distribution = []
    for row in page_rows("written", data, page):
        title = row.get("subtype_id") or f"№{row.get('number', '—')}"
        distribution.append(
            f"{_bold(title)} · 0 б. — {count(row, 'zero')} · 1 б. — {count(row, 'one')} "
            f"· 2 б. — {count(row, 'two')}"
        )
    scores = _block("Как распределились баллы", distribution) if distribution else ""
    cohort = "Проверки начаты в выбранном периоде. Показаны их текущие статусы."
    if not data.get("submitted"):
        cohort = "За этот период работы на проверку не отправляли."
    # The overview graphic already shows the score counts for each number.
    photo_details = _join(cohort, scores if number else "")
    return _Body(summary, _join(cohort, scores)), photo_details


def _cost(data: Data) -> _Body:
    summary = _join(
        _metric("Известные расходы за период", money(data.get("known_cost"))),
        _block(
            "Месячный бюджет · UTC",
            [
                budget_dates(data),
                _metric("Лимит", money(data.get("budget"))),
                _metric("Потрачено", money(data.get("spent"))),
                _metric("Зарезервировано", money(data.get("held"))),
                _metric("Доступно", money(data.get("available"))),
            ],
        ),
    )
    incomplete = ["Сумма за период частичная."] if data.get("unknown_cost") else []
    details = _join(
        _block(
            "Расходы за выбранный период",
            [
                _metric("Запросы с неизвестной стоимостью", count(data, "unknown_cost")),
                *incomplete,
            ],
        ),
        _block(
            "Диагностика",
            [
                _metric("Вызовы", count(data, "diagnostics")),
                _metric("Известные расходы", money(data.get("diagnostic_cost"))),
                _metric("Запросы с неизвестной стоимостью", count(data, "diagnostic_unknown")),
            ],
        ),
        _block(
            "Письменные проверки",
            [
                _metric("Проверки с оценкой", count(data, "graded")),
                _metric("На одну проверку с оценкой", money(data.get("known_cost_per_result"))),
                _metric("Проверки с неизвестной стоимостью", count(data, "unknown_written")),
            ],
        ),
    )
    return _Body(summary, details)


def _system(data: Data, status: str, release: str) -> _Body:
    unavailable = data.get("unavailable")
    db = {
        "unconfigured": "подключение отсутствует",
        "unavailable": "недоступна",
        "timeout": "не отвечает",
    }.get(str(unavailable), "на связи")
    errors = "—" if unavailable else count(data, "errors")
    connections = _block(
        "Подключения",
        [
            _metric("База аналитики", db),
            _metric("Тестовый бот", _companion(status)),
            f"Версия приложения  {_code(release)}" if release else "Версия приложения  —",
        ],
    )
    labels = {
        "ok": "Успешно",
        "retry": "Повтор",
        "processed": "Обработано",
        "processing": "Обрабатывается",
        "error": "Ошибка",
        "failed": "Ошибка",
    }
    operations = [
        _metric(
            escape(labels.get(str(row.get("status")), str(row.get("status", "—")))),
            count(row, "count"),
        )
        for row in data.get("operations", [])[:5]
    ]
    return _Body(
        connections,
        _join(
            _block("За выбранный период", [_metric("Ошибки письменных проверок", errors)]),
            _block(
                "Операции основного бота",
                operations
                or [
                    "Данные недоступны." if unavailable else "Сохранённых операций за период нет.",
                ],
            ),
            "Состояние основано на доступных подключениях и сохранённых операциях.",
        ),
    )


def _replays(data: Data, page: int) -> _Body:
    rows = page_rows("replays", data, page)
    if not rows:
        return _Body("За этот период не было ответов при повторе ошибок.")
    return _Body(
        _join(
            *[
                _block(
                    f"№{row.get('number', '—')} · {family_label(row.get('family_id'))}",
                    [
                        f"Решено  {_bold(count(row, 'solved'))} из {count(row, 'answered')} · "
                        f"повторных ошибок {count(row, 'repeat_errors')}",
                    ],
                )
                for row in rows
            ]
        )
    )


def _tools(tools_url: str | None) -> _Body:
    return _Body(
        _block(
            "Точные проверки",
            [
                "Выбор номера и типа, поиск по ID или seed, повтор сохранённого варианта.",
                "Диагностика, Rich/PNG и синтетическая проверка фотографии.",
            ],
        ),
        _block(
            "Как ученик",
            [
                "Тренировки используют отдельную тестовую историю.",
                *([] if tools_url else ["Вход в точные проверки также доступен по /qa."]),
            ],
        ),
    )


def _keyboard(rows: ButtonRows, revision: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=label,
                    callback_data=f"adm:{revision}:{action}",
                    style="success" if label.startswith("✓ ") else None,
                )
                for label, action in row
            ]
            for row in rows
        ]
    )


def _nav(screen: str, period: str) -> ButtonRows:
    if screen == "home":
        rows = [
            [("Активность", "usage"), ("Задания", "tasks")],
            [("Письменные работы", "written"), ("ИИ и расходы", "cost")],
            [("Состояние системы", "system"), ("Инструменты", "tools")],
            [("↻ Обновить", "refresh")],
        ]
    else:
        rows = []
        if screen == "usage":
            rows.append([("Ученики", "learners:0")])
        if screen == "tasks":
            rows.append([("Повторы ошибок", "replays")])
        if screen == "system":
            rows.append([("ИИ и расходы", "cost")])
        rows.append([("← Назад", "back"), ("⌂ Главная", "home"), ("↻ Обновить", "refresh")])
    rows.append(
        [
            (f"{'✓ ' if key == period else ''}{label}", f"period:{key}")
            for key, label in (("today", "Сегодня"), ("7", "7 дней"), ("28", "28 дней"))
        ]
    )
    return rows


def _paging(page: int, more: bool, prefix: str, suffix: str = "") -> ButtonRows:
    buttons = []
    if page:
        buttons.append(("‹ Предыдущая", f"{prefix}:{page - 1}{suffix}"))
    if more:
        buttons.append(("Следующая ›", f"{prefix}:{page + 1}{suffix}"))
    return [buttons] if buttons else []


def _detail_nav(
    screen: str,
    data: Data,
    *,
    page: int,
    number: int,
    sort: str,
    family_id: str,
) -> ButtonRows:
    rows = page_rows(screen, data, page)
    more = bool(data.get("more"))
    if screen == "learners":
        return [
            [(f"Ученик …{str(row['user_id'])[-6:]}", f"learner:{row['user_id']}")]
            for row in rows
            if row.get("user_id")
        ] + _paging(page, more, "learners")
    if screen == "tasks":
        task_links = [
            (f"№{r['number']}", f"types:{r['number']}:0:sample") for r in rows if r.get("number")
        ]
        more = (page + 1) * NUMBER_PAGE_SIZE < len(data.get("rows", []))
        return [list(group) for group in batched(task_links, 5)] + _paging(page, more, "tasks")
    if screen == "types":
        type_rows: ButtonRows = [
            [(family_label(row["family_id"]), f"detail:{number}:{i}")]
            for i, row in enumerate(rows)
            if row.get("family_id")
        ]
        if number:
            type_rows.insert(0, [(f"Сводка №{number}", f"task:{number}")])
        type_rows += _paging(page, more, f"types:{number}", f":{sort}")
        type_rows.append(
            [
                (f"{'✓ ' if key == sort else ''}{label}", f"types:{number}:0:{key}")
                for key, label in SORT_LABELS.items()
            ]
        )
        return type_rows
    if screen == "task" and family_id:
        return [[("Проверить этот тип", "qa_family")]]
    if screen == "written":
        written_links = [
            (f"№{r['number']}", f"written:{r['number']}")
            for r in rows
            if not number and r.get("number")
        ]
        return [list(group) for group in batched(written_links, 3)] + _paging(
            page,
            more,
            f"written:{number}",
        )
    if screen == "replays":
        return _paging(page, more, "replays")
    return []


@dataclass(frozen=True)
class ScreenCopy:
    text: str
    caption: str
    markup: InlineKeyboardMarkup


def screen_copy(
    screen: str,
    data: Data,
    *,
    revision: str = "preview",
    period: str = "7",
    companion_status: str = "unavailable",
    release: str = "",
    tools_url: str | None = None,
    number: int = 0,
    page: int = 0,
    sort: str = "sample",
    family_id: str = "",
    learner_id: str = "",
    window: object = None,
    updated_at: datetime | None = None,
) -> ScreenCopy:
    screen = screen if screen in LABELS else "home"
    title = f"bop Admin · {LABELS[screen]}"
    if number and screen in {"types", "task", "written"}:
        title += f" · №{number}"
    subtitle = period_range(window)
    updated = f"Обновлено в {updated_at:%H:%M:%S} МСК" if updated_at is not None else ""
    header = "\n".join(filter(None, (_bold(title), subtitle, updated)))
    unavailable = data.get("unavailable")
    if unavailable and screen not in {"system", "tools"}:
        reason = {
            "unconfigured": "Подключение к аналитике отсутствует.",
            "timeout": "Аналитика не ответила вовремя.",
        }.get(str(unavailable), "Аналитика временно недоступна.")
        notice = _block(
            "Данные недоступны", [reason, "Нажмите «Обновить», чтобы повторить запрос."]
        )
        return ScreenCopy(_join(header, notice), "", _keyboard(_nav(screen, period), revision))
    photo_details = None
    match screen:
        case "home" | "usage":
            body = _activity(data, period, home=screen == "home", status=companion_status)
        case "learners":
            body = _learners(data, page)
        case "learner":
            body = _learner(data, learner_id)
        case "tasks":
            body = _tasks(data, page)
        case "types":
            body = _types(data, page, sort)
        case "task":
            body = _task(data, family_id)
        case "written":
            body, photo_details = _written(data, number, page)
        case "cost":
            body = _cost(data)
        case "system":
            body = _system(data, companion_status, release)
        case "replays":
            body = _replays(data, page)
        case _:
            body = _tools(tools_url)
    if screen == "tools":
        keyboard = _keyboard(
            [
                [("Открыть точные проверки", "tools_open")],
                [("← Назад", "back"), ("⌂ Главная", "home"), ("↻ Обновить", "refresh")],
            ],
            revision,
        )
        if tools_url:
            keyboard.inline_keyboard.insert(
                1, [InlineKeyboardButton(text="Открыть через /qa", url=tools_url)]
            )
    else:
        dynamic = _detail_nav(
            screen, data, page=page, number=number, sort=sort, family_id=family_id
        )
        keyboard = _keyboard(dynamic + _nav(screen, period), revision)
    page_label = (
        f"Страница {page + 1}"
        if screen in {"learners", "tasks", "types", "written", "replays"}
        and (
            page
            or data.get("more")
            or screen == "tasks"
            and len(data.get("rows", [])) > NUMBER_PAGE_SIZE
        )
        else ""
    )
    text = _join(header, body.summary, body.details, page_label)
    caption = _join(
        photo_details if photo_details is not None else body.details,
        " · ".join(filter(None, (updated, page_label))),
    )
    return ScreenCopy(text, caption, keyboard)


def render_screen(
    screen: str,
    data: Data | None = None,
    **context: Any,
) -> tuple[str, InlineKeyboardMarkup]:
    """Return the full HTML report and its actual Telegram keyboard."""
    copy = screen_copy(screen, data or {}, **context)
    return copy.text, copy.markup
