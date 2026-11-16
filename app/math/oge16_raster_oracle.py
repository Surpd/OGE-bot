"""Stored PNG audit: affine metric, primitive coverage, glyphs, crop and collisions."""

from __future__ import annotations

import base64
import hashlib
import math
from io import BytesIO
from typing import Any, cast

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont


def audit_png(snapshot: dict[str, Any]) -> None:
    from app.math.oge16_oracle import near, require

    f, g = snapshot["figure"], snapshot["geometry"]
    require(f["renderer_version"] == "oge16-pillow-1", "Unknown renderer version")
    require(f["width"] == 720 and f["height"] == 720, "Unexpected dimensions")
    raw = base64.b64decode(f["png_base64"], validate=True)
    require(hashlib.sha256(raw).hexdigest() == f["sha256"], "PNG checksum mismatch")
    with Image.open(BytesIO(raw)) as source:
        require(source.format == "PNG" and source.size == (720, 720), "Invalid PNG")
        source.load()
        require(source.mode == "RGB", "Unexpected PNG mode")
        image = source.copy()
    r, points = g["radius"], g["points"]
    xs = [-r, r, *(p[0] for p in points.values())]
    ys = [-r, r, *(p[1] for p in points.values())]
    expected_scale = 568 / max(max(xs) - min(xs), max(ys) - min(ys))
    layout = f["layout"]
    scale = layout["scale"]
    ox, oy = layout["origin"]
    near(scale, expected_scale)
    near(ox, 360 - expected_scale * (max(xs) + min(xs)) / 2)
    near(oy, 360 + expected_scale * (max(ys) + min(ys)) / 2)
    require(layout["font_size"] == 28 and layout["stroke_width"] == 3, "Unreadable styles")

    def xy(p: Any) -> tuple[float, float]:
        return ox + scale * p[0], oy - scale * p[1]

    expected_ink = Image.new("L", (720, 720), 0)
    ink = ImageDraw.Draw(expected_ink)
    cx, cy = xy(g["center"])
    ink.ellipse(
        (cx - r * scale, cy - r * scale, cx + r * scale, cy + r * scale), outline=255, width=3
    )
    for first, second in g["segments"]:
        ink.line((xy(points[first]), xy(points[second])), fill=255, width=3)
    for point in points.values():
        x, y = xy(point)
        ink.ellipse((x - 3, y - 3, x + 3, y + 3), fill=255)
    gray = image.convert("L")
    # Every expected geometry pixel must be ink, independent of PNG metadata/hash.
    missing = ImageChops.multiply(gray, expected_ink)
    require(missing.getextrema()[1] == 0, "Missing/shifted geometric strokes")
    allowed = expected_ink.copy()
    boxes = layout["labels"]
    require(set(boxes) == set(points), "Missing/swapped labels")
    font = ImageFont.truetype("DejaVuSans.ttf", 28)
    for name, box in boxes.items():
        require(
            isinstance(box, list) and len(box) == 4 and all(type(v) is int for v in box),
            "Invalid label bounds",
        )
        x0, y0, x1, y1 = box
        require(12 <= x0 < x1 <= 708 and 12 <= y0 < y1 <= 708, "Cropped label")
        bbox = font.getbbox(name)
        require(
            (x1 - x0, y1 - y0) == (bbox[2] - bbox[0] + 8, bbox[3] - bbox[1] + 8), "Bad glyph size"
        )
        px, py = xy(points[name])
        require(
            math.hypot((x0 + x1) / 2 - px, (y0 + y1) / 2 - py) <= 72, "Label detached from vertex"
        )
        require(expected_ink.crop(tuple(box)).getextrema()[1] == 0, "Label crosses geometry")
        for other, b in boxes.items():
            if other != name:
                require(x1 < b[0] or b[2] < x0 or y1 < b[1] or b[3] < y0, "Overlapping labels")
        glyph = Image.new("RGB", (x1 - x0, y1 - y0), "white")
        ImageDraw.Draw(glyph).text((4 - bbox[0], 4 - bbox[1]), name, fill="black", font=font)
        require(
            ImageChops.difference(glyph, image.crop(tuple(box))).getbbox() is None,
            "Wrong or missing glyph",
        )
        ImageDraw.Draw(allowed).rectangle(tuple(box), fill=255)
    extra = ImageChops.multiply(ImageChops.invert(gray), ImageChops.invert(allowed))
    require(extra.getextrema()[1] == 0, "Unexpected ink outside model/glyphs")
    # Check all requested phone sizes retain every labeled vertex and every segment.
    for size in (360, 390, 430):
        mobile = gray.resize((size, size), Image.Resampling.LANCZOS)
        for box in boxes.values():
            b = tuple(round(v * size / 720) for v in box)
            require(
                cast(tuple[float, float], mobile.crop(b).getextrema())[0] < 160,
                "Label lost on mobile",
            )
        # Downsampled expected primitive ink must remain visible near its footprint.
        mask = expected_ink.resize((size, size), Image.Resampling.LANCZOS)
        dark = mobile.filter(ImageFilter.MinFilter(3))
        require(
            cast(tuple[float, float], ImageChops.multiply(dark, mask).getextrema())[1] < 235,
            "Mobile strokes lost",
        )
