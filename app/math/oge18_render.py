"""Version 1 grid scenes: no auxiliary constructions or dimension labels."""

from __future__ import annotations

from functools import lru_cache
from io import BytesIO
from typing import cast

from PIL import Image, ImageDraw, ImageFont

VERSION = "oge18-pillow-1"
WIDTH, HEIGHT = 720, 640
STEP, LEFT, BOTTOM = 32, 40, 584
Point = tuple[int, int]


def screen(point: Point) -> tuple[int, int]:
    return LEFT + STEP * point[0], BOTTOM - STEP * point[1]


@lru_cache(maxsize=1)
def _font() -> ImageFont.FreeTypeFont:
    return ImageFont.truetype("DejaVuSans.ttf", 44)


def render(points: tuple[Point, ...], triangle: bool) -> bytes:
    scale = 2
    image = Image.new("RGB", (WIDTH * scale, HEIGHT * scale), "white")
    draw = ImageDraw.Draw(image)
    for x in range(21):
        px = (LEFT + x * STEP) * scale
        draw.line((px, 40 * scale, px, BOTTOM * scale), fill=(195, 195, 195), width=2)
    for y in range(18):
        py = (BOTTOM - y * STEP) * scale
        draw.line((LEFT * scale, py, 680 * scale, py), fill=(195, 195, 195), width=2)
    vertices = [(screen(p)[0] * scale, screen(p)[1] * scale) for p in points]
    draw.line([*vertices, vertices[0]], fill=(22, 38, 60), width=6, joint="curve")
    if triangle:
        for label, (x, y), (dx, dy) in zip(
            "ABC", vertices, ((-20, 10), (-8, -56), (10, 10)), strict=True
        ):
            draw.text((x + dx, y + dy), label, font=_font(), fill=(22, 38, 60))
    image = image.resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)
    out = BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def audit(png: bytes, points: tuple[Point, ...], triangle: bool) -> None:
    """Inspect decoded final pixels, then enforce the versioned complete scene.

    Independent coordinate sampling catches missing/misplaced edges and grid lines;
    full raster equality additionally excludes arbitrary added marks or moved letters.
    """
    try:
        image = Image.open(BytesIO(png))
        if image.size != (720, 640) or image.format != "PNG":
            raise ValueError("Invalid PNG dimensions")
        image.load()
    except (OSError, ValueError) as exc:
        raise ValueError("Invalid PNG") from exc
    if image.format != "PNG" or image.size != (720, 640) or image.mode != "RGB":
        raise ValueError("Invalid image contract")
    for width in (360, 390, 430, 720):
        small = image.resize((width, round(640 * width / 720)), Image.Resampling.LANCZOS)
        ratio = width / 720
        # Grid samples lie outside all admissible polygons and labels.
        samples = [(40 + 32 * x, 40) for x in range(21)]
        samples += [(680, 584 - 32 * y) for y in range(18)]
        for gx, gy in samples:
            px, py = round(gx * ratio), round(gy * ratio)
            box = small.crop((max(0, px - 1), max(0, py - 1), px + 2, py + 2))
            darkest = min(
                sum(cast(tuple[int, ...], box.getpixel((x, y))))
                for x in range(box.width) for y in range(box.height)
            )
            if darkest > 735:
                raise ValueError("Grid line missing or nonuniform")
        for a, b in zip(points, (*points[1:], points[0]), strict=True):
            for k in range(9):
                # Independently map Cartesian coordinates to raster coordinates.
                x = round((40 + 32 * (a[0] + (b[0] - a[0]) * k / 8)) * ratio)
                y = round((584 - 32 * (a[1] + (b[1] - a[1]) * k / 8)) * ratio)
                box = small.crop((x - 2, y - 2, x + 3, y + 3))
                if (
                    min(
                        sum(cast(tuple[int, ...], pixel))
                        for pixel in (
                            box.getpixel((x, y))
                            for x in range(box.width)
                            for y in range(box.height)
                        )
                    )
                    > 450
                ):
                    raise ValueError("Polygon edge missing")
    reference = Image.open(BytesIO(render(points, triangle)))
    if image.tobytes() != reference.tobytes():
        raise ValueError("Unexpected or missing scene pixels")
