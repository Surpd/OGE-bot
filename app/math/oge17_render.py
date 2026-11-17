"""Plain Pillow quadrilateral diagrams and independent final-pixel admissible masks."""

from __future__ import annotations

import math
from functools import lru_cache
from io import BytesIO
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 720, 540
INK = (30, 30, 30)
AUXILIARY = (210, 117, 20)


@lru_cache(maxsize=1)
def font() -> ImageFont.FreeTypeFont:
    return ImageFont.truetype("DejaVuSans.ttf", 28)


def layout(d: dict[str, Any]) -> dict[str, tuple[float, float]]:
    p = d["points"]
    xs = [v[0] for v in p.values()]
    ys = [v[1] for v in p.values()]
    scale = min(510 / (max(xs) - min(xs)), 330 / (max(ys) - min(ys)))
    cx = (min(xs) + max(xs)) / 2
    cy = (min(ys) + max(ys)) / 2
    return {k: (360 + (v[0] - cx) * scale, 270 - (v[1] - cy) * scale) for k, v in p.items()}


def distance(p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy)))
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)


def label_plan(d: dict[str, Any], pts: dict[str, tuple[float, float]]) -> list[dict[str, Any]]:
    """Place labels outside all strokes; reject scenes without an admissible placement."""
    lines = [(pts[s[0]], pts[s[1]]) for s in d["segments"]]
    center = (sum(pts[k][0] for k in "ABCD") / 4, sum(pts[k][1] for k in "ABCD") / 4)
    requests: list[tuple[str, tuple[float, float], tuple[float, float]]] = []
    for k, point in sorted(pts.items()):
        vx, vy = point[0] - center[0], point[1] - center[1]
        norm = math.hypot(vx, vy)
        direction = (vx / norm, vy / norm) if norm > 1e-6 else (0.0, -1.0)
        requests.append((k, point, direction))
    for segment, label in sorted(d["length_labels"].items()):
        a, b = (pts[k] for k in segment)
        dx, dy = b[0] - a[0], b[1] - a[1]
        norm = math.hypot(dx, dy)
        requests.append((label, ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2), (-dy / norm, dx / norm)))
    result: list[dict[str, Any]] = []
    for text, origin, preferred in requests:
        bbox = font().getbbox(text)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        found = False
        # Prefer outward placement, then test other directions for intersection points.
        angles = [math.atan2(preferred[1], preferred[0])] + [i * math.pi / 8 for i in range(16)]
        for radius in (29, 39, 50, 62):
            for theta in angles:
                x = origin[0] + radius * math.cos(theta)
                y = origin[1] + radius * math.sin(theta)
                box = (x - w / 2 - 3, y - h / 2 - 3, x + w / 2 + 3, y + h / 2 + 3)
                if not (8 < box[0] < box[2] < 712 and 8 < box[1] < box[3] < 532):
                    continue
                samples = [
                    (box[0] + (box[2] - box[0]) * i / 4, box[1] + (box[3] - box[1]) * j / 4)
                    for i in range(5)
                    for j in range(5)
                ]
                if any(distance(q, a, b) < 7 for q in samples for a, b in lines):
                    continue
                if any(
                    not (
                        box[2] + 5 < r["box"][0]
                        or r["box"][2] + 5 < box[0]
                        or box[3] + 5 < r["box"][1]
                        or r["box"][3] + 5 < box[1]
                    )
                    for r in result
                ):
                    continue
                result.append(
                    {"text": text, "box": box, "origin": (x - w / 2 - bbox[0], y - h / 2 - bbox[1])}
                )
                found = True
                break
            if found:
                break
        if not found:
            raise ValueError("No collision-free label placement")
    return result


def right_paths(
    d: dict[str, Any], pts: dict[str, tuple[float, float]]
) -> list[list[tuple[float, float]]]:
    result = []
    for aa, hh, bb in d["right_angles"]:
        a, h, b = (pts[k] for k in (aa, hh, bb))
        na = math.dist(a, h)
        nb = math.dist(b, h)
        u = ((a[0] - h[0]) * 15 / na, (a[1] - h[1]) * 15 / na)
        v = ((b[0] - h[0]) * 15 / nb, (b[1] - h[1]) * 15 / nb)
        result.append(
            [
                (h[0] + u[0], h[1] + u[1]),
                (h[0] + u[0] + v[0], h[1] + u[1] + v[1]),
                (h[0] + v[0], h[1] + v[1]),
            ]
        )
    return result


def render(d: dict[str, Any]) -> bytes:
    pts = layout(d)
    image = Image.new("RGB", (WIDTH, HEIGHT), "white")
    draw = ImageDraw.Draw(image)
    for s in d["segments"]:
        draw.line(
            (pts[s[0]], pts[s[1]]),
            fill=INK if s in ("AB", "BC", "CD", "DA") else AUXILIARY,
            width=2 if s in ("AB", "BC", "CD", "DA") else 3,
        )
    for path in right_paths(d, pts):
        draw.line(path, fill=AUXILIARY, width=2)
    for label in label_plan(d, pts):
        draw.text(label["origin"], label["text"], font=font(), fill=INK)
    out = BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def audit_png(png: bytes, d: dict[str, Any]) -> None:
    """Decode final pixels, sample strokes and reject ink outside an analytic mask.

    Does not call render or compare with a second rendering. The pixel transform is
    independently derived here. Text boxes must contain ink and avoid all drawn lines.
    Deterministic snapshot replay additionally verifies exact glyphs and image bytes.
    """
    try:
        im = Image.open(BytesIO(png))
        if im.format != "PNG" or im.size != (WIDTH, HEIGHT) or im.mode != "RGB":
            raise ValueError("Invalid PNG format/dimensions")
        im.load()
    except (OSError, Image.DecompressionBombError) as exc:
        raise ValueError("Unreadable PNG") from exc
    values = list(d["points"].values())
    lo = [min(v[i] for v in values) for i in (0, 1)]
    hi = [max(v[i] for v in values) for i in (0, 1)]
    ratio = min((WIDTH - 210) / (hi[0] - lo[0]), (HEIGHT - 210) / (hi[1] - lo[1]))
    pts = {
        k: (
            WIDTH / 2 + (v[0] - (lo[0] + hi[0]) / 2) * ratio,
            HEIGHT / 2 - (v[1] - (lo[1] + hi[1]) / 2) * ratio,
        )
        for k, v in d["points"].items()
    }
    labels = label_plan(d, pts)
    paths = right_paths(d, pts)
    edges = [(pts[s[0]], pts[s[1]]) for s in d["segments"]]
    edges += [(path[i], path[i + 1]) for path in paths for i in range(2)]
    for width in (360, 390, 430):
        r = width / WIDTH
        height = round(HEIGHT * r)
        small = im.resize((width, height), Image.Resampling.LANCZOS)
        pixels = np.asarray(small)
        ink = np.min(pixels, axis=2) < 160
        yy, xx = np.indices((height, width))
        allowed = np.zeros((height, width), dtype=bool)
        for a, b in edges:
            ax, ay = a[0] * r, a[1] * r
            bx, by = b[0] * r, b[1] * r
            dx, dy = bx - ax, by - ay
            t = np.clip(((xx - ax) * dx + (yy - ay) * dy) / (dx * dx + dy * dy), 0, 1)
            dist2 = (xx - ax - t * dx) ** 2 + (yy - ay - t * dy) ** 2
            allowed |= dist2 <= 3.5**2
            # Explicit coverage of every line, not merely absence of stray pixels.
            for t0 in (0.12, 0.25, 0.4, 0.6, 0.75, 0.88):
                x = round(ax + t0 * dx)
                y = round(ay + t0 * dy)
                if not ink[max(0, y - 2) : y + 3, max(0, x - 2) : x + 3].any():
                    raise ValueError("Missing or misplaced diagram stroke")
        for label in labels:
            left, t0, rr, bb = label["box"]
            left = max(0, int(left * r) - 1)
            rr = min(width, math.ceil(rr * r) + 1)
            t0 = max(0, int(t0 * r) - 1)
            bb = min(height, math.ceil(bb * r) + 1)
            allowed[t0:bb, left:rr] = True
            if int(ink[t0:bb, left:rr].sum()) < 6:
                raise ValueError("Missing diagram label")
        if np.any(ink & ~allowed):
            raise ValueError("Unexpected ink outside independent permissible mask")
