"""Bounded local Mathtext + Pillow fallback; no TeX executable or network."""

import io
import threading
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

from app.bot.explicit_math import block_parts, flatten_math_lines, local_tex, plain_tex
from app.bot.math_fragments import MathFragment, System
from app.bot.math_layout import action_prefix, layout_text
from app.bot.math_notation import Span, math_spans, parse_formula

_RENDER_LOCK = threading.Lock()
_WIDTH = 1200
_PADDING = 48
_FONT_SIZE = 36


@lru_cache(maxsize=256)
def _formula(latex: str, size: int = 20) -> Image.Image:
    from matplotlib.font_manager import FontProperties
    from matplotlib.mathtext import math_to_image

    output = io.BytesIO()
    math_to_image(
        "$" + latex + "$",
        output,
        prop=FontProperties(size=size),
        dpi=160,
        format="png",
        color="#17212b",
    )
    image = Image.open(output).convert("RGBA")
    return image


@lru_cache(maxsize=128)
def _explicit_formula(latex: str) -> Image.Image:
    cases = block_parts(latex)
    if cases is None:
        return _formula(local_tex(latex), 24)
    from matplotlib import get_data_path

    left, rows, right, with_brace = cases
    cells = [
        [_formula(local_tex(cell), 24) if cell else Image.new("RGBA", (1, 1)) for cell in row]
        for row in rows
    ]
    columns = max(map(len, cells))
    widths = [
        max((row[index].width for row in cells if index < len(row)), default=0)
        for index in range(columns)
    ]
    heights = [max(cell.height for cell in row) + 12 for row in cells]
    prefix = _formula(local_tex(left), 24) if left else None
    suffix = _formula(local_tex(right), 24) if right else None
    start = prefix.width + 10 if prefix else 0
    indent = 32 if with_brace else 0
    body_width = sum(widths) + 28 * (columns - 1)
    height = sum(heights)
    image = Image.new(
        "RGBA",
        (start + indent + body_width + (suffix.width + 8 if suffix else 0), height),
        (255, 255, 255, 255),
    )
    if prefix:
        image.paste(prefix, (0, (height - prefix.height) // 2))
    if suffix:
        y_suffix = (
            height - suffix.height - 4
            if right in (".", ",", ";", ":")
            else ((height - suffix.height) // 2)
        )
        image.paste(suffix, (start + indent + 8 + body_width, y_suffix))
    if with_brace:
        brace = Image.new("RGBA", (height, height * 2))
        font = ImageFont.truetype(get_data_path() + "/fonts/ttf/DejaVuSans.ttf", height)
        ImageDraw.Draw(brace).text((0, 0), "{", font=font, fill="#17212b")
        bounds = brace.getbbox()
        if bounds:
            brace = brace.crop(bounds).resize((27, height - 4), Image.Resampling.LANCZOS)
            image.paste(brace, (start, 2), brace)
    y = 0
    for row, row_height in zip(cells, heights, strict=True):
        x = start + indent
        for index, cell in enumerate(row):
            image.paste(cell, (x, y + (row_height - cell.height) // 2))
            x += widths[index] + 28
        y += row_height
    return image


def render_math_image(
    source: str | MathFragment,
    diagram: bytes | None = None,
    system_rows: tuple[str, ...] | None = None,
) -> bytes:
    """One photo carries the same problem and controls, including any diagram.

    Telegram's photo aspect/dimension limits are enforced. Oversize content is
    rejected before upload, never silently clipped. Formula failure is literal.
    A lock protects Matplotlib's process-global font/parser caches in threads.
    """
    with _RENDER_LOCK:
        if isinstance(source, str):
            laid_out = layout_text(flatten_math_lines(source))
            system_range = None
            lines = laid_out.split("\n")
            if system_rows and all(parse_formula(row) is not None for row in system_rows):
                for index in range(len(lines)):
                    if lines[index : index + len(system_rows)] == list(system_rows):
                        system_range = (index, index + len(system_rows))
                        break
            return _render(laid_out, diagram, system_range=system_range)
        if isinstance(source, System):
            # Mathtext does not implement TeX's cases environment. Render the
            # explicitly typed rows directly and draw the system brace locally.
            return _render(
                "\n".join(row.unicode() for row in source.rows),
                diagram,
                explicit_rows=[row.latex() for row in source.rows],
                system=True,
            )
        return _render(source.unicode(), diagram, explicit_rows=[source.latex()])


def _render(
    source: str,
    diagram: bytes | None,
    *,
    explicit_rows: list[str] | None = None,
    system: bool = False,
    system_range: tuple[int, int] | None = None,
) -> bytes:
    from matplotlib import get_data_path

    if len(source) > 8000:
        raise ValueError("Mathematical message exceeds image budget")
    font_root = get_data_path() + "/fonts/ttf/DejaVuSans"
    size = 43 if any(span.explicit for span in math_spans(source)) else _FONT_SIZE
    regular = ImageFont.truetype(font_root + ".ttf", size)
    bold = ImageFont.truetype(font_root + "-Bold.ttf", size)
    measuring = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    rows: list[list[tuple[Image.Image, int]]] = []
    row: list[tuple[Image.Image, int]] = []
    row_width = 0

    def add(span: Span, font: ImageFont.FreeTypeFont) -> None:
        nonlocal row, row_width
        if span.latex is not None:
            try:
                tile = (
                    _explicit_formula(span.latex) if span.explicit else _formula(span.latex)
                ).copy()
            except (ValueError, RecursionError):
                if span.explicit:
                    for word in plain_tex(span.latex).split():
                        add(Span(word + " "), font)
                    return
                tile = text_tile(span.source, font)
        else:
            tile = text_tile(span.source, font)
        available = _WIDTH - 2 * _PADDING
        if tile.width > available:
            if span.latex is not None and (span.explicit or tile.width <= available * 1.6):
                tile.thumbnail((available, tile.height))
            elif len(span.source) > 1:
                # Preserve every source character if one expression cannot fit.
                for char in span.source:
                    add(Span(char), font)
                return
            else:
                raise ValueError("Unrenderable mathematical message")
        if row and row_width + tile.width > available:
            rows.append(row)
            row, row_width = [], 0
        row.append((tile, row_width))
        row_width += tile.width

    def text_tile(text: str, font: ImageFont.FreeTypeFont) -> Image.Image:
        width = max(1, int(measuring.textlength(text, font=font)) + 1)
        image = Image.new("RGBA", (width, size + 14), (255, 255, 255, 0))
        ImageDraw.Draw(image).text((0, 0), text, font=font, fill="#17212b")
        return image

    source_lines = source.split("\n")
    if system:
        system_range = (0, len(source_lines))
    line_row_starts = []
    for line_index, line in enumerate(source_lines):
        line_row_starts.append(len(rows))
        heading = line.startswith(
            ("Задание №", "Подсказка", "Разбор", "Ответ:", "Правильный", "Оценка")
            or (line.startswith("№") and " · " in line)
        )
        font = bold if heading else regular
        prefix = None if heading else action_prefix(line)
        spans = (
            [Span(line, explicit_rows[line_index])]
            if explicit_rows is not None
            else math_spans(line)
        )
        if system_range is not None and system_range[0] <= line_index < system_range[1]:
            add(Span("   "), regular)
        if prefix is not None:
            add(Span(prefix), bold)
            spans = math_spans(line[len(prefix) :])
        for index, span in enumerate(spans):
            if span.latex is not None:
                block = span.explicit and block_parts(span.latex) is not None
                if span.explicit and index + 1 < len(spans):
                    following = spans[index + 1]
                    if following.latex is None and following.source[:1] in (".", ",", ";", ":"):
                        punctuation = following.source[0]
                        span = Span(span.source + punctuation, span.latex + punctuation, True)
                        tail = following.source[1:]
                        spans[index + 1] = Span(tail.lstrip() if block else tail)
                if block and row:
                    rows.append(row)
                    row, row_width = [], 0
                add(span, font)
                if block:
                    rows.append(row)
                    row, row_width = [], 0
            else:
                # Words (and their original spaces) can wrap independently.
                for word_index, word in enumerate(span.source.split(" ")):
                    if word_index:
                        add(Span(" "), font)
                    if word:
                        add(Span(word), font)
        rows.append(row)
        row, row_width = [], 0
    line_row_starts.append(len(rows))
    heights = [max((tile.height for tile, _ in items), default=20) + 14 for items in rows]
    graphic = None
    if diagram is not None:
        graphic = Image.open(io.BytesIO(diagram)).convert("RGB")
        graphic.thumbnail((_WIDTH - 2 * _PADDING, 1600))
    height = sum(heights) + 2 * _PADDING + (graphic.height + 24 if graphic else 0)
    if height > 6000 or height / _WIDTH > 20:
        raise ValueError("Mathematical message exceeds Telegram photo budget")
    canvas = Image.new("RGB", (_WIDTH, height), "white")
    y = _PADDING
    for items, row_height in zip(rows, heights, strict=True):
        for tile, x in items:
            canvas.paste(tile, (_PADDING + x, y + (row_height - 14 - tile.height) // 2), tile)
        y += row_height
    if system_range is not None:
        start_row, end_row = (line_row_starts[index] for index in system_range)
        brace_height = sum(heights[start_row:end_row])
        brace_font = ImageFont.truetype(font_root + ".ttf", brace_height)
        brace = Image.new("RGBA", (brace_height, brace_height * 2), (0, 0, 0, 0))
        ImageDraw.Draw(brace).text((0, 0), "{", font=brace_font, fill="#17212b")
        bounds = brace.getbbox()
        if bounds is not None:
            brace = brace.crop(bounds).resize((30, brace_height))
            canvas.paste(brace, (_PADDING - 8, _PADDING + sum(heights[:start_row])), brace)
    if graphic is not None:
        canvas.paste(graphic, ((_WIDTH - graphic.width) // 2, y + 12))
    output = io.BytesIO()
    canvas.save(output, format="PNG", optimize=True)
    return output.getvalue()
