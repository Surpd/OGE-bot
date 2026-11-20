"""Compact ungridded Pillow diagrams; independent final-ink audit."""

from __future__ import annotations

from io import BytesIO
from math import atan2, cos, hypot, pi, sin
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageFont

VERSION = "oge15-pillow-1"
VERSION_V2 = "oge15-pillow-2"
SIZE = (720, 520)


def layout(scene: dict[str, Any]) -> dict[str, tuple[float, float]]:
    pts = scene["points"]
    xs = [p[0] for p in pts.values()]
    ys = [p[1] for p in pts.values()]
    scale = min(540 / (max(xs) - min(xs)), 340 / (max(ys) - min(ys)))
    cx = (min(xs) + max(xs)) / 2
    cy = (min(ys) + max(ys)) / 2
    return {n: (360 + (p[0] - cx) * scale, 260 - (p[1] - cy) * scale) for n, p in pts.items()}


def marks(
    scene: dict[str, Any], coords: dict[str, tuple[float, float]]
) -> list[list[tuple[float, float]]]:
    paths = []
    for a, b, c in scene["right"]:
        origin = coords[b]
        u = (coords[a][0] - origin[0], coords[a][1] - origin[1])
        v = (coords[c][0] - origin[0], coords[c][1] - origin[1])
        u = (u[0] / hypot(*u) * 15, u[1] / hypot(*u) * 15)
        v = (v[0] / hypot(*v) * 15, v[1] / hypot(*v) * 15)
        paths.append(
            [
                (origin[0] + u[0], origin[1] + u[1]),
                (origin[0] + u[0] + v[0], origin[1] + u[1] + v[1]),
                (origin[0] + v[0], origin[1] + v[1]),
            ]
        )
    for group_index, group in enumerate(scene["equal"]):
        for a, b in group:
            x, y = coords[a]
            dx, dy = coords[b][0] - x, coords[b][1] - y
            length = hypot(dx, dy)
            for shift in range(group_index + 1):
                offset = (shift - group_index / 2) * 7
                mx, my = x + dx / 2 + dx / length * offset, y + dy / 2 + dy / length * offset
                paths.append(
                    [
                        (mx - dy / length * 7, my + dx / length * 7),
                        (mx + dy / length * 7, my - dx / length * 7),
                    ]
                )
    for a, b, k, c in scene["bisectors"]:
        x, y = coords[b]
        for start, end in ((a, k), (k, c)):
            t1 = atan2(coords[start][1] - y, coords[start][0] - x)
            t2 = atan2(coords[end][1] - y, coords[end][0] - x)
            delta = (t2 - t1 + pi) % (2 * pi) - pi
            paths.append(
                [
                    (x + 30 * cos(t1 + delta * i / 20), y + 30 * sin(t1 + delta * i / 20))
                    for i in range(21)
                ]
            )
    for start, vertex, end in scene.get("angle_arcs", []):
        x, y = coords[vertex]
        t1 = atan2(coords[start][1] - y, coords[start][0] - x)
        t2 = atan2(coords[end][1] - y, coords[end][0] - x)
        delta = (t2 - t1 + pi) % (2 * pi) - pi
        paths.append(
            [
                (x + 26 * cos(t1 + delta * i / 20), y + 26 * sin(t1 + delta * i / 20))
                for i in range(21)
            ]
        )
    return paths


def label_boxes(
    scene: dict[str, Any], coords: dict[str, tuple[float, float]], version: str = VERSION
) -> dict[str, tuple[float, float]]:
    cx = sum(coords[n][0] for n in "ABC") / 3
    cy = sum(coords[n][1] for n in "ABC") / 3
    result = {}
    for name in scene["labels"]:
        x, y = coords[name]
        # The extension at C and the altitude foot H both lie on the baseline.
        if version == VERSION_V2 and name == ("C" if "X" in coords else "H"):
            result[name] = (x, y + 32)
            continue
        dx, dy = x - cx, y - cy
        length = max(1, hypot(dx, dy))
        result[name] = (x + dx / length * 30, y + dy / length * 30)
    return result


def render(scene: dict[str, Any], version: str = VERSION) -> bytes:
    scale = 2
    image = Image.new("RGB", (SIZE[0] * scale, SIZE[1] * scale), "white")
    draw = ImageDraw.Draw(image)
    coords = layout(scene)

    def path(points: list[tuple[float, float]], color: str, width: int) -> None:
        draw.line(
            [(round(x * scale), round(y * scale)) for x, y in points],
            fill=color,
            width=width * scale,
            joint="curve",
        )

    for a, b in scene["segments"]:
        path(
            [coords[a], coords[b]],
            "#202020" if (a, b) in [("A", "B"), ("B", "C"), ("C", "A"), ("C", "X")] else "#d57716",
            3,
        )
    for points in marks(scene, coords):
        path(points, "#202020", 2)
    font = ImageFont.truetype("DejaVuSans.ttf", 32 * scale)
    for name, (x, y) in label_boxes(scene, coords, version).items():
        draw.text(
            (round(x * scale), round(y * scale)), name, font=font, fill="#202020", anchor="mm"
        )
    if scene.get("exterior_label"):
        x, y = coords["C"]
        draw.text(
            (round((x + 45) * scale), round((y - 27) * scale)),
            scene["exterior_label"],
            font=font,
            fill="#202020",
            anchor="mm",
        )
    image = image.resize(SIZE, Image.Resampling.LANCZOS)
    out = BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def audit(
    png: bytes, scene: dict[str, Any], *, expected_png: bytes | None = None, version: str = VERSION
) -> None:
    image = Image.open(BytesIO(png))
    image.load()
    if image.format != "PNG" or image.size != SIZE or image.mode != "RGB":
        raise ValueError("Invalid triangle PNG contract")
    coords = layout(scene)
    for width in (360, 390, 430):
        ratio = width / SIZE[0]
        small = image.resize((width, round(SIZE[1] * ratio)), Image.Resampling.LANCZOS)
        for a, b in scene["segments"]:
            for f in (0.15, 0.35, 0.5, 0.65, 0.85):
                px = round((coords[a][0] + f * (coords[b][0] - coords[a][0])) * ratio)
                py = round((coords[a][1] + f * (coords[b][1] - coords[a][1])) * ratio)
                if min(small.convert("L").crop((px - 2, py - 2, px + 3, py + 3)).tobytes()) > 220:
                    raise ValueError("Missing triangle line at mobile width")
    gray = image.convert("L")
    for x, y in label_boxes(scene, coords, version).values():
        box = gray.crop((round(x - 18), round(y - 23), round(x + 18), round(y + 23)))
        if sum(value < 100 for value in list(box.tobytes())) < 30:
            raise ValueError("Missing vertex label")
    for path in marks(scene, coords):
        x, y = path[len(path) // 2]
        if min(gray.crop((round(x) - 2, round(y) - 2, round(x) + 3, round(y) + 3)).tobytes()) > 200:
            raise ValueError("Missing geometry mark")
    if scene.get("exterior_label"):
        x, y = coords["C"]
        digits = gray.crop((round(x + 10), round(y - 48), round(x + 100), round(y - 7)))
        if sum(value < 100 for value in digits.tobytes()) < 60:
            raise ValueError("Missing exterior-angle value")
    # Independently allow only the geometric edges, marks and bounded glyph regions.
    mask = Image.new("L", SIZE, 0)
    draw = ImageDraw.Draw(mask)
    for a, b in scene["segments"]:
        draw.line([coords[a], coords[b]], fill=255, width=11)
        for x, y in (coords[a], coords[b]):
            draw.ellipse((x - 6, y - 6, x + 6, y + 6), fill=255)
    for path in marks(scene, coords):
        draw.line(path, fill=255, width=10)
        for x, y in path:
            draw.ellipse((x - 5, y - 5, x + 5, y + 5), fill=255)
    for x, y in label_boxes(scene, coords, version).values():
        draw.rectangle((x - 18, y - 23, x + 18, y + 23), fill=255)
    if scene.get("exterior_label"):
        x, y = coords["C"]
        draw.rectangle((x + 5, y - 52, x + 100, y), fill=255)
    ink = image.convert("L").point(lambda v: 255 if v < 225 else 0)
    if ImageChops.subtract(ink, mask).getbbox():
        raise ValueError("Unexpected triangle construction or label")
    if (
        image.tobytes()
        != Image.open(
            BytesIO(expected_png if expected_png is not None else render(scene, version))
        ).tobytes()
    ):
        raise ValueError("Corrupted triangle raster")
