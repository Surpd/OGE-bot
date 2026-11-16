"""Version 1 grid scenes: no auxiliary constructions or dimension labels."""

from __future__ import annotations

from functools import lru_cache
from io import BytesIO
from typing import cast

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

VERSION = "oge18-pillow-1"
VERSION_V2 = "oge18-pillow-2"
VERSION_V3 = "oge18-pillow-3"
WIDTH, HEIGHT = 720, 640
STEP, LEFT, BOTTOM = 32, 40, 584
PADDING_CELLS = 2.5
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
                for x in range(box.width)
                for y in range(box.height)
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
    # Independent ink budget: the renderer cannot validate an added construction
    # merely by reproducing its own mistake in the reference raster.
    allowed = Image.new("L", (720, 640), 0)
    pen = ImageDraw.Draw(allowed)
    vertices = [(40 + 32 * x, 584 - 32 * y) for x, y in points]
    for a, b in zip(vertices, (*vertices[1:], vertices[0]), strict=True):
        pen.line((*a, *b), fill=255, width=7)
    for x, y in vertices:
        pen.ellipse((x - 6, y - 6, x + 6, y + 6), fill=255)
    dark = image.convert("L").point(lambda value: 255 if value < 130 else 0)
    if triangle:
        for index, letter, offset in ((0, "A", (-10, 5)), (1, "B", (-4, -28)), (2, "C", (5, 5))):
            x, y = vertices[index]
            glyph = Image.new("L", (1440, 1280), 0)
            ImageDraw.Draw(glyph).text(
                (2 * (x + offset[0]), 2 * (y + offset[1])),
                letter,
                font=ImageFont.truetype("DejaVuSans.ttf", 44),
                fill=255,
            )
            glyph = glyph.resize((720, 640), Image.Resampling.LANCZOS)
            core = glyph.point(lambda value: 255 if value > 160 else 0)
            overlap = ImageChops.multiply(core, dark)
            if sum(overlap.histogram()[1:]) < sum(core.histogram()[1:]) * 0.8:
                raise ValueError("Missing or misplaced vertex label")
            allowed = ImageChops.lighter(allowed, glyph.filter(ImageFilter.MaxFilter(5)))
    allowed = allowed.point(lambda value: 255 if value else 0)
    if ImageChops.subtract(dark, allowed).getbbox() is not None:
        raise ValueError("Unexpected dark ink: auxiliary line, dimension, or label")
    reference = Image.open(BytesIO(render(points, triangle)))
    if image.tobytes() != reference.tobytes():
        raise ValueError("Unexpected or missing scene pixels")


def render_family(family: str, points: tuple[Point, ...]) -> bytes:
    """Version 2 source-shaped grid diagram; auxiliary constructions stay absent."""
    scale = 2
    image = Image.new("RGB", (WIDTH * scale, HEIGHT * scale), "white")
    draw = ImageDraw.Draw(image)
    for x in range(21):
        px = (LEFT + x * STEP) * scale
        draw.line((px, 40 * scale, px, BOTTOM * scale), fill=(195, 195, 195), width=2)
    for y in range(18):
        py = (BOTTOM - y * STEP) * scale
        draw.line((LEFT * scale, py, 680 * scale, py), fill=(195, 195, 195), width=2)
    screen_points = [(screen(p)[0] * scale, screen(p)[1] * scale) for p in points]
    if family == "OGE18-D05":
        for x, y in screen_points:
            draw.ellipse((x - 7, y - 7, x + 7, y + 7), fill=(239, 136, 35))
    else:
        fill = (245, 151, 36) if family.startswith("OGE18-A") else None
        draw.polygon(screen_points, fill=fill)
        edge = (239, 136, 35) if family == "OGE18-L02" else (22, 22, 22)
        draw.line([*screen_points, screen_points[0]], fill=edge, width=6, joint="curve")
    image = image.resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)
    out = BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def _darkest_pixel_sum(image: Image.Image, box: tuple[int, int, int, int]) -> int:
    crop = image.crop(box)
    return min(
        sum(cast(tuple[int, ...], crop.getpixel((x, y))))
        for x in range(crop.width)
        for y in range(crop.height)
    )


def audit_family(png: bytes, family: str, points: tuple[Point, ...]) -> None:
    """Audit exact versioned pixels plus an independent allowed-object mask."""
    try:
        image = Image.open(BytesIO(png))
        image.load()
    except (OSError, ValueError) as exc:
        raise ValueError("Invalid PNG") from exc
    if image.format != "PNG" or image.size != (WIDTH, HEIGHT) or image.mode != "RGB":
        raise ValueError("Invalid image contract")
    vertices = [screen(point) for point in points]
    for width in (360, 390, 430):
        ratio = width / WIDTH
        small = image.resize((width, round(HEIGHT * ratio)), Image.Resampling.LANCZOS)
        grid_samples = [(40 + 32 * x, 40) for x in range(21)]
        grid_samples += [(680, 584 - 32 * y) for y in range(18)]
        for gx, gy in grid_samples:
            px, py = round(gx * ratio), round(gy * ratio)
            if _darkest_pixel_sum(small, (max(0, px - 1), max(0, py - 1), px + 2, py + 2)) > 735:
                raise ValueError("Grid line missing at mobile width")
        for index, (x, y) in enumerate(vertices):
            if family == "OGE18-D05":
                px, py = round(x * ratio), round(y * ratio)
                if _darkest_pixel_sum(small, (px - 3, py - 3, px + 4, py + 4)) > 700:
                    raise ValueError("Point missing at mobile width")
                continue
            a, b = vertices[index], vertices[(index + 1) % len(vertices)]
            for step in range(9):
                x = round((a[0] + (b[0] - a[0]) * step / 8) * ratio)
                y = round((a[1] + (b[1] - a[1]) * step / 8) * ratio)
                threshold = 700 if family == "OGE18-L02" else 450
                if _darkest_pixel_sum(small, (x - 2, y - 2, x + 3, y + 3)) > threshold:
                    raise ValueError("Polygon edge missing at mobile width")
    boundary = Image.new("L", image.size, 0)
    mask = ImageDraw.Draw(boundary)
    if family == "OGE18-D05":
        for x, y in vertices:
            mask.ellipse((x - 9, y - 9, x + 9, y + 9), fill=255)
        colored = boundary
    else:
        mask.line([*vertices, vertices[0]], fill=255, width=8)
        if family == "OGE18-L02":
            colored = boundary
        else:
            colored = Image.new("L", image.size, 0)
            ImageDraw.Draw(colored).polygon(vertices, fill=255)
    boundary = boundary.filter(ImageFilter.MaxFilter(7))
    colored = colored.filter(ImageFilter.MaxFilter(3))
    # Separate masks allow orange fill inside a polygon but only the perimeter
    # for dark strokes, so an accidental triangle height is rejected.
    dark = image.convert("L").point(lambda value: 255 if value < 90 else 0)
    if ImageChops.subtract(dark, boundary).getbbox() is not None:
        raise ValueError("Unexpected dark construction or label")
    red, green, blue = image.split()
    orange = ImageChops.multiply(
        red.point(lambda value: 255 if value > 210 else 0),
        green.point(lambda value: 255 if 90 < value < 220 else 0),
    )
    orange = ImageChops.multiply(orange, blue.point(lambda value: 255 if value < 100 else 0))
    if ImageChops.subtract(orange, colored).getbbox() is not None:
        raise ValueError("Unexpected colored pixels outside source geometry")
    reference = Image.open(BytesIO(render_family(family, points)))
    if image.tobytes() != reference.tobytes():
        raise ValueError("Unexpected or missing scene pixels")


def compact_layout(points: tuple[Point, ...]) -> tuple[int, int, list[tuple[int, int]]]:
    """Return a square-cell canvas tightly framed with 2.5 cells of padding."""
    min_x = min(point[0] for point in points)
    max_x = max(point[0] for point in points)
    min_y = min(point[1] for point in points)
    max_y = max(point[1] for point in points)
    width = round((max_x - min_x + 2 * PADDING_CELLS) * STEP)
    height = round((max_y - min_y + 2 * PADDING_CELLS) * STEP)
    vertices = [
        (
            round((x - min_x + PADDING_CELLS) * STEP),
            round((max_y - y + PADDING_CELLS) * STEP),
        )
        for x, y in points
    ]
    return width, height, vertices


def render_compact(family: str, points: tuple[Point, ...]) -> bytes:
    """Version 3 scene with a centered tight crop and uniform square cells."""
    width, height, vertices = compact_layout(points)
    scale = 2
    image = Image.new("RGB", (width * scale, height * scale), "white")
    draw = ImageDraw.Draw(image)
    min_x = min(point[0] for point in points)
    max_x = max(point[0] for point in points)
    min_y = min(point[1] for point in points)
    max_y = max(point[1] for point in points)
    for x in range(min_x - 2, max_x + 3):
        px = round((x - min_x + PADDING_CELLS) * STEP) * scale
        draw.line((px, 0, px, height * scale), fill=(195, 195, 195), width=2)
    for y in range(min_y - 2, max_y + 3):
        py = round((max_y - y + PADDING_CELLS) * STEP) * scale
        draw.line((0, py, width * scale, py), fill=(195, 195, 195), width=2)
    high_res_vertices = [(x * scale, y * scale) for x, y in vertices]
    if family == "OGE18-D05":
        for x, y in high_res_vertices:
            draw.ellipse(
                (x - 12 * scale, y - 12 * scale, x + 12 * scale, y + 12 * scale),
                fill=(239, 136, 35),
                outline=(22, 22, 22),
                width=3 * scale,
            )
    else:
        if family.startswith("OGE18-A"):
            draw.polygon(high_res_vertices, fill=(245, 151, 36))
        draw.line(
            [*high_res_vertices, high_res_vertices[0]],
            fill=(22, 22, 22),
            width=6,
            joint="curve",
        )
    if family == "OGE18-M01":
        for label, (x, y), (dx, dy) in zip(
            "ABC", high_res_vertices, ((-20, 10), (-8, -56), (10, 10)), strict=True
        ):
            draw.text((x + dx, y + dy), label, font=_font(), fill=(22, 22, 22))
    image = image.resize((width, height), Image.Resampling.LANCZOS)
    out = BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def audit_compact_family(png: bytes, family: str, points: tuple[Point, ...]) -> None:
    """Verify compact PNG dimensions, grid/edge pixels, marks, and allowed ink."""
    width, height, vertices = compact_layout(points)
    try:
        image = Image.open(BytesIO(png))
        image.load()
    except (OSError, ValueError) as exc:
        raise ValueError("Invalid PNG") from exc
    if image.format != "PNG" or image.size != (width, height) or image.mode != "RGB":
        raise ValueError("Invalid compact PNG dimensions or mode")
    for target_width in (360, 390):
        ratio = target_width / width
        small = image.resize(
            (target_width, round(height * ratio)), Image.Resampling.LANCZOS
        )
        for x, y in vertices:
            if family == "OGE18-D05":
                px, py = round(x * ratio), round(y * ratio)
                if _darkest_pixel_sum(small, (px - 3, py - 3, px + 4, py + 4)) > 650:
                    raise ValueError("Point missing at mobile width")
                continue
            for edge_start, edge_end in zip(vertices, (*vertices[1:], vertices[0]), strict=True):
                # A few independent samples at different fractions catch clipped sides.
                for fraction in (0.0, 0.5, 1.0):
                    px = round((edge_start[0] + (edge_end[0] - edge_start[0]) * fraction) * ratio)
                    py = round((edge_start[1] + (edge_end[1] - edge_start[1]) * fraction) * ratio)
                    if _darkest_pixel_sum(small, (px - 2, py - 2, px + 3, py + 3)) > 520:
                        raise ValueError("Polygon edge missing at mobile width")
        # Grid lines at the unoccupied top and left padding retain equal spacing.
        min_x, max_x = min(p[0] for p in points), max(p[0] for p in points)
        min_y, max_y = min(p[1] for p in points), max(p[1] for p in points)
        top_y = round(STEP * 0.5 * ratio)
        left_x = round(STEP * 0.5 * ratio)
        grid_x = [
            round((x - min_x + PADDING_CELLS) * STEP * ratio)
            for x in range(min_x - 2, max_x + 3)
        ]
        grid_y = [
            round((max_y - y + PADDING_CELLS) * STEP * ratio)
            for y in range(min_y - 2, max_y + 3)
        ]
        for x in grid_x:
            if _darkest_pixel_sum(small, (x - 1, top_y - 1, x + 2, top_y + 2)) > 735:
                raise ValueError("Grid line missing at mobile width")
        for y in grid_y:
            if _darkest_pixel_sum(small, (left_x - 1, y - 1, left_x + 2, y + 2)) > 735:
                raise ValueError("Grid line missing at mobile width")

    boundary = Image.new("L", image.size, 0)
    mask = ImageDraw.Draw(boundary)
    if family == "OGE18-D05":
        for x, y in vertices:
            mask.ellipse((x - 14, y - 14, x + 14, y + 14), fill=255)
        colored = Image.new("L", image.size, 0)
        color_mask = ImageDraw.Draw(colored)
        for x, y in vertices:
            color_mask.ellipse((x - 13, y - 13, x + 13, y + 13), fill=255)
    else:
        mask.line([*vertices, vertices[0]], fill=255, width=8)
        colored = Image.new("L", image.size, 0)
        if family.startswith("OGE18-A"):
            ImageDraw.Draw(colored).polygon(vertices, fill=255)
    if family == "OGE18-M01":
        glyph_mask = Image.new("L", (width * 2, height * 2), 0)
        glyph_draw = ImageDraw.Draw(glyph_mask)
        for label, (x, y), (dx, dy) in zip(
            "ABC", vertices, ((-10, 5), (-4, -28), (5, 5)), strict=True
        ):
            glyph_draw.text(
                ((x + dx) * 2, (y + dy) * 2), label, font=_font(), fill=255
            )
        glyph_mask = glyph_mask.resize((width, height), Image.Resampling.LANCZOS)
        boundary = ImageChops.lighter(boundary, glyph_mask.filter(ImageFilter.MaxFilter(5)))
    boundary = boundary.filter(ImageFilter.MaxFilter(5))
    dark = image.convert("L").point(lambda value: 255 if value < 90 else 0)
    if ImageChops.subtract(dark, boundary).getbbox() is not None:
        raise ValueError("Unexpected dark construction or label")
    red, green, blue = image.split()
    orange = ImageChops.multiply(
        red.point(lambda value: 255 if value > 210 else 0),
        green.point(lambda value: 255 if 90 < value < 220 else 0),
    )
    orange = ImageChops.multiply(orange, blue.point(lambda value: 255 if value < 100 else 0))
    colored = colored.filter(ImageFilter.MaxFilter(5))
    if ImageChops.subtract(orange, colored).getbbox() is not None:
        raise ValueError("Unexpected orange pixels outside source geometry")
    reference = Image.open(BytesIO(render_compact(family, points)))
    if image.tobytes() != reference.tobytes():
        raise ValueError("Unexpected or missing compact scene pixels")
