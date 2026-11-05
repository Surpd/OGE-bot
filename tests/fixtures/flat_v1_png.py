"""Frozen c2570e9 FLAT PNG renderer for cross-version byte compatibility tests.

PNG codec output can differ between Pillow platform wheels. Compare the old and
new renderer in the SAME runtime, without changing the production digest guard.
This fixture must remain independent of current FLAT geometry/render helpers.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from PIL import Image, ImageDraw, ImageFont

from app.math.scenario_engine import ScenarioDraft

ROOM_PARTS = {
    "bedroom": ((0, 0, 6, 13),),
    "bedroom_2": ((18, 0, 24, 13),),
    "living": ((6, 0, 18, 13),),
    "hall": ((9, 13, 24, 19), (5, 18, 9, 19)),
    "pantry": ((5, 13, 9, 18),),
    "bathroom": ((0, 13, 5, 19),),
    "loggia_1": ((-3, 1, 0, 11),),
    "loggia_2": ((18, -5, 24, 0),),
}
DOOR_MARKS = (
    (6, 6, "v"),
    (18, 6, "v"),
    (21, 13, "h"),
    (12, 13, "h"),
    (9, 15, "v"),
    (5, 15, "v"),
    (0, 6, "v"),
    (21, 0, "h"),
)
WINDOW_MARKS = ((10, 0, "h"), (0, 16, "v"))


class Renderer:
    def _png(self, scenario: ScenarioDraft) -> bytes:
        c = scenario.context
        labels = cast(Mapping[str, int], c["room_labels"])
        scale, ox, oy = 36, 150, 210
        image = Image.new("RGB", (1120, 1000), "white")
        draw = ImageDraw.Draw(image)
        font: ImageFont.FreeTypeFont | ImageFont.ImageFont
        try:
            font = ImageFont.truetype("arial.ttf", 18)
        except OSError:
            font = ImageFont.load_default()
        draw.text((40, 30), "План квартиры · клетка 0,4 м", fill="#202b38", font=font)
        draw.text(
            (40, 62),
            "Сторона клетки 0,4 м · синие проёмы — двери · бирюзовые — окна · вход красный",
            fill="#202b38",
            font=font,
        )
        for room, rectangles in ROOM_PARTS.items():
            for x1, y1, x2, y2 in rectangles:
                box = (ox + x1 * scale, oy + y1 * scale, ox + x2 * scale, oy + y2 * scale)
                draw.rectangle(box, fill="white")
                for gx in range(x1 + 1, x2):
                    px = ox + gx * scale
                    draw.line((px, box[1], px, box[3]), fill="#dce4eb", width=1)
                for gy in range(y1 + 1, y2):
                    py = oy + gy * scale
                    draw.line((box[0], py, box[2], py), fill="#dce4eb", width=1)
                draw.rectangle(box, outline="#202b38", width=4)
            x1, y1, x2, y2 = rectangles[0]
            cx, cy = ox + (x1 + x2) * scale // 2, oy + (y1 + y2) * scale // 2
            draw.ellipse(
                (cx - 17, cy - 17, cx + 17, cy + 17), fill="#e9f2ff", outline="#1463a5", width=2
            )
            draw.text((cx - 6, cy - 12), str(labels[room]), fill="#102b45", font=font)
        for x, y, orientation in DOOR_MARKS:
            px, py = ox + x * scale, oy + y * scale
            bounds = (
                (px - 12, py, px + 12, py) if orientation == "h" else (px, py - 12, px, py + 12)
            )
            draw.line(bounds, fill="white", width=8)
            draw.line(bounds, fill="#1463a5", width=3)
        for x, y, orientation in WINDOW_MARKS:
            px, py = ox + x * scale, oy + y * scale
            bounds = (
                (px - 30, py, px + 30, py) if orientation == "h" else (px, py - 30, px, py + 30)
            )
            draw.line(bounds, fill="white", width=9)
            draw.line(bounds, fill="#008b8b", width=4)
        entry_x, entry_y = ox + 7 * scale, oy + 19 * scale
        draw.line((entry_x - 30, entry_y, entry_x + 30, entry_y), fill="white", width=9)
        draw.line((entry_x - 30, entry_y, entry_x + 30, entry_y), fill="#bd3030", width=5)
        draw.text((entry_x - 20, entry_y + 8), "Вход", fill="#202b38", font=font)
        from io import BytesIO

        buf = BytesIO()
        image.save(buf, format="PNG", optimize=False)
        return buf.getvalue()
