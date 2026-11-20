"""Compact Telegram OGE progress infographic. Pillow only, no AI rendering.

Example (aiogram):
    png = render_progress_png(
        display_name='Вася', username='vasya',
        per_task={1: (1, 1), 6: (1, 2), 7: (4, 4)},
        skipped=126, task_count=25,
    )
    await message.answer_photo(BufferedInputFile(png, filename='progress.png'))

per_task maps task number to (correct_answers, answered_attempts).
The grid always uses ONE identical tile layout, including empty results.
"""
from __future__ import annotations

import os
from io import BytesIO
from pathlib import Path
from typing import Mapping

from PIL import Image, ImageDraw, ImageFont

WIDTH = 1200
MARGIN = 44
BG = "#F7F7F1"
INK = "#1F3531"
TEXT = "#263A36"
MUTED = "#6D7B75"
LINE = "#CDD6CC"
TILE = "#EAEEE6"
PANEL_EMPTY = "#E1E7E0"
ACCENT = "#F15E45"

FONTDIR = Path("/usr/share/fonts/opentype/inter")


def font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    env = os.environ.get("OGE_FONT_BOLD" if bold else "OGE_FONT_REGULAR")
    paths = [
        env,
        str(FONTDIR / ("InterDisplay-Bold.otf" if bold else "InterDisplay-Medium.otf")),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in paths:
        if path and Path(path).is_file():
            return ImageFont.truetype(path, size)
    raise RuntimeError(
        "A Cyrillic font is required; set OGE_FONT_REGULAR / OGE_FONT_BOLD"
    )


def hex_rgb(color: str) -> tuple[int, int, int]:
    h = color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def mix(a: str, b: str, portion_b: float) -> str:
    x, y = hex_rgb(a), hex_rgb(b)
    t = max(0, min(1, portion_b))
    return "#" + "".join(f"{round(u * (1-t) + v*t):02x}" for u, v in zip(x, y))


def accuracy_color(accuracy: float) -> str:
    """Smooth red -> amber -> green, no discrete 3-category jumps."""
    accuracy = min(1.0, max(0.0, accuracy))
    if accuracy <= .5:
        return mix("#CB5B50", "#B88C2F", accuracy * 2)
    return mix("#B88C2F", "#268455", (accuracy - .5) * 2)


def text_fit(draw: ImageDraw.ImageDraw, text: str, max_w: int, sz: int) -> str:
    rendered_font = font(sz, bold=True)
    if draw.textlength(text, font=rendered_font) <= max_w:
        return text
    while text and draw.textlength(text + "…", font=rendered_font) > max_w:
        text = text[:-1]
    return (text + "…") if text else "…"


def render_progress_png(
    display_name: str,
    username: str | None,
    per_task: Mapping[int, tuple[int, int]],
    skipped: int,
    task_count: int = 25,
) -> bytes:
    """Return complete PNG bytes; works for current 19 and upcoming 25 task types."""
    if not 1 <= task_count <= 25:
        raise ValueError("task_count must be between 1 and 25")
    if skipped < 0:
        raise ValueError("skipped must be nonnegative")
    for num, (correct, answered) in per_task.items():
        if not (1 <= num <= task_count and 0 <= correct <= answered):
            raise ValueError(f"Invalid task data at #{num}")

    totals = [per_task.get(i, (0, 0)) for i in range(1, task_count + 1)]
    total_correct = sum(c for c, _ in totals)
    total_answered = sum(a for _, a in totals)
    overall = round(total_correct * 100 / total_answered) if total_answered else None

    cols = 5
    rows = (task_count + cols - 1) // cols
    gap, tile_h = 9, 126
    grid_y = 407
    grid_bottom = grid_y + rows * tile_h + (rows - 1) * gap
    height = max(970, grid_bottom + 81)
    image = Image.new("RGB", (WIDTH, height), BG)
    draw = ImageDraw.Draw(image)
    right = WIDTH - MARGIN

    # A tiny identity label, then one (non-duplicated) page title.
    draw.ellipse((MARGIN, 43, MARGIN + 52, 95), fill=INK)
    name = " ".join((display_name or "").split()) or "Ученик"
    draw.text((MARGIN + 26, 69), name[0].upper(), font=font(28, bold=True),
              fill=BG, anchor="mm")
    username_text = ("@" + username.lstrip("@").strip()) if username else ""
    draw.text((MARGIN + 72, 49), text_fit(draw, name, 580, 30),
              font=font(30, bold=True), fill=INK)
    if username_text:
        draw.text((MARGIN + 72, 84), text_fit(draw, username_text, 580, 20),
                  font=font(20), fill=MUTED)
    draw.text((MARGIN - 3, 110), "Твой прогресс", font=font(67, bold=True),
              fill=INK)
    draw.rounded_rectangle((MARGIN, 190, MARGIN + 148, 198), radius=4, fill=ACCENT)

    # One horizontal data strip, not three giant rounded cards.
    draw.line((MARGIN, 229, right, 229), fill=LINE, width=2)
    draw.line((MARGIN, 345, right, 345), fill=LINE, width=2)
    draw.line((438, 245, 438, 330), fill=LINE, width=2)
    draw.line((808, 245, 808, 330), fill=LINE, width=2)
    success_txt = f"{overall}%" if overall is not None else "—"
    success_rgb = accuracy_color(overall / 100) if overall is not None else INK
    draw.text((MARGIN, 244), success_txt, font=font(68, bold=True), fill=success_rgb)
    draw.text((MARGIN, 321), "УСПЕШНОСТЬ", font=font(19, bold=True), fill=MUTED)
    draw.text((471, 245), str(total_correct), font=font(65, bold=True), fill=INK)
    draw.text((473, 321), "ВЕРНО", font=font(19, bold=True), fill=MUTED)
    draw.text((840, 245), str(skipped), font=font(65, bold=True), fill=INK)
    draw.text((841, 321), "ПРОПУЩЕНО", font=font(19, bold=True), fill=MUTED)
    draw.text((MARGIN, 359), "По номерам", font=font(34, bold=True), fill=INK)
    draw.text((right, 375), f"{task_count} ЗАДАНИЙ", font=font(20, bold=True),
              fill=MUTED, anchor="ra")

    tile_w = (WIDTH - 2 * MARGIN - gap * (cols - 1)) // cols
    for i, (correct, answered) in enumerate(totals):
        number = i + 1
        col, row = i % cols, i // cols
        x = MARGIN + col * (tile_w + gap)
        y = grid_y + row * (tile_h + gap)
        accuracy = correct / answered if answered else None
        percent = round(accuracy * 100) if accuracy is not None else None

        # Identical geometry in all cells. Only text and colors vary.
        draw.rounded_rectangle((x, y, x + tile_w, y + tile_h), radius=13,
                               fill=TILE, outline="#D8DED5", width=2)
        pill_x1, pill_y1 = x + 108, y + 13
        pill_x2, pill_y2 = x + tile_w - 12, y + tile_h - 13
        color = accuracy_color(accuracy) if accuracy is not None else MUTED
        pill_bg = mix(BG, color, .135) if accuracy is not None else PANEL_EMPTY
        draw.rounded_rectangle((pill_x1, pill_y1, pill_x2, pill_y2),
                               radius=9, fill=pill_bg)
        num_color = color if answered >= 5 else INK
        draw.text((x + 14, y + 17), f"№{number}", font=font(30, bold=True),
                  fill=num_color)
        draw.text((x + 14, y + 77), f"{correct}/{answered}",
                  font=font(24), fill=TEXT)
        value = f"{percent}%" if percent is not None else "—"
        draw.text(((pill_x1 + pill_x2) // 2, (pill_y1 + pill_y2) // 2 + 1), value,
                  font=font(34, bold=True), fill=color, anchor="mm")

    # Tiny legend, not an oversized bottom notice.
    foot_y = grid_bottom + 27
    draw.line((MARGIN, foot_y - 8, right, foot_y - 8), fill=LINE, width=2)
    draw.text((MARGIN, foot_y + 4), "До 5 ответов процент предварительный",
              font=font(20), fill=MUTED)
    gx1, gy, gx2 = right - 240, foot_y + 13, right
    for xx in range(gx1, gx2):
        ratio = (xx - gx1) / (gx2 - gx1 - 1)
        draw.line((xx, gy, xx, gy + 10), fill=accuracy_color(ratio), width=1)
    draw.text((gx1, gy + 18), "0%", font=font(15), fill=MUTED)
    draw.text((gx2, gy + 18), "100%", font=font(15), fill=MUTED, anchor="ra")

    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


if __name__ == "__main__":
    demo = {1: (1, 1), 6: (1, 2), 7: (4, 4), 8: (1, 1), 9: (1, 1),
            11: (1, 1), 13: (2, 3), 19: (1, 1)}
    for count in (19, 25):
        rendered = render_progress_png(
            "Вася", "vasya", demo, skipped=126, task_count=count
        )
        Path(__file__).with_name(f"oge_progress_uniform_{count}.png").write_bytes(rendered)
        print(f"Created {count} tasks: {len(rendered)} bytes")
