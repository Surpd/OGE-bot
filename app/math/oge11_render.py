"""Fast deterministic Pillow renderer and pixel-level graph audit for OGE 11."""

from __future__ import annotations

import hashlib
import io
import json
from fractions import Fraction
from typing import TYPE_CHECKING, Any

from PIL import Image, ImageDraw, PngImagePlugin

if TYPE_CHECKING:
    from app.math.oge11 import Graph

WIDTH = 700
HEIGHT = 1530
ROW_HEIGHT = 510
PLOT = (155, 72, 545, 462)
CURVE = (34, 83, 180)
BACKGROUND = (255, 255, 255)


_GLYPHS = {
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11110", "00001", "00001", "01110", "00001", "00001", "11110"),
    "А": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "Б": ("11111", "10000", "10000", "11110", "10001", "10001", "11110"),
    "В": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
}


def _bitmap_text(draw: ImageDraw.ImageDraw, text: str, x: int, y: int, scale: int) -> None:
    for char_index, char in enumerate(text):
        glyph = _GLYPHS[char]
        for row, pattern in enumerate(glyph):
            for column, pixel in enumerate(pattern):
                if pixel == "1":
                    x0 = x + char_index * 6 * scale + column * scale
                    y0 = y + row * scale
                    draw.rectangle((x0, y0, x0 + scale - 1, y0 + scale - 1), fill=(20, 20, 20))


def _pixels(
    x: float, y: float, viewport: tuple[Fraction, Fraction, Fraction, Fraction], panel: int
) -> tuple[int, int]:
    xmin, xmax, ymin, ymax = (float(value) for value in viewport)
    left, top, right, bottom = PLOT
    px = left + round((x - xmin) * (right - left) / (xmax - xmin))
    py = panel * ROW_HEIGHT + top + round((ymax - y) * (bottom - top) / (ymax - ymin))
    return px, py


def _draw_graph(
    draw: ImageDraw.ImageDraw,
    graph: Graph,
    panel: int,
    viewport: tuple[Fraction, Fraction, Fraction, Fraction],
) -> None:
    xmin, xmax, ymin, ymax = (float(value) for value in viewport)
    left, top, right, bottom = PLOT
    origin = _pixels(0, 0, viewport, panel)
    draw.line((left, origin[1], right, origin[1]), fill=(70, 70, 70), width=2)
    draw.line(
        (origin[0], panel * ROW_HEIGHT + top, origin[0], panel * ROW_HEIGHT + bottom),
        fill=(70, 70, 70),
        width=2,
    )
    # Direction arrows and small origin/unit labels make the shared scale explicit.
    draw.polygon(
        ((right, origin[1]), (right - 10, origin[1] - 5), (right - 10, origin[1] + 5)),
        fill=(70, 70, 70),
    )
    draw.polygon(
        (
            (origin[0], panel * ROW_HEIGHT + top),
            (origin[0] - 5, panel * ROW_HEIGHT + top + 10),
            (origin[0] + 5, panel * ROW_HEIGHT + top + 10),
        ),
        fill=(70, 70, 70),
    )
    for tick in range(-4, 5):
        tx, ty = _pixels(tick, 0, viewport, panel)
        draw.line((tx, origin[1] - 4, tx, origin[1] + 4), fill=(80, 80, 80), width=1)
        tx, ty = _pixels(0, tick, viewport, panel)
        draw.line((origin[0] - 4, ty, origin[0] + 4, ty), fill=(80, 80, 80), width=1)
    zero_x, zero_y = _pixels(0, 0, viewport, panel)
    one_x, _ = _pixels(1, 0, viewport, panel)
    _, one_y = _pixels(0, 1, viewport, panel)
    _bitmap_text(draw, "0", zero_x + 5, zero_y + 4, 2)
    _bitmap_text(draw, "1", one_x - 4, zero_y + 4, 2)
    _bitmap_text(draw, "1", zero_x + 5, one_y - 15, 2)
    if graph.kind == "inverse":
        # Plot both disconnected domains independently; no segment crosses x=0.
        for start, end in ((xmin, -0.08), (0.08, xmax)):
            _sample_curve(draw, graph, panel, viewport, start, end)
    else:
        _sample_curve(draw, graph, panel, viewport, xmin, xmax)


def _sample_curve(
    draw: ImageDraw.ImageDraw,
    graph: Graph,
    panel: int,
    viewport: tuple[Fraction, Fraction, Fraction, Fraction],
    start: float,
    end: float,
) -> None:
    ymin, ymax = float(viewport[2]), float(viewport[3])
    points: list[tuple[int, int]] = []
    steps = 220
    for index in range(steps + 1):
        x = start + (end - start) * index / steps
        try:
            y = float(graph.value(Fraction(x).limit_denominator(10_000)))
        except (ValueError, ZeroDivisionError):
            if len(points) > 1:
                draw.line(points, fill=CURVE, width=4)
            points = []
            continue
        if y < ymin - 0.25 or y > ymax + 0.25:
            if len(points) > 1:
                draw.line(points, fill=CURVE, width=4)
            points = []
            continue
        points.append(_pixels(x, y, viewport, panel))
    if len(points) > 1:
        draw.line(points, fill=CURVE, width=4)


def render_graphs(
    graphs: tuple[Graph, Graph, Graph],
    graph_order: tuple[int, int, int],
    family_id: str,
    renderer_version: str,
    viewport: tuple[Fraction, Fraction, Fraction, Fraction],
) -> tuple[bytes, dict[str, Any]]:
    image = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(image)
    for panel, graph_index in enumerate(graph_order):
        label = ("А", "Б", "В")[panel] if family_id == "OGE11-F02" else str(panel + 1)
        _bitmap_text(draw, label, 24, panel * ROW_HEIGHT + 18, 4)
        _draw_graph(draw, graphs[graph_index], panel, viewport)
    semantics = {
        "family_id": family_id,
        "renderer_version": renderer_version,
        "graph_order": list(graph_order),
        "graphs": [graph.as_json() for graph in graphs],
        "viewport": [str(value) for value in viewport],
        "plot_box": list(PLOT),
        "curve_rgb": list(CURVE),
    }
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("oge11.semantics", json.dumps(semantics, sort_keys=True))
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=False, pnginfo=metadata)
    payload = output.getvalue()
    return payload, {"sha256": hashlib.sha256(payload).hexdigest(), "size": image.size}


def audit_png(
    png_bytes: bytes,
    graphs: tuple[Graph, Graph, Graph],
    graph_order: tuple[int, int, int],
    viewport: tuple[Fraction, Fraction, Fraction, Fraction],
    family_id: str,
) -> None:
    image = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    if image.size != (WIDTH, HEIGHT):
        raise ValueError("unexpected PNG dimensions")
    pixels = image.load()
    if pixels is None:
        raise ValueError("PNG pixel data is unavailable")
    curve_pixels = 0
    for panel, graph_index in enumerate(graph_order):
        label = ("А", "Б", "В")[panel] if family_id == "OGE11-F02" else str(panel + 1)
        scale = 4
        for row, pattern in enumerate(_GLYPHS[label]):
            for column, expected in enumerate(pattern):
                for dy in range(scale):
                    for dx in range(scale):
                        actual = pixels[
                            24 + column * scale + dx, panel * ROW_HEIGHT + 18 + row * scale + dy
                        ]
                        if (actual == (20, 20, 20)) != (expected == "1"):
                            raise ValueError("graph panel label pixels do not match order")
        graph = graphs[graph_index]
        probes = (Fraction(-2), Fraction(-1), Fraction(1), Fraction(2))
        visible = 0
        for x in probes:
            try:
                y = graph.value(x)
            except ZeroDivisionError:
                continue
            fx, fy = _pixels(float(x), float(y), viewport, panel)
            if not (0 <= fx < image.width and 0 <= fy < image.height):
                continue
            if not (
                PLOT[0] <= fx <= PLOT[2]
                and panel * ROW_HEIGHT + PLOT[1] <= fy <= panel * ROW_HEIGHT + PLOT[3]
            ):
                continue
            if _has_curve_near(pixels, fx, fy, image.width, image.height):
                visible += 1
        if visible < 2:
            raise ValueError("mathematical landmark is missing from raster")
        if graph.kind == "inverse":
            left_has_curve = any(
                _has_curve_near(
                    pixels,
                    *_pixels(float(x), float(graph.value(x)), viewport, panel),
                    image.width,
                    image.height,
                )
                for x in (Fraction(-2), Fraction(-1))
            )
            right_has_curve = any(
                _has_curve_near(
                    pixels,
                    *_pixels(float(x), float(graph.value(x)), viewport, panel),
                    image.width,
                    image.height,
                )
                for x in (Fraction(1), Fraction(2))
            )
            if not left_has_curve or not right_has_curve:
                raise ValueError("inverse branch missing from raster")
        curve_pixels += visible
    if curve_pixels < 6:
        raise ValueError("insufficient graph landmarks")


def _has_curve_near(pixels: Any, x: int, y: int, width: int, height: int) -> bool:
    for px in range(max(0, x - 5), min(width, x + 6)):
        for py in range(max(0, y - 5), min(height, y + 6)):
            red, green, blue = pixels[px, py]
            if blue > red + 30 and blue > green + 20:
                return True
    return False
