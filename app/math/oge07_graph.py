"""Self-contained number-line model, PNG renderer, and raster consistency oracle."""

from __future__ import annotations

import base64
import hashlib
import math
import random
import re
import struct
import zlib
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from fractions import Fraction
from typing import TypedDict, cast
from uuid import NAMESPACE_URL, uuid5

WIDTH = 960
HEIGHT = 260
SPEC_VERSION = "oge07-line-v2"
GENERATOR_VERSION = "1.1.0"
_AXIS_Y = 145
_AXIS_LEFT = 72
_AXIS_RIGHT = WIDTH - 72
_TEXT_SCALE = 4
_WHITE = (255, 255, 255)
_BLACK = (26, 36, 52)
_BLUE = (35, 105, 190)
_GLYPHS: dict[str, tuple[str, ...]] = {
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11110", "00001", "00001", "01110", "00001", "00001", "11110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "10000", "11110", "00001", "00001", "11110"),
    "6": ("01110", "10000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00001", "01110"),
    "-": ("00000", "00000", "00000", "11111", "00000", "00000", "00000"),
    "−": ("00000", "00000", "00000", "11111", "00000", "00000", "00000"),
    ",": ("00000", "00000", "00000", "00000", "00110", "00100", "01000"),
    ".": ("00000", "00000", "00000", "00000", "00000", "00110", "00110"),
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "B": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
    "C": ("01110", "10001", "10000", "10000", "10000", "10001", "01110"),
    "D": ("11110", "10001", "10001", "10001", "10001", "10001", "11110"),
}


class GraphModel(TypedDict):
    axis_min: tuple[int, int]
    axis_max: tuple[int, int]
    ticks: list[dict[str, object]]
    points: list[dict[str, object]]
    options: list[str]
    correct_option_index: int
    reference_ids: list[str]
    render_spec_version: str
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class GraphProblem:
    problem_id: str
    family_id: str
    seed: int
    reference_ids: tuple[str, ...]
    condition: str
    options: tuple[str, str, str, str]
    correct_option_index: int
    graph_model: GraphModel
    png: bytes
    png_sha256: str
    hints: tuple[str, ...]
    solution: tuple[str, ...]

    def to_snapshot(self) -> dict[str, object]:
        return {
            "problem_id": self.problem_id,
            "family_id": self.family_id,
            "seed": self.seed,
            "generator_version": GENERATOR_VERSION,
            "reference_ids": list(self.reference_ids),
            "content_provenance": "generated_analogue",
            "condition": self.condition,
            "options": list(self.options),
            "correct_option_index": self.correct_option_index,
            "correct_answer": str(self.correct_option_index),
            "answer_policy_id": "oge07.single-choice",
            "answer_policy_version": "1",
            "hints": list(self.hints),
            "solution": list(self.solution),
            "graph_model": self.graph_model,
            "graph_png_base64": base64.b64encode(self.png).decode("ascii"),
            "graph_png_sha256": self.png_sha256,
            "fingerprint": hashlib.sha256(
                (self.family_id + self.condition + "|".join(self.options)).encode()
            ).hexdigest(),
        }


def _coord(value: Fraction | dict[str, int] | tuple[int, int] | object) -> Fraction:
    if isinstance(value, Fraction):
        return value
    if isinstance(value, dict):
        return Fraction(int(value["numerator"]), int(value["denominator"]))
    if isinstance(value, tuple | list) and len(value) == 2:
        return Fraction(int(value[0]), int(value[1]))
    raise TypeError("Expected a rational graph coordinate")


def graph_model(
    family_id: str,
    axis_min: Fraction,
    axis_max: Fraction,
    points: list[dict[str, object]],
    options: list[str],
    correct_option_index: int,
    reference_ids: list[str],
) -> GraphModel:
    """Build the persisted, exact semantic graph model before rasterization."""
    if family_id not in {"OGE07-N01", "OGE07-N02", "OGE07-N03", "OGE07-N04", "OGE07-N05"}:
        raise ValueError("Unsupported OGE07 graph family")
    lo, hi = axis_min, axis_max
    if not lo < hi or any(not lo <= _value(p) <= hi for p in points):
        raise ValueError("Point falls outside the visible axis")
    normalized_points: list[dict[str, object]] = []
    for source_point in points:
        point = dict(source_point)
        exact = point["value_exact"]
        if isinstance(exact, Fraction):
            point["value_exact"] = {"numerator": exact.numerator, "denominator": exact.denominator}
        normalized_points.append(point)
    ticks: list[dict[str, object]] = [
        {"value": (v, 1), "label": str(v)} for v in range(math.floor(lo), math.ceil(hi) + 1)
    ]
    return {
        "axis_min": (lo.numerator, lo.denominator),
        "axis_max": (hi.numerator, hi.denominator),
        "ticks": ticks,
        "points": normalized_points,
        "options": options,
        "correct_option_index": correct_option_index,
        "reference_ids": reference_ids,
        "render_spec_version": SPEC_VERSION,
        "width": WIDTH,
        "height": HEIGHT,
    }


def _value(point: dict[str, object]) -> Fraction:
    value = point["value_exact"]
    if isinstance(value, dict) and "sqrt" in value:
        n = int(value["sqrt"])
        root = math.isqrt(n)
        if root * root == n:
            return Fraction(root)
        with localcontext() as context:
            context.prec = 40
            return Fraction(Decimal(n).sqrt())
    return _coord(value)


def _text(pixels: bytearray, x: int, y: int, text: str, color: tuple[int, int, int]) -> None:
    cursor = x
    scale = _TEXT_SCALE
    for char in text:
        glyph = _GLYPHS.get(char)
        if glyph is None:
            cursor += 8
            continue
        for row, bits in enumerate(glyph):
            for col, bit in enumerate(bits):
                if bit == "1":
                    for sy in range(scale):
                        for sx in range(scale):
                            _pixel(pixels, cursor + col * scale + sx, y + row * scale + sy, color)
        cursor += 7 * scale


def _pixel(pixels: bytearray, x: int, y: int, color: tuple[int, int, int]) -> None:
    if 0 <= x < WIDTH and 0 <= y < HEIGHT:
        offset = (y * WIDTH + x) * 3
        pixels[offset : offset + 3] = bytes(color)


def _line(
    pixels: bytearray, x0: int, y0: int, x1: int, y1: int, color: tuple[int, int, int]
) -> None:
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
    error = dx + dy
    while True:
        _pixel(pixels, x0, y0, color)
        if x0 == x1 and y0 == y1:
            break
        twice = 2 * error
        if twice >= dy:
            error += dy
            x0 += sx
        if twice <= dx:
            error += dx
            y0 += sy


def projection(model: GraphModel) -> dict[str, int]:
    lo = Fraction(*model["axis_min"])
    hi = Fraction(*model["axis_max"])
    return {
        str(point["id"]): _project_value(point["value_exact"], lo, hi) for point in model["points"]
    }


def _project_value(value: object, axis_min: Fraction, axis_max: Fraction) -> int:
    span = axis_max - axis_min
    if isinstance(value, dict) and "sqrt" in value:
        with localcontext() as context:
            context.prec = 80
            decimal_coordinate = Decimal(int(value["sqrt"])).sqrt()
            lo = Decimal(axis_min.numerator) / Decimal(axis_min.denominator)
            width = Decimal(span.numerator) / Decimal(span.denominator)
            normalized = (decimal_coordinate - lo) / width
            offset = (normalized * (_AXIS_RIGHT - _AXIS_LEFT)).to_integral_value(
                rounding=ROUND_HALF_EVEN
            )
            return _AXIS_LEFT + int(offset)
    rational_coordinate = _coord(value)
    return _AXIS_LEFT + round((rational_coordinate - axis_min) / span * (_AXIS_RIGHT - _AXIS_LEFT))


def render_png(model: GraphModel) -> tuple[bytes, dict[str, int]]:
    if model["render_spec_version"] != SPEC_VERSION or model["width"] != WIDTH:
        raise ValueError("Unsupported graph rendering specification")
    pixels = bytearray(bytes(_WHITE) * WIDTH * HEIGHT)
    axis_y, left, right = _AXIS_Y, _AXIS_LEFT, _AXIS_RIGHT
    lo = Fraction(*model["axis_min"])
    hi = Fraction(*model["axis_max"])
    for dy in (-1, 0, 1):
        _line(pixels, left, axis_y + dy, right, axis_y + dy, _BLACK)
    for tick in model["ticks"]:
        value = _coord(tick["value"])
        x = left + round((value - lo) / (hi - lo) * (right - left))
        for dx in (-1, 0, 1):
            _line(pixels, x + dx, axis_y - 8, x + dx, axis_y + 8, _BLACK)
        label = str(tick["label"])
        _text(pixels, x - len(label) * 14, axis_y + 20, label, _BLACK)
    positions = projection(model)
    for point in model["points"]:
        x = positions[str(point["id"])]
        for dy in range(-8, 9):
            for dx in range(-8, 9):
                if dx * dx + dy * dy <= 64:
                    _pixel(pixels, x + dx, axis_y - 24 + dy, _BLUE)
        label = str(point["label"])
        _text(pixels, x - len(label) * 14, axis_y - 63, label, _BLACK)
    rows = b"".join(b"\x00" + pixels[y * WIDTH * 3 : (y + 1) * WIDTH * 3] for y in range(HEIGHT))

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return (
            struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        )

    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">2I5B", WIDTH, HEIGHT, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows, 9))
        + chunk(b"IEND", b"")
    )
    return png, positions


def audit_png(model: GraphModel, png: bytes) -> bool:
    """Independently read labels, ticks and plotted point centers from PNG pixels."""
    pixels = _decode_rgb_png(png)
    if pixels is None or model["correct_option_index"] not in range(1, 5):
        return False
    options = model["options"]
    points = model["points"]
    ticks = model["ticks"]
    if len(options) != 4 or len(set(options)) != 4 or not points or not ticks:
        return False
    try:
        axis_min = _coord(model["axis_min"])
        axis_max = _coord(model["axis_max"])
        if not axis_min < axis_max:
            return False
        if any(not isinstance(tick, dict) for tick in ticks):
            return False
        tick_values = [_coord(tick["value"]) for tick in ticks]
        if tick_values != sorted(set(tick_values)) or any(
            value.denominator != 1 for value in tick_values
        ):
            return False
        axis_pixels = [x for x in range(WIDTH) if _raster_pixel(pixels, x, _AXIS_Y) == _BLACK]
        if axis_pixels != list(range(_AXIS_LEFT - 1, _AXIS_RIGHT + 2)):
            return False
        raster_tick_columns = [
            x
            for x in range(_AXIS_LEFT - 1, _AXIS_RIGHT + 2)
            if sum(_raster_pixel(pixels, x, y) == _BLACK for y in range(_AXIS_Y - 8, _AXIS_Y + 9))
            >= 16
        ]
        raster_tick_x: list[int] = []
        if raster_tick_columns:
            tick_start = previous = raster_tick_columns[0]
            for x in raster_tick_columns[1:]:
                if x != previous + 1:
                    raster_tick_x.append((tick_start + previous) // 2)
                    tick_start = x
                previous = x
            raster_tick_x.append((tick_start + previous) // 2)
        expected_tick_x = [
            _AXIS_LEFT
            + round((value - axis_min) / (axis_max - axis_min) * (_AXIS_RIGHT - _AXIS_LEFT))
            for value in tick_values
        ]
        if raster_tick_x != expected_tick_x:
            return False
        if len(raster_tick_x) > 1:
            gaps = [b - a for a, b in zip(raster_tick_x, raster_tick_x[1:], strict=False)]
            value_gaps = [b - a for a, b in zip(tick_values, tick_values[1:], strict=False)]
            if len(set(value_gaps)) != 1 or max(gaps) - min(gaps) > 1:
                return False
        for tick, x in zip(ticks, raster_tick_x, strict=True):
            label = str(tick["label"])
            if label != str(int(_coord(tick["value"]))):
                return False
            if not _raster_text_matches(pixels, label, x - len(label) * 14, _AXIS_Y + 20):
                return False

        point_centers = _blue_centers_on_row(pixels, _AXIS_Y - 24)
        if len(point_centers) != len(points):
            return False
        expected_centers: list[int] = []
        ordered_points = sorted(points, key=lambda point: _value(point))
        if list(points) != ordered_points:
            return False
        if [point.get("sort_order") for point in points] != list(range(len(points))):
            return False
        labels = [str(point["label"]) for point in points]
        if len(set(labels)) != len(labels):
            return False
        for point in points:
            coordinate = _value(point)
            if not axis_min <= coordinate <= axis_max:
                return False
            x = _project_value(point["value_exact"], axis_min, axis_max)
            expected_centers.append(x)
            # Check the point's mathematical position against the adjacent labeled ticks.
            lower = [i for i, tick in enumerate(tick_values) if tick <= coordinate]
            upper = [i for i, tick in enumerate(tick_values) if tick >= coordinate]
            if not lower or not upper:
                return False
            if not raster_tick_x[lower[-1]] <= x <= raster_tick_x[upper[0]]:
                return False
            if not _raster_text_matches(
                pixels, str(point["label"]), x - len(str(point["label"])) * 14, _AXIS_Y - 63
            ):
                return False
            for y in range(_AXIS_Y - 26, _AXIS_Y - 15):
                for dx in range(-8, 9):
                    inside = dx * dx + (y - (_AXIS_Y - 24)) ** 2 <= 64
                    expected = _BLUE if inside else _WHITE
                    if _raster_pixel(pixels, x + dx, y) != expected:
                        return False
        if point_centers != expected_centers:
            return False
        if any(b - a < 20 for a, b in zip(point_centers, point_centers[1:], strict=False)):
            return False
        return all(_AXIS_LEFT <= center <= _AXIS_RIGHT for center in point_centers)
    except (KeyError, TypeError, ValueError, ZeroDivisionError, OverflowError):
        return False


def _decode_rgb_png(png: bytes) -> bytes | None:
    if len(png) < 33 or not png.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    cursor = 8
    compressed = bytearray()
    dimensions: tuple[int, int] | None = None
    while cursor + 12 <= len(png):
        length = struct.unpack(">I", png[cursor : cursor + 4])[0]
        kind = png[cursor + 4 : cursor + 8]
        end = cursor + 12 + length
        if end > len(png):
            return None
        data = png[cursor + 8 : cursor + 8 + length]
        crc = struct.unpack(">I", png[cursor + 8 + length : end])[0]
        if zlib.crc32(kind + data) & 0xFFFFFFFF != crc:
            return None
        if kind == b"IHDR":
            if length != 13:
                return None
            width, height, bit_depth, color_type, compression, filtering, interlace = struct.unpack(
                ">2I5B", data
            )
            if (width, height) != (WIDTH, HEIGHT) or (bit_depth, color_type) != (8, 2):
                return None
            if compression or filtering or interlace:
                return None
            dimensions = (width, height)
        elif kind == b"IDAT":
            compressed.extend(data)
        elif kind == b"IEND":
            if length != 0 or end != len(png):
                return None
            break
        cursor = end
    if dimensions is None:
        return None
    try:
        scanlines = zlib.decompress(compressed)
    except zlib.error:
        return None
    stride = WIDTH * 3
    if len(scanlines) != HEIGHT * (stride + 1):
        return None
    raster = bytearray(HEIGHT * stride)
    for y in range(HEIGHT):
        start = y * (stride + 1)
        if scanlines[start] != 0:
            return None
        raster[y * stride : (y + 1) * stride] = scanlines[start + 1 : start + 1 + stride]
    return bytes(raster)


def _raster_pixel(pixels: bytes, x: int, y: int) -> tuple[int, int, int] | None:
    if not (0 <= x < WIDTH and 0 <= y < HEIGHT):
        return None
    offset = (y * WIDTH + x) * 3
    return pixels[offset], pixels[offset + 1], pixels[offset + 2]


def _raster_text_matches(pixels: bytes, text: str, x: int, y: int) -> bool:
    cursor = x
    for char in text:
        glyph = _GLYPHS.get(char)
        if glyph is None:
            return False
        for row in range(7):
            for col in range(7):
                bit = glyph[row][col] if col < 5 else "0"
                for dy in range(_TEXT_SCALE):
                    for dx in range(_TEXT_SCALE):
                        expected = _BLACK if bit == "1" else _WHITE
                        if (
                            _raster_pixel(
                                pixels, cursor + col * _TEXT_SCALE + dx, y + row * _TEXT_SCALE + dy
                            )
                            != expected
                        ):
                            return False
        cursor += 7 * _TEXT_SCALE
    return True


def _blue_centers_on_row(pixels: bytes, y: int) -> list[int]:
    runs: list[int] = []
    start: int | None = None
    for x in range(_AXIS_LEFT, _AXIS_RIGHT + 1):
        blue = _raster_pixel(pixels, x, y) == _BLUE
        if blue and start is None:
            start = x
        elif not blue and start is not None:
            if x - start != 17:
                return []
            runs.append((start + x - 1) // 2)
            start = None
    if start is not None:
        return []
    return runs


def png_sha256(png: bytes) -> str:
    return hashlib.sha256(png).hexdigest()


GRAPH_SOURCES: dict[str, tuple[str, ...]] = {
    "OGE07-N01": ("384400", "322293", "449733"),
    "OGE07-N02": ("311380", "474133"),
    "OGE07-N03": ("317102", "370464"),
    "OGE07-N04": ("317005",),
    "OGE07-N05": ("311392", "317074"),
}


def _fmt_fraction(value: Fraction) -> str:
    if value.denominator == 1:
        return str(value.numerator)
    return f"{value.numerator}/{value.denominator}"


def _fmt_decimal(value: Fraction) -> str:
    numerator, denominator = abs(value.numerator), value.denominator
    whole, remainder = divmod(numerator, denominator)
    digits = f"{remainder * 100 // denominator:02d}".rstrip("0")
    sign = "−" if value < 0 else ""
    return f"{sign}{whole}" + (f",{digits}" if digits else "")


def generate_graph_problem(family_id: str, seed: int) -> GraphProblem:
    """Create a deterministic point/number task, exact model and original PNG."""
    if family_id not in GRAPH_SOURCES:
        raise ValueError("Unsupported OGE07 graph family")
    rng = random.Random(f"oge07-graph:{family_id}:{seed}:1")
    points: list[dict[str, object]]
    if family_id == "OGE07-N01":
        radicand = rng.choice([v for v in range(12, 181) if math.isqrt(v) ** 2 != v])
        target: Fraction | dict[str, int] = {"sqrt": radicand}
        base = math.isqrt(radicand)
        coords: list[Fraction | dict[str, int]] = [
            Fraction(base) - Fraction(3, 2),
            Fraction(base) - Fraction(3, 4),
            target,
            Fraction(base) + Fraction(5, 4),
        ]
        condition = f"Какой точке на координатной прямой соответствует число √{radicand}?"
        hints = (
            "Сравните подкоренное число с квадратами соседних целых.",
            f"{base}² < {radicand} < {(base + 1) ** 2}.",
        )
        solution = (f"{base} < √{radicand} < {base + 1}; найдите точку в этом промежутке.",)
    elif family_id in {"OGE07-N02", "OGE07-N03"}:
        if family_id == "OGE07-N02":
            den = rng.choice((3, 4, 5, 8, 10, 12))
            target = Fraction(rng.randrange(-8, 21), den)
            shown = _fmt_fraction(target)
        else:
            target = Fraction(rng.randrange(-300, 301), 100)
            shown = _fmt_decimal(target)
        coords = [target - Fraction(3, 2), target - Fraction(3, 4), target, target + Fraction(5, 4)]
        condition = f"Какой точке на координатной прямой соответствует число {shown}?"
        hints = (
            "Сравните число с подписанными делениями шкалы.",
            "Учитывайте знак и точное значение числа.",
        )
        solution = (f"Число {shown} отмечено на прямой точкой с такой координатой.",)
    elif family_id == "OGE07-N04":
        radicand = rng.choice([v for v in range(12, 181) if math.isqrt(v) ** 2 != v])
        target = {"sqrt": radicand}
        base = math.isqrt(radicand)
        coords = [target]
        radicands = [
            radicand,
            max(0, (base - 1) ** 2 + 1),
            (base + 1) ** 2 + 1,
            (base + 2) ** 2 + 3,
        ]
        condition = "Какое число соответствует отмеченной на координатной прямой точке A?"
        hints = ("Определите между какими целыми расположена точка A.", f"{base} < A < {base + 1}.")
        solution = (f"Точка A имеет координату √{radicand}; сопоставьте её с вариантами корней.",)
    else:  # N05
        den = rng.choice((3, 4, 5, 8, 10, 12))
        target = Fraction(rng.randrange(-8, 21), den)
        coords = [target]
        values = [
            target,
            target - Fraction(7, 4),
            target + Fraction(9, 4),
            target + Fraction(13, 4),
        ]
        condition = "Какое число соответствует отмеченной на координатной прямой точке A?"
        hints = (
            "Определите координату точки A по делениям.",
            f"Координата A = {_fmt_fraction(target)}.",
        )
        solution = (f"Отметка A находится в координате {_fmt_fraction(target)}.",)
    if family_id in {"OGE07-N01", "OGE07-N02", "OGE07-N03"}:
        labels = ["A", "B", "C", "D"]
        rng.shuffle(labels)
        points = [
            {"id": label, "label": label, "value_exact": value, "sort_order": i}
            for i, (label, value) in enumerate(zip(labels, coords, strict=True))
        ]
        correct = next(str(point["label"]) for point in points if point["value_exact"] == target)
        values_options = ["A", "B", "C", "D"]
    else:
        points = [{"id": "A", "label": "A", "value_exact": target, "sort_order": 0}]
        if family_id == "OGE07-N04":
            values_options = [f"√{v}" for v in radicands]
            correct = f"√{radicand}"
        else:
            if not isinstance(target, Fraction):
                raise TypeError("Expected a rational target for N05")
            values_options = [_fmt_fraction(v) for v in values]
            correct = _fmt_fraction(target)
    options = values_options[:]
    rng.shuffle(options)
    correct_index = options.index(correct) + 1
    numeric_values = [_value(point) for point in points]
    axis_min = Fraction(math.floor(float(min(numeric_values))) - 2)
    axis_max = Fraction(math.ceil(float(max(numeric_values))) + 2)
    model = graph_model(
        family_id,
        axis_min,
        axis_max,
        points,
        options,
        correct_index,
        list(GRAPH_SOURCES[family_id]),
    )
    png, _ = render_png(model)
    return GraphProblem(
        str(uuid5(NAMESPACE_URL, f"oge07:{family_id}:1:{seed}")),
        family_id,
        seed,
        GRAPH_SOURCES[family_id],
        condition,
        cast(tuple[str, str, str, str], tuple(options)),
        correct_index,
        model,
        png,
        png_sha256(png),
        hints,
        solution,
    )


def audit_graph_problem(problem: GraphProblem) -> bool:
    """Cross-check displayed task, exact graph model, answer and PNG raster."""
    model = problem.graph_model
    if (
        len(problem.options) != 4
        or len(set(problem.options)) != 4
        or problem.correct_option_index not in range(1, 5)
        or model["options"] != list(problem.options)
        or model["correct_option_index"] != problem.correct_option_index
        or model["reference_ids"] != list(problem.reference_ids)
        or png_sha256(problem.png) != problem.png_sha256
        or not audit_png(model, problem.png)
    ):
        return False
    try:
        if problem.family_id == "OGE07-N01":
            match = re.fullmatch(
                r"Какой точке на координатной прямой соответствует число √(\d+)\?",
                problem.condition,
            )
            if not match:
                return False
            target = {"sqrt": int(match[1])}
            truths = [
                any(
                    point["label"] == option and point["value_exact"] == target
                    for point in model["points"]
                )
                for option in problem.options
            ]
        elif problem.family_id in {"OGE07-N02", "OGE07-N03"}:
            match = re.fullmatch(
                r"Какой точке на координатной прямой соответствует число "
                r"(−?-?\d+(?:,\d+)?(?:/\d+)?)\?",
                problem.condition,
            )
            if not match:
                return False
            raw = match[1].replace("−", "-").replace(",", ".")
            target_value = Fraction(raw)
            truths = [
                any(
                    point["label"] == option and _coord(point["value_exact"]) == target_value
                    for point in model["points"]
                )
                for option in problem.options
            ]
        elif problem.family_id == "OGE07-N04":
            if (
                problem.condition
                != "Какое число соответствует отмеченной на координатной прямой точке A?"
            ):
                return False
            if len(model["points"]) != 1 or model["points"][0]["label"] != "A":
                return False
            exact = model["points"][0]["value_exact"]
            if not isinstance(exact, dict) or "sqrt" not in exact:
                return False
            radicand = int(exact["sqrt"])
            if radicand <= 0 or math.isqrt(radicand) ** 2 == radicand:
                return False
            truths = [option == f"√{exact['sqrt']}" for option in problem.options]
        elif problem.family_id == "OGE07-N05":
            if (
                problem.condition
                != "Какое число соответствует отмеченной на координатной прямой точке A?"
            ):
                return False
            if len(model["points"]) != 1 or model["points"][0]["label"] != "A":
                return False
            exact = _coord(model["points"][0]["value_exact"])
            truths = [option == _fmt_fraction(exact) for option in problem.options]
        else:
            return False
        return sum(truths) == 1 and truths[problem.correct_option_index - 1]
    except (ValueError, ZeroDivisionError, KeyError, TypeError):
        return False
