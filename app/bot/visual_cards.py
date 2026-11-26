"""Offline Pillow renderer for the bop Math cards shown above Telegram keyboards."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
from itertools import batched
from math import ceil
from pathlib import Path

from matplotlib import get_data_path
from PIL import Image, ImageDraw, ImageFont

from app.bot.visual_models import (
    VisualBreakdown,
    VisualCard,
    VisualEntry,
    VisualMetric,
    VisualPractice,
    VisualSection,
)

_WIDTH = 400
_SCALE = 3
_PAD = 16
_RIGHT = _WIDTH - _PAD
_CONTENT = _RIGHT - _PAD
_MAX_HEIGHT = 900
_MAX_FIELD_LENGTH = 1200
_PALETTE = {
    "paper": "#F8F4E9", "ink": "#1F3531", "muted": "#4A6157", "line": "#CBD2C2",
    "orange": "#F15E45", "sage": "#E6EBDF", "sage_deep": "#D9E2D0", "peach": "#F6DDD0",
    "cool": "#E2ECE8", "good": "#256043", "good_bg": "#E3ECDD", "warn": "#795415",
    "warn_bg": "#F8E8C8", "bad": "#903D34", "bad_bg": "#F5DFDA",
    "other_correct": "#87A583", "skipped_segment": "#80918A",
}
_TEXT_TONE = {"neutral": "ink", "muted": "muted", "good": "good", "warn": "warn", "bad": "bad"}
_SURFACE = {
    "neutral": "cool", "muted": "sage", "good": "good_bg", "warn": "warn_bg", "bad": "bad_bg",
}
_STORY_SURFACE = {
    "TYRES": "cool", "PAPER": "peach", "STOVE": "peach", "TARIFF": "cool",
    "GARDEN": "sage", "FLAT": "sage",
}
_STORY_DETAILS = {
    "TYRES": "Размеры колёс", "PAPER": "Форматы листов", "STOVE": "Размеры и цены",
    "TARIFF": "Минуты и оплата", "GARDEN": "План участка", "FLAT": "План квартиры",
}
_OUTCOME_ICONS = {
    "independent", "retry", "hint", "correct", "wrong", "skipped", "solution", "pending",
}
_Point = tuple[float, float]
_Bounds = tuple[float, float, float, float]


@dataclass(frozen=True)
class _TileStyle:
    indent: int
    size: int
    leading: int
    min_height: int
    top: int
    gap: int


_TILE_STYLES = {
    "numbers": _TileStyle(48, 14, 16, 35, 6, 4),
    "part2": _TileStyle(11, 14, 16, 79, 43, 8),
    "stories": _TileStyle(56, 17, 20, 73, 10, 8),
}


class CardLayoutError(ValueError):
    """Card content cannot be rendered within the supported layout."""


@lru_cache(maxsize=24)
def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    root = Path(get_data_path()) / "fonts" / "ttf"
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    return ImageFont.truetype(str(root / name), size * _SCALE, layout_engine=ImageFont.Layout.BASIC)


def _measure(text: str, font: ImageFont.FreeTypeFont) -> float:
    left, _, right, _ = font.getbbox(text)
    return (right - left) / _SCALE


class _Canvas:
    def __init__(self) -> None:
        self.image = Image.new("RGB", (_WIDTH * _SCALE, _MAX_HEIGHT * _SCALE), _PALETTE["paper"])
        self.draw = ImageDraw.Draw(self.image)

    def wrap(self, text: str, width: float, size: int, bold: bool = False) -> list[str]:
        if len(text) > _MAX_FIELD_LENGTH:
            raise CardLayoutError("Visual card field exceeds the supported length")
        font = _font(size, bold)
        lines: list[str] = []
        for paragraph in text.splitlines():
            line = ""
            for word in paragraph.split():
                candidate = f"{line} {word}" if line else word
                if _measure(candidate, font) <= width:
                    line = candidate
                    continue
                if _measure(word, font) > width:
                    raise CardLayoutError("Visual card contains a word too wide for its section")
                lines.append(line)
                line = word
            if line:
                lines.append(line)
        return lines

    def fit(self, text: str, width: float, size: int, minimum: int) -> int:
        if len(text) > _MAX_FIELD_LENGTH:
            raise CardLayoutError("Visual card field exceeds the supported length")
        for candidate in range(size, minimum - 1, -1):
            if _measure(text, _font(candidate, True)) <= width:
                return candidate
        return minimum

    def text(
        self, x: float, y: float, text: str, size: int, *, bold: bool = False,
        fill: str = "ink", align: str = "l",
    ) -> None:
        font = _font(size, bold)
        ascent, _ = font.getmetrics()
        position = (round(x * _SCALE), round(y * _SCALE) + int(ascent * 0.82))
        anchor = align + "s"
        left, top, right, bottom = self.draw.textbbox(position, text, font=font, anchor=anchor)
        if left < 0 or right > self.image.width or top < 0 or bottom > self.image.height:
            raise CardLayoutError("Visual card text exceeds the canvas")
        self.draw.text(position, text, font=font, fill=_PALETTE[fill], anchor=anchor)

    def paragraph(
        self, x: float, y: float, lines: list[str], size: int, leading: int, *,
        bold: bool = False, fill: str = "ink",
    ) -> int:
        for index, line in enumerate(lines):
            self.text(x, y + index * leading, line, size, bold=bold, fill=fill)
        return len(lines) * leading

    def rect(
        self, box: _Bounds, fill: str, radius: int = 0, *, outline: str | None = None,
    ) -> None:
        bounds = tuple(round(value * _SCALE) for value in box)
        stroke = _PALETTE[outline] if outline else None
        self.draw.rounded_rectangle(
            bounds, radius=radius * _SCALE, fill=_PALETTE[fill], outline=stroke, width=_SCALE,
        )

    def line(self, points: Iterable[_Point], fill: str = "line", width: float = 1) -> None:
        self.draw.line(
            [(round(x * _SCALE), round(y * _SCALE)) for x, y in points],
            fill=_PALETTE[fill], width=round(width * _SCALE), joint="curve",
        )

    def circle(
        self, x: float, y: float, radius: float, fill: str | None = None, *, outline: str = "ink",
    ) -> None:
        bounds = tuple(round(v * _SCALE) for v in (x - radius, y - radius, x + radius, y + radius))
        self.draw.ellipse(bounds, fill=_PALETTE[fill] if fill else None,
                          outline=_PALETTE[fill or outline], width=round(1.5 * _SCALE))

    def png(self, bottom: int) -> bytes:
        height = (bottom + _PAD) * _SCALE
        if height > self.image.height:
            raise CardLayoutError("Visual card exceeds the maximum height")
        with BytesIO() as output:
            self.image.crop((0, 0, self.image.width, height)).save(output, format="PNG")
            return output.getvalue()


def _heading(canvas: _Canvas, card: VisualCard) -> int:
    canvas.text(_PAD, 16, "bop Math", 16, bold=True)
    canvas.rect((_PAD, 37, _PAD + 30, 40), "orange", 2)
    if card.screen == "welcome":
        x = _PAD + 14
        title = canvas.wrap(card.title, 245, 31, True)
        subtitle = canvas.wrap(card.subtitle, 245, 15)
        height = max(121, 24 + 36 * len(title) + 19 * len(subtitle))
        canvas.rect((_PAD, 56, _RIGHT, 56 + height), "sage", 13)
        text_height = canvas.paragraph(x, 72, title, 31, 36, bold=True)
        canvas.paragraph(x, 76 + text_height, subtitle, 15, 19, fill="muted")
        # A triangle and its drawn height introduce the subject in the approved welcome layout.
        canvas.circle(_RIGHT - 66, 113, 35, "sage_deep")
        canvas.line(((_RIGHT - 89, 134), (_RIGHT - 55, 84), (_RIGHT - 44, 134),
                     (_RIGHT - 89, 134)), "ink", 2)
        canvas.line(((_RIGHT - 69, 134), (_RIGHT - 69, 104)), "good", 1.4)
        return 56 + height
    size = canvas.fit(card.title, _CONTENT, 31, 25)
    title = canvas.wrap(card.title, _CONTENT, size, True)
    y = 51 + canvas.paragraph(_PAD, 51, title, size, 37, bold=True)
    return y + canvas.paragraph(_PAD, y, canvas.wrap(card.subtitle, _CONTENT, 15),
                                15, 19, fill="muted")


def _practical(canvas: _Canvas, y: int, section: VisualSection) -> int:
    names = canvas.wrap(section.title, _CONTENT - 24, 16, True)
    label_height = len(names) * 20
    height = 45 + label_height
    canvas.rect((_PAD, y, _RIGHT, y + height), "peach", 13)
    canvas.paragraph(_PAD + 12, y + 8, names, 16, 20, bold=True)
    number_y = y + 11 + label_height
    width = _CONTENT / len(section.entries)
    for index, entry in enumerate(section.entries):
        x = _PAD + index * width
        number = (entry.key or entry.label).removeprefix("№")
        if len(canvas.wrap(number, width - 8, 25, True)) != 1:
            raise CardLayoutError("Visual card practical number must fit on one line")
        canvas.text(x + width / 2, number_y, number, 25, bold=True, align="m")
        if index:
            canvas.line(((x, number_y + 2), (x, number_y + 26)))
    return y + height


def _miniature(canvas: _Canvas, code: str, x: float, y: float) -> None:
    def stroke(*points: _Point, color: str = "ink", weight: float = 1.5) -> None:
        canvas.line(((x + px, y + py) for px, py in points), color, weight)

    def box(a: int, b: int, c: int, d: int, fill: str) -> None:
        canvas.rect((x + a, y + b, x + c, y + d), fill, outline="ink")

    if code == "TYRES":
        canvas.circle(x + 19, y + 16, 13)
        canvas.circle(x + 19, y + 16, 7)
        stroke((19, 16), (32, 16), color="good")
        stroke((29, 13), (32, 16), (29, 19), color="good")
    elif code == "PAPER":
        box(7, 3, 25, 28, "paper")
        box(17, 9, 33, 31, "cool")
        stroke((20, 15), (29, 15))
        stroke((20, 20), (29, 20))
    elif code == "STOVE":
        box(8, 10, 31, 28, "cool")
        stroke((22, 10), (22, 3), (28, 3), (28, 10))
        box(12, 14, 24, 24, "paper")
        stroke((10, 29), (10, 32))
        stroke((29, 29), (29, 32))
    elif code == "TARIFF":
        stroke((6, 4), (6, 29), (35, 29))
        stroke((10, 25), (16, 25), (16, 18), (24, 18), (24, 10), (33, 10),
               color="good", weight=2)
    elif code == "GARDEN":
        box(5, 5, 34, 29, "paper")
        box(8, 8, 17, 16, "sage_deep")
        box(23, 19, 31, 26, "cool")
        stroke((19, 5), (19, 22), (23, 22), color="good")
    elif code == "FLAT":
        box(5, 6, 34, 29, "paper")
        stroke((17, 6), (17, 15))
        stroke((17, 23), (17, 29))
        stroke((17, 18), (24, 18))
        stroke((29, 18), (34, 18))


def _tiles(
    canvas: _Canvas, y: int, entries: tuple[VisualEntry, ...], screen: str, surface: str,
) -> int:
    style = _TILE_STYLES.get(screen)
    if style is None:
        raise CardLayoutError("Visual card screen does not support tiles")
    gap = 7 if screen == "numbers" else 8
    wide_last = screen == "numbers" and entries[-1].key.removeprefix("№") == "19"
    rows = list(batched(entries[:-1] if wide_last else entries, 2))
    if wide_last:
        rows.append(entries[-1:])
    for row in rows:
        keys = tuple(entry.key.removeprefix("№") for entry in row)
        width = (_CONTENT - gap) // 2
        if screen == "numbers" and "17" in keys:
            width = 211 if keys[0] == "17" else _CONTENT - gap - 211
        widths: tuple[int, ...]
        if len(row) == 2:
            widths = (width, _CONTENT - width - gap)
        else:
            widths = (_CONTENT if screen != "numbers" or keys == ("19",) else width,)
        x = _PAD
        blocks = []
        for entry, tile_width in zip(row, widths, strict=True):
            available = tile_width - style.indent - 7
            lines = canvas.wrap(entry.label, available, style.size, True)
            detail = canvas.wrap(entry.detail or _STORY_DETAILS.get(entry.icon, ""), available, 13)
            text_height = len(lines) * style.leading + len(detail) * 17
            blocks.append((entry, x, tile_width, lines, detail, text_height))
            x += tile_width + gap
        height = max(style.min_height, max(block[-1] for block in blocks) + style.top + 6)
        for entry, x, tile_width, lines, detail, text_height in blocks:
            fill = _STORY_SURFACE.get(entry.icon, surface)
            if screen == "part2" and entry.key.removeprefix("№") in {"23", "24", "25"}:
                fill = "cool"
            canvas.rect((x, y, x + tile_width, y + height), fill, 9)
            number = entry.key.removeprefix("№")
            label_y = y + (height - text_height) / 2
            if screen == "part2":
                canvas.text(x + 11, y + 9, number, 26, bold=True)
                label_y = y + 43
            elif screen == "stories":
                _miniature(canvas, entry.icon, x + 11, y + (height - 36) / 2)
            else:
                canvas.text(x + 37, y + (height - 24) / 2, number, 22, bold=True, align="r")
            used = canvas.paragraph(x + style.indent, label_y, lines, style.size, style.leading,
                                    bold=True)
            canvas.paragraph(x + style.indent, label_y + used, detail, 13, 17, fill="muted")
        y += height + style.gap
    return y - style.gap


def _metrics(
    canvas: _Canvas, y: int, metrics: tuple[VisualMetric, ...], *, equal_columns: bool = False,
) -> int:
    for row in batched(metrics, 3):
        font = _font(13, True)
        for metric in row:
            if len(metric.label) > _MAX_FIELD_LENGTH:
                raise CardLayoutError("Visual card metric label exceeds the supported length")
        minimums = [max(89, 18 + ceil(max((_measure(word, font) for word in metric.label.split()),
                                        default=0))) for metric in row]
        slack = (_CONTENT - sum(minimums)) / len(row)
        if slack < 0:
            raise CardLayoutError("Visual card metric labels exceed the available width")
        widths = ([_CONTENT / len(row)] * len(row) if equal_columns
                  else [minimum + slack for minimum in minimums])
        sizes = [canvas.fit(metric.value, width - 18, 30, 20)
                 for metric, width in zip(row, widths, strict=True)]
        values = [canvas.wrap(metric.value, width - 18, size, True)
                  for metric, width, size in zip(row, widths, sizes, strict=True)]
        labels = [canvas.wrap(metric.label, width - 18, 13, True)
                  for metric, width in zip(row, widths, strict=True)]
        text_top = max(36, max((size + 3) * len(lines)
                               for size, lines in zip(sizes, values, strict=True))) + 8
        height = max(65, text_top + 4 + 16 * max(map(len, labels)))
        canvas.rect((_PAD, y, _RIGHT, y + height), "sage", 12)
        x: float = _PAD
        columns = zip(row, values, sizes, labels, widths, strict=True)
        for metric, value, size, label, width in columns:
            if x > _PAD:
                canvas.line(((x, y + 10), (x, y + height - 11)))
            canvas.paragraph(x + 9, y + 8, value, size, size + 3, bold=True,
                             fill=_TEXT_TONE[metric.tone])
            canvas.paragraph(x + 9, y + text_top, label, 13, 16, bold=True, fill="muted")
            x += width
        y += height + 8
    return y - 8


def _list(canvas: _Canvas, y: int, section: VisualSection, screen: str) -> int:
    for entry in section.entries:
        inset = 10 if screen == "training_result" else 0
        start = _PAD + inset + (30 if entry.key else 0)
        values = canvas.wrap(entry.value, 110, 14, True)
        width = _RIGHT - inset - start - (116 if values else 0)
        labels = canvas.wrap(entry.label, width, 15, True)
        detail = canvas.wrap(entry.detail, _RIGHT - inset - start, 13)
        primary_height = max(len(labels) * 18, len(values) * 17)
        height = max(34, 14 + primary_height + len(detail) * 17)
        if inset:
            canvas.rect((_PAD, y, _RIGHT, y + height), "cool", 8)
        else:
            canvas.line(((_PAD, y), (_RIGHT, y)))
        if entry.key:
            if len(canvas.wrap(entry.key, 24, 15, True)) != 1:
                raise CardLayoutError("Visual card row number must fit on one line")
            canvas.text(start - 10, y + 7, entry.key, 15, bold=True, fill="muted", align="r")
        canvas.paragraph(start, y + 7, labels, 15, 18, bold=True)
        canvas.paragraph(start, y + 7 + primary_height, detail, 13, 17,
                         fill=_TEXT_TONE[entry.tone])
        for index, value in enumerate(values):
            canvas.text(_RIGHT - inset, y + 7 + index * 17, value, 14, bold=True, align="r")
        y += height + (4 if inset else 0)
    return y - (4 if screen == "training_result" else 0)


def _outcome_mark(canvas: _Canvas, x: float, y: float, icon: str, tone: str) -> None:
    fill = _TEXT_TONE[tone]
    if icon in {"independent", "retry", "hint", "correct"}:
        if icon == "hint":
            canvas.circle(x, y, 8)
        if icon == "correct":
            canvas.line(((x - 2, y - 6), (x + 2, y - 6)), fill)
        for center in (x - 4.5, x + 5.5) if icon == "independent" else (x,):
            canvas.line(((center - 3.5, y), (center - 1, y + 3), (center + 4, y - 3.8)), fill, 1.8)
    elif icon == "wrong":
        canvas.line(((x - 4, y - 4), (x + 4, y + 4)), fill, 1.8)
        canvas.line(((x - 4, y + 4), (x + 4, y - 4)), fill, 1.8)
    elif icon == "skipped":
        canvas.line(((x - 5, y), (x + 5, y)), fill, 1.8)
    elif icon == "solution":
        canvas.line(((x - 5, y - 6), (x + 5, y - 6), (x + 5, y + 6), (x - 5, y + 6),
                     (x - 5, y - 6)), fill, 1.5)
        canvas.line(((x - 2, y - 2), (x + 2, y - 2)), fill)
        canvas.line(((x - 2, y + 2), (x + 2, y + 2)), fill)
    elif icon == "pending":
        for offset in (-4, 0, 4):
            canvas.circle(x + offset, y, 0.8, fill)


def _outcomes(canvas: _Canvas, y: int, entries: tuple[VisualEntry, ...]) -> int:
    if len(entries) <= 5 or any(
        entry.icon not in _OUTCOME_ICONS or entry.detail or entry.value for entry in entries
    ):
        for entry in entries:
            label = canvas.wrap(entry.label, _CONTENT - 87, 14)
            detail = canvas.wrap(" · ".join(filter(None, (entry.detail, entry.value))),
                                 _CONTENT - 87, 13)
            height = max(29, 12 + len(label) * 17 + len(detail) * 16)
            canvas.rect((_PAD, y, _RIGHT, y + height), _SURFACE[entry.tone], 6)
            if entry.key:
                if len(canvas.wrap(entry.key, 41, 15, True)) != 1:
                    raise CardLayoutError("Visual card outcome number must fit on one line")
                canvas.text(_PAD + 9, y + 6, entry.key, 15, bold=True)
            _outcome_mark(canvas, _PAD + 61, y + 15, entry.icon, entry.tone)
            used = canvas.paragraph(_PAD + 76, y + 6, label, 14, 17)
            canvas.paragraph(_PAD + 76, y + 6 + used, detail, 13, 16, fill="muted")
            y += height + 4
        return y - 4

    width = (_CONTENT - 4 * 6) / 5
    legend: dict[str, VisualEntry] = {}
    for row in batched(entries, 5):
        for index, entry in enumerate(row):
            if len(canvas.wrap(entry.key, width - 30, 16, True)) != 1:
                raise CardLayoutError("Visual card outcome number must fit on one line")
            if entry.icon in legend and entry.label != legend[entry.icon].label:
                raise CardLayoutError("Visual card has conflicting labels for an outcome")
            legend[entry.icon] = entry
            x = _PAD + index * (width + 6)
            canvas.rect((x, y, x + width, y + 36), _SURFACE[entry.tone], 7)
            canvas.text(x + 7, y + 9, entry.key, 16, bold=True)
            _outcome_mark(canvas, x + width - 13, y + 18, entry.icon, entry.tone)
        y += 42
    y += 5
    for pair in batched(legend.values(), 2):
        lines_by_entry = [canvas.wrap(entry.label, _CONTENT / 2 - 25, 13) for entry in pair]
        for index, (entry, lines) in enumerate(zip(pair, lines_by_entry, strict=True)):
            x = _PAD + index * (_CONTENT / 2)
            _outcome_mark(canvas, x + 9, y + 7, entry.icon, entry.tone)
            canvas.paragraph(x + 24, y, lines, 13, 16, fill="muted")
        y += 4 + 16 * max(map(len, lines_by_entry))
    return y


def _result_breakdown(canvas: _Canvas, y: int, result: VisualBreakdown) -> int:
    groups = (
        (result.independent, "Самостоятельно", "independent", "good", "good"),
        (result.assisted, "Другие верные", "retry", "good", "other_correct"),
        (result.unsolved, "Не решено", "wrong", "bad", "bad"),
        (result.skipped, "Пропущено", "skipped", "muted", "skipped_segment"),
    )
    if any(count < 0 for count, *_ in groups):
        raise CardLayoutError("Visual card result contains a negative count")

    total = result.total
    y = _metrics(canvas, y, (
        VisualMetric(f"{result.independent + result.assisted} из {total}", "Решено верно"),
        VisualMetric(f"{result.independent} из {total}", "Самостоятельно", "good"),
    ), equal_columns=True) + 10
    canvas.rect((_PAD, y, _RIGHT, y + 9), "sage", 4)
    completed = 0
    for count, _, _, _, color in groups:
        if count:
            x = _PAD + _CONTENT * completed / total
            completed += count
            right = _PAD + _CONTENT * completed / total
            canvas.rect((x, y, right, y + 9), color, 3 if right - x >= 6 else 0)

    y += 17
    width = _CONTENT / 2
    for pair in batched(groups, 2):
        labels = [canvas.wrap(f"{count} · {label}", width - 27, 14) for count, label, *_ in pair]
        for index, ((_, _, icon, tone, _), lines) in enumerate(zip(pair, labels, strict=True)):
            x = _PAD + index * width
            _outcome_mark(canvas, x + 10, y + 7, icon, tone)
            canvas.paragraph(x + 24, y, lines, 14, 17)
        y += 3 + 17 * max(map(len, labels))
    return y - 2


def _result_practice(canvas: _Canvas, y: int, skills: tuple[VisualPractice, ...]) -> int:
    canvas.line(((_PAD, y), (_RIGHT, y)))
    canvas.text(_PAD, y + 10, "Закрепление типа", 15, bold=True)
    y += 33
    for index, skill in enumerate(skills):
        valid_count = 1 <= skill.target <= 16 and 0 <= skill.count <= skill.target
        if not valid_count or skill.confirmed != (skill.count == skill.target):
            raise CardLayoutError("Visual card practice count conflicts with its target or status")
        if index:
            canvas.line(((_PAD, y), (_RIGHT, y)))
            y += 8
        lines = canvas.wrap(skill.label, _CONTENT, 16, True)
        y += canvas.paragraph(_PAD, y, lines, 16, 20, bold=True)
        for position in range(skill.target):
            fill = "good" if position < skill.count else None
            canvas.circle(_PAD + 6 + position * 18, y + 8, 5, fill, outline="muted")
        y += 22
        status = canvas.wrap(skill.status, _CONTENT, 14, skill.confirmed)
        y += canvas.paragraph(_PAD, y, status, 14, 18, bold=skill.confirmed,
                              fill="good" if skill.confirmed else "muted")
    return y


def render_card(card: VisualCard) -> bytes:
    """Render a complete, opaque 1200px wide PNG or raise a layout error."""
    canvas = _Canvas()
    y = _heading(canvas, card)
    if card.screen == "training_result" and card.breakdown is not None:
        y = _result_breakdown(canvas, y + 12, card.breakdown)
    elif card.metrics:
        y = _metrics(canvas, y + 12, card.metrics)
    if card.note:
        y += 10
        lines = canvas.wrap(card.note, _CONTENT, 14)
        y += canvas.paragraph(_PAD, y, lines, 14, 18, fill="muted")
    if card.hint and card.screen == "number_progress":
        y += 12
        lines = canvas.wrap(card.hint, _CONTENT - 22, 14)
        height = len(lines) * 18 + 20
        canvas.rect((_PAD, y, _RIGHT, y + height), "warn_bg", 9)
        canvas.paragraph(_PAD + 11, y + 10, lines, 14, 18, fill="warn")
        y += height
    if card.screen == "training_result" and card.practice:
        y = _result_practice(canvas, y + 12, card.practice)
    tile_surface = "sage"
    for section in card.sections:
        if not section.entries:
            continue
        y += 12
        if section.layout == "practical":
            y = _practical(canvas, y, section)
            continue
        if section.title:
            lines = canvas.wrap(section.title, _CONTENT, 15, True)
            y += canvas.paragraph(_PAD, y, lines, 15, 19, bold=True) + 5
        if section.layout == "tiles":
            y = _tiles(canvas, y, section.entries, card.screen, tile_surface)
            tile_surface = "cool"
        elif section.layout == "outcomes":
            y = _outcomes(canvas, y, section.entries)
        elif section.layout == "list":
            y = _list(canvas, y, section, card.screen)
        else:
            raise CardLayoutError("Visual card section uses an unsupported layout")
    if card.hint and card.screen != "number_progress":
        y += 10
        lines = canvas.wrap(card.hint, _CONTENT, 13)
        y += canvas.paragraph(_PAD, y, lines, 13, 17, fill="muted")
    return canvas.png(y)
