"""Pillow geometry→layout→PNG; deterministic labels avoid the figure ink."""

from __future__ import annotations

from io import BytesIO
from math import hypot
from typing import Any, cast

from PIL import Image, ImageDraw, ImageFont

from app.math.oge16_model import CircleGeometry, Point

RENDERER_VERSION = "oge16-pillow-2"
SIZE = 720


def render(scene: CircleGeometry) -> tuple[bytes, dict[str, Any]]:
    r = scene.radius
    points = dict(scene.points)
    xs = [-r, r, *(p[0] for p in points.values())]
    ys = [-r, r, *(p[1] for p in points.values())]
    # Equal units on both axes; reserve 76 pixels for labels at every edge.
    scale = (SIZE - 152) / max(max(xs) - min(xs), max(ys) - min(ys))
    ox = SIZE / 2 - scale * (min(xs) + max(xs)) / 2
    oy = SIZE / 2 + scale * (min(ys) + max(ys)) / 2

    def pixel(point: Point) -> Point:
        return ox + scale * point[0], oy - scale * point[1]

    image = Image.new("RGB", (SIZE, SIZE), "white")
    draw = ImageDraw.Draw(image)
    cx, cy = pixel(scene.center)
    draw.ellipse(
        (cx - scale * r, cy - scale * r, cx + scale * r, cy + scale * r), outline="black", width=3
    )
    for first, second in scene.segments:
        draw.line((pixel(points[first]), pixel(points[second])), fill="black", width=3)
    for point in points.values():
        px, py = pixel(point)
        draw.ellipse((px - 3, py - 3, px + 3, py + 3), fill="black")
    shape = image.copy()
    font = ImageFont.truetype("DejaVuSans.ttf", 28)
    boxes: dict[str, list[int]] = {}
    for name, point in scene.points:
        if name in scene.hidden_labels:
            continue
        px, py = pixel(point)
        vx, vy = px - cx, py - cy
        length = hypot(vx, vy)
        unit = (vx / length, vy / length) if length > 1 else (-0.7, 0.7)
        bbox = draw.textbbox((0, 0), name, font=font)
        w, h = int(bbox[2] - bbox[0]), int(bbox[3] - bbox[1])
        directions = (
            unit,
            (0, 1),
            (0, -1),
            (-1, 0),
            (1, 0),
            (-0.707, -0.707),
            (0.707, 0.707),
            (-0.707, 0.707),
            (0.707, -0.707),
        )
        placed = False
        for gap in (30, 42, 56, 70):
            for dx, dy in directions:
                x, y = round(px + gap * dx - w / 2), round(py + gap * dy - h / 2)
                box = [x - 4, y - 4, x + w + 4, y + h + 4]
                if min(box) < 12 or max(box) > SIZE - 12:
                    continue
                if any(
                    not (box[2] < b[0] or b[2] < box[0] or box[3] < b[1] or b[3] < box[1])
                    for b in boxes.values()
                ):
                    continue
                if (
                    cast(
                        tuple[float, float],
                        shape.crop((box[0], box[1], box[2], box[3])).convert("L").getextrema(),
                    )[0]
                    < 240
                ):
                    continue
                draw.text((x - bbox[0], y - bbox[1]), name, fill="black", font=font)
                boxes[name] = box
                placed = True
                break
            if placed:
                break
        if not placed:
            raise ValueError(f"No safe label placement: {name}")
    buf = BytesIO()
    image.save(buf, format="PNG", optimize=False)
    return buf.getvalue(), {
        "scale": scale,
        "origin": [ox, oy],
        "labels": boxes,
        "font_size": 28,
        "stroke_width": 3,
    }
