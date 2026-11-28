"""Data-driven bop Math PNG layouts for owner reports."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from math import ceil
from typing import Any

from app.admin.queries import MIN_RANK_SAMPLE
from app.admin.screens import (
    MOSCOW,
    WRITTEN_STATUSES,
    Data,
    budget_dates,
    count,
    day_label,
    family_label,
    learner_name,
    money,
    moscow_time,
    page_rows,
    period_range,
)
from app.bot.visual_cards import BopCanvas, CardLayoutError

LEFT = BopCanvas.padding
RIGHT = BopCanvas.width - LEFT
WIDTH = RIGHT - LEFT

TITLES = {
    "home": "Обзор",
    "usage": "Активность",
    "tasks": "По номерам",
    "task": "Результаты",
    "learner": "Карточка ученика",
    "written": "Письменные работы",
    "cost": "ИИ и расходы",
}


def _heading(canvas: BopCanvas, title: str, window: object) -> int:
    canvas.text(LEFT, 15, "bop Admin", 15, bold=True)
    canvas.rect((LEFT, 34, LEFT + 30, 37), "orange", 2)
    canvas.text(LEFT, 49, title, canvas.fit(title, WIDTH, 29, 22), bold=True)
    if timespan := period_range(window):
        canvas.text(LEFT, 84, timespan, 13, fill="muted")
        return 112
    return 95


def _caption(canvas: BopCanvas, y: int, text: str) -> int:
    lines = canvas.wrap(text, WIDTH, 14)
    return y + canvas.paragraph(LEFT, y, lines, 14, 19, fill="muted")


def _values(
    canvas: BopCanvas,
    y: int,
    values: Sequence[tuple[str, str]],
    *,
    size: int = 24,
) -> int:
    """A single aligned row with direct labels and shared spacing."""
    col_width = WIDTH / len(values)
    height = 0
    for index, (value, label) in enumerate(values):
        x = LEFT + index * col_width
        value_size = canvas.fit(value, col_width - 8, size, 13)
        canvas.text(x, y, value, value_size, bold=True)
        lines = canvas.wrap(label, col_width - 9, 14)
        height = max(height, canvas.paragraph(x, y + size + 5, lines, 14, 17, fill="muted"))
    return ceil(y + size + 5 + height)


def _section(canvas: BopCanvas, y: int, title: str) -> int:
    canvas.line(((LEFT, y), (RIGHT, y)))
    canvas.text(LEFT, y + 12, title, 16, bold=True)
    return y + 38


def _home(canvas: BopCanvas, y: int, data: Data, period: str) -> int:
    canvas.rect((LEFT, y, RIGHT, y + 83), "sage", 9)
    active = count(data, "active")
    canvas.text(LEFT + 13, y + 12, active, canvas.fit(active, 139, 33, 16), bold=True)
    canvas.text(LEFT + 13, y + 53, "Занимались", 15, bold=True)
    canvas.line(((LEFT + 159, y + 14), (LEFT + 159, y + 68)))
    first_y = y + (32 if period == "today" else 18)
    first = count(data, "first")
    canvas.text(LEFT + 173, first_y, "Начали впервые", 14)
    canvas.text(RIGHT - 13, first_y - 3, first, canvas.fit(first, 65, 19, 13), bold=True, align="r")
    if period != "today":
        canvas.text(LEFT + 173, y + 47, "В разные дни", 14)
        repeats = count(data, "repeat_days")
        canvas.text(
            RIGHT - 13, y + 44, repeats, canvas.fit(repeats, 65, 19, 13), bold=True, align="r"
        )
    y = (
        _values(
            canvas,
            y + 98,
            [
                (count(data, "answered"), "Заданий с ответом"),
                (count(data, "graded"), "Проверок с оценкой"),
                (money(data.get("known_cost")), "Известные расходы на ИИ"),
            ],
        )
        + 5
    )
    if not data.get("active"):
        y = _caption(canvas, y + 5, "За этот период занятий пока нет.")
    return y


def _day_bars(canvas: BopCanvas, y: int, days: Sequence[Data]) -> int:
    counts = [int(row.get("active") or 0) for row in days]
    peak = max(counts, default=0)
    if not peak:
        return _caption(canvas, y, "За этот период занятий пока нет.")
    chart_left = LEFT + max(26, 8 * len(str(peak)) + 9)
    plot_top, bottom = y + 5, y + 82
    step = (RIGHT - chart_left) / len(counts)
    for tick in sorted({0, peak // 2, peak} if peak >= 4 else {0, peak}):
        tick_y = bottom - (bottom - plot_top) * tick / peak
        canvas.line(((chart_left, tick_y), (RIGHT, tick_y)))
        canvas.text(chart_left - 7, tick_y - 6, str(tick), 13, fill="muted", align="r")
    bar = min(34, step * 0.68)
    for index, value in enumerate(counts):
        if value:
            x = chart_left + step * (index + 0.5)
            top = bottom - (bottom - plot_top) * value / peak
            canvas.rect((x - bar / 2, top, x + bar / 2, bottom), "good", 2)
    if len(days) == 1:
        canvas.text(
            chart_left + step / 2,
            bottom + 8,
            day_label(days[0].get("day")),
            13,
            align="m",
            fill="muted",
        )
    else:
        canvas.text(chart_left, bottom + 8, day_label(days[0].get("day")), 13, fill="muted")
        canvas.text(RIGHT, bottom + 8, day_label(days[-1].get("day")), 13, align="r", fill="muted")
    return bottom + 26


def _usage(canvas: BopCanvas, y: int, data: Data, period: str) -> int:
    values = [(count(data, "active"), "Занимались"), (count(data, "first"), "Начали впервые")]
    if period != "today":
        values.append((count(data, "repeat_days"), "В разные дни"))
    y = _values(canvas, y, values, size=28)
    if period == "today":
        return y if data.get("active") else _caption(canvas, y + 10, "Сегодня занятий пока нет.")
    y = _section(canvas, y + 13, "Ученики по дням")
    return _day_bars(canvas, y, data.get("days", [])[:28])


def _ratio_bar(canvas: BopCanvas, x: float, y: int, w: int, value: int, total: int) -> None:
    if total >= MIN_RANK_SAMPLE:
        canvas.rect((x, y, x + w, y + 6), "sage_deep", 3)
        if value:
            end = x + max(2, w * min(value, total) / total)
            canvas.rect((x, y, end, y + 6), "good", 3)


def _tasks(canvas: BopCanvas, y: int, data: Data, page: int) -> int:
    rows = page_rows("tasks", data, page)
    if not any(row.get("answered") for row in rows):
        return _caption(canvas, y, "На этой странице за период нет заданий с ответом.")
    canvas.text(LEFT, y, "Номер", 13, bold=True, fill="muted")
    canvas.text(LEFT + 135, y, "Ученики", 13, bold=True, align="r", fill="muted")
    canvas.text(RIGHT, y, "Решено / с ответом", 13, bold=True, align="r", fill="muted")
    y += 20
    for row in rows:
        canvas.line(((LEFT, y), (RIGHT, y)))
        canvas.text(LEFT, y + 5, f"№{row.get('number', '—')}", 15, bold=True)
        canvas.text(LEFT + 135, y + 6, count(row, "users"), 14, align="r")
        _ratio_bar(
            canvas,
            LEFT + 151,
            y + 11,
            72,
            int(row.get("solved") or 0),
            int(row.get("answered") or 0),
        )
        sample = f"{count(row, 'solved')} / {count(row, 'answered')}"
        canvas.text(RIGHT, y + 5, sample, canvas.fit(sample, 133, 15, 12), align="r", bold=True)
        y += 24
    return y


def _task(canvas: BopCanvas, y: int, data: Data, family_id: str) -> int:
    if family_id:
        lines = canvas.wrap(family_label(family_id), WIDTH, 16, bold=True)
        y += canvas.paragraph(LEFT, y, lines, 16, 20, bold=True) + 12
    answered = int(data.get("answered") or 0)
    solved = int(data.get("solved") or 0)
    if answered:
        label = f"{count(data, 'solved')} из {count(data, 'answered')}"
        canvas.text(LEFT, y, label, canvas.fit(label, WIDTH, 31, 21), bold=True)
        canvas.text(LEFT, y + 38, "Заданий решено верно", 14, fill="muted")
        if answered >= MIN_RANK_SAMPLE:
            canvas.text(
                RIGHT, y + 38, f"{solved / answered:.0%}", 15, bold=True, align="r", fill="good"
            )
            _ratio_bar(canvas, LEFT, y + 61, WIDTH, solved, answered)
        y += 85 if answered >= MIN_RANK_SAMPLE else 64
    else:
        y = _caption(canvas, y, "За этот период ответов пока нет.") + 10
    return _values(
        canvas,
        y,
        [
            (count(data, "users"), "Ученики"),
            (count(data, "issued"), "Заданий выдано"),
        ],
    )


def _learner(canvas: BopCanvas, y: int, data: Data) -> int:
    name = learner_name(data)[:160]
    # Profile text is user-controlled and may be a single very long word.
    # Elide the label, never fall back to a long report just because of a name.
    lines = ["Ученик без имени"]
    for end in range(len(name), 0, -1):
        candidate = name if end == len(name) else name[:end].rstrip() + "…"
        try:
            wrapped = canvas.wrap(candidate, WIDTH, 21, bold=True)
        except CardLayoutError:
            continue
        if len(wrapped) <= 2:
            lines = wrapped
            break
    y += canvas.paragraph(LEFT, y, lines, 21, 25, bold=True) + 7
    if data.get("username"):
        username = f"@{str(data['username'])[:32]}"
        canvas.text(LEFT, y, username, canvas.fit(username, WIDTH, 14, 10), fill="muted")
        y += 25
    if data.get("last_activity"):
        y = _caption(canvas, y, f"Последнее занятие · {moscow_time(data.get('last_activity'))}")
    else:
        y = _caption(canvas, y, "За выбранный период занятий не было.")
    y = _values(
        canvas,
        y + 12,
        [
            (count(data, "days"), "Дни занятий"),
            (count(data, "solved"), "Решено"),
            (count(data, "answered"), "Заданий с ответом"),
        ],
    )
    numbers = ", ".join(str(number) for number in data.get("numbers", [])[:25])
    if numbers:
        y = _caption(canvas, y + 10, f"Номера занятий · {numbers}")
    if not data.get("submitted"):
        return y
    y = _section(canvas, y + 13, "Письменные работы")
    points = "—" if data.get("points") is None else count(data, "points")
    return _values(
        canvas,
        y,
        [
            (count(data, "submitted"), "Отправлено"),
            (count(data, "graded"), "С оценкой"),
            (points, "Всего баллов"),
        ],
        size=22,
    )


def _written_statuses(canvas: BopCanvas, y: int, data: Data) -> int:
    tones = ("good", "muted", "warn", "bad", "muted")
    y = _section(canvas, y, "Статусы проверок")
    for (key, label), tone in zip(WRITTEN_STATUSES, tones, strict=True):
        canvas.text(LEFT, y, label, 14)
        value = count(data, key)
        canvas.text(
            RIGHT, y - 1, value, 16, bold=True, fill=tone if value != "0" else "muted", align="r"
        )
        y += 22
    return y


def _scores(canvas: BopCanvas, y: int, rows: Sequence[Data]) -> int:
    columns = (
        (LEFT + 146, "0 баллов", "zero"),
        (LEFT + 249, "1 балл", "one"),
        (RIGHT, "2 балла", "two"),
    )
    y = _section(canvas, y, "Баллы по номерам")
    for x, title, _ in columns:
        canvas.text(x, y, title, 13, bold=True, align="r", fill="muted")
    y += 20
    for row in rows:
        canvas.line(((LEFT, y), (RIGHT, y)))
        canvas.text(LEFT, y + 5, f"№{row.get('number', '—')}", 14, bold=True)
        for x, _, key in columns:
            canvas.text(x, y + 5, count(row, key), 14, align="r")
        y += 22
    return y


def _written(canvas: BopCanvas, y: int, data: Data, number: int, page: int) -> int:
    y = _values(
        canvas,
        y,
        [
            (count(data, "issued"), "Заданий выдано"),
            (count(data, "issues_submitted"), "С отправкой"),
            (count(data, "submitted"), "Всего отправок"),
        ],
    )
    canvas.text(LEFT, y + 7, f"Повторные отправки · {count(data, 'revisions')}", 14, fill="muted")
    if not data.get("submitted"):
        return _caption(canvas, y + 32, "За этот период работы на проверку не отправляли.")
    y = _written_statuses(canvas, y + 36, data)
    rows = page_rows("written", data, page)
    if rows and not number:
        y = _scores(canvas, y + 8, rows)
    return y


def _cost(canvas: BopCanvas, y: int, data: Data) -> int:
    amount = money(data.get("known_cost"))
    canvas.text(LEFT, y, amount, canvas.fit(amount, WIDTH, 33, 23), bold=True)
    canvas.text(LEFT, y + 40, "Известные расходы за период", 15, fill="muted")
    y = _section(canvas, y + 69, "Месячный бюджет · UTC")
    y = _caption(canvas, y, budget_dates(data))
    y = _caption(canvas, y + 2, f"Лимит · {money(data.get('budget'))}") + 12
    return _values(
        canvas,
        y,
        [
            (money(data.get("spent")), "Потрачено"),
            (money(data.get("held")), "В резерве"),
            (money(data.get("available")), "Доступно"),
        ],
        size=22,
    )


def render_summary(
    screen: str,
    data: Data,
    *,
    period: str = "7",
    window: object = None,
    number: int = 0,
    page: int = 0,
    family_id: str = "",
    updated_at: datetime | None = None,
    **_: Any,
) -> bytes | None:
    if (
        screen not in TITLES
        or data.get("unavailable")
        or (screen == "learner" and not data.get("found"))
    ):
        return None
    title = TITLES[screen]
    if number and screen in {"task", "written"}:
        title += f" · №{number}"
    canvas = BopCanvas()
    top = _heading(canvas, title, window)
    match screen:
        case "home":
            bottom = _home(canvas, top, data, period)
        case "usage":
            bottom = _usage(canvas, top, data, period)
        case "tasks":
            bottom = _tasks(canvas, top, data, page)
        case "task":
            bottom = _task(canvas, top, data, family_id)
        case "learner":
            bottom = _learner(canvas, top, data)
        case "written":
            bottom = _written(canvas, top, data, number, page)
        case _:
            bottom = _cost(canvas, top, data)
    if screen == "home":
        canvas.text(
            LEFT, bottom + 12, f"Аккаунтов всего · {count(data, 'registered')}", 12, fill="muted"
        )
        if updated_at is not None:
            canvas.text(
                RIGHT,
                bottom + 12,
                f"На {updated_at.astimezone(MOSCOW):%H:%M} МСК",
                12,
                fill="muted",
                align="r",
            )
        bottom += 28
    elif updated_at is not None:
        canvas.text(
            LEFT,
            bottom + 12,
            f"Обновлено {updated_at.astimezone(MOSCOW):%H:%M} МСК",
            12,
            fill="muted",
        )
        bottom += 28
    return canvas.png(bottom)
