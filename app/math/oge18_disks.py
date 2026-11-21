"""Two unmarked circles on a unit grid, after FIPI's 2026 demonstration, №18."""

from io import BytesIO
from math import ceil, cos, floor, hypot, pi, sin

from PIL import Image, ImageChops, ImageDraw

Point = tuple[int, int]
FAMILY = "OGE18-C01"
SOURCE = "FIPI-2026-DEMO-18"
URL = "https://doc.fipi.ru/oge/demoversii-specifikacii-kodifikatory/2026/ma_9_2026.zip"


def frame(points: tuple[Point, ...]) -> tuple[Point, Point]:
    bounds = [(x, y, hypot(px - x, py - y)) for (x, y), (px, py) in (points[:2], points[2:])]
    return (
        (floor(min(x - r for x, y, r in bounds)), floor(min(y - r for x, y, r in bounds))),
        (ceil(max(x + r for x, y, r in bounds)), ceil(max(y + r for x, y, r in bounds))),
    )


def render(points: tuple[Point, ...], *, construction: bool = False) -> bytes:
    from app.math.oge18_render import STEP, compact_layout

    width, height, vertices = compact_layout((*points, *frame(points)))
    scale = 2
    tile = STEP * scale
    image = Image.new("RGB", (width * scale, height * scale), "white")
    draw = ImageDraw.Draw(image)
    origin_x, origin_y = vertices[0]
    for x in range(origin_x * scale % tile, image.width, tile):
        draw.line((x, 0, x, image.height), fill="#bdbdbd", width=2)
    for y in range(origin_y * scale % tile, image.height, tile):
        draw.line((0, y, image.width, y), fill="#bdbdbd", width=2)
    for (x, y), (u, v) in (vertices[:2], vertices[2:4]):
        r = hypot(u - x, v - y)
        draw.ellipse(
            tuple(round(t * scale) for t in (x - r, y - r, x + r, y + r)),
            outline="#161616",
            width=5,
        )
        if construction:
            path = [(x, y), (u, v)] if y == v else [(x, y), (u, y), (u, v), (x, y)]
            draw.line([(a * scale, b * scale) for a, b in path], fill="#1950a0", width=5)
    out = BytesIO()
    image.resize((width, height), Image.Resampling.LANCZOS).save(out, "PNG")
    return out.getvalue()


def audit(png: bytes, points: tuple[Point, ...]) -> None:
    from app.math.oge18_render import STEP, compact_layout

    width, height, vertices = compact_layout((*points, *frame(points)))
    with Image.open(BytesIO(png)) as image:
        if image.size != (width, height) or image.mode != "RGB":
            raise ValueError("Invalid circles canvas")
        gray = image.convert("L")
        allowed = Image.new("L", image.size)
        mask = ImageDraw.Draw(allowed)
        for i in (0, 2):
            cx, cy = vertices[i]
            x, y = points[i]
            u, v = points[i + 1]
            radius = STEP * ((u - x) ** 2 + (v - y) ** 2) ** 0.5
            # A mathematical annulus, independent of the curve rasterizer.
            outer, inner = radius + 3, radius - 4
            mask.ellipse((cx - outer, cy - outer, cx + outer, cy + outer), fill=255)
            mask.ellipse((cx - inner, cy - inner, cx + inner, cy + inner), fill=0)
            for j in range(48):
                angle = j * pi / 24
                px, py = round(cx + radius * cos(angle)), round(cy + radius * sin(angle))
                if (
                    gray.crop((px - 2, py - 2, px + 3, py + 3))
                    .point(lambda v: 255 if v < 110 else 0)
                    .getbbox()
                    is None
                ):
                    raise ValueError("Circle does not pass through the expected circumference")
        ink = gray.point(lambda value: 255 if value < 110 else 0)
        if ImageChops.subtract(ink, allowed).getbbox():
            raise ValueError("Ink outside the two mathematically permitted circles")
        with Image.open(BytesIO(render(points))) as expected:
            if ImageChops.difference(image, expected).getbbox():
                raise ValueError("Unexpected mark on the circles diagram")
