"""Render phone-size contact sheets from the public schedulers and Telegram image path."""

from importlib import import_module
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw

from app.bot.mixed_training import _builders, _render_image
from app.math.scenarios.mobile_photos import font

OUTPUT = Path("reports/previews/print-review")
PROBES = ((0, 360), (42, 390), (90126, 430))


def samples(number: int, family: str) -> list[tuple[Image.Image, str]]:
    build = _builders()[number]
    options = {"enabled_families": (family,)}
    if number == 7:
        options = {"family_ids": (family,), "limit": 1}
    elif number == 13:
        options = {"limit": 1}
    row = []
    for seed, width in PROBES:
        snapshot = build({"family_queue": [family]}, seed, **options)[0]
        assert snapshot["family_id"] == family
        payload = _render_image(number, snapshot)
        if payload:
            with Image.open(BytesIO(payload)) as original:
                size = (width, round(original.height * width / original.width))
                image = original.convert("RGB").resize(size, Image.Resampling.LANCZOS)
            row.append((image, f"{family}   seed {snapshot['seed']}"))
    return row


def generate() -> None:
    OUTPUT.mkdir(exist_ok=True, parents=True)
    for number in (7, 11, 13, 15, 16, 17, 18):
        families = import_module(f"app.math.oge{number:02}_scheduler").ENABLED_FAMILIES
        rows = [row for family in families if (row := samples(number, family))]
        for offset in range(0, len(rows), 4):
            page = rows[offset:offset + 4]
            heights = [max(image.height for image, _ in row) + 33 for row in page]
            sheet = Image.new("RGB", (1200, sum(heights)), "#eeeff1")
            draw = ImageDraw.Draw(sheet)
            y = 0
            for row, height in zip(page, heights, strict=True):
                x = 4
                for image, title in row:
                    draw.text((x, y + 4), title, font=font(14), fill="black")
                    sheet.paste(image, (x, y + 27))
                    x += image.width + 6
                y += height
            sheet.save(OUTPUT / f"number-{number}-{offset // 4 + 1}.png")


if __name__ == "__main__":
    generate()
