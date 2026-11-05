import sys
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw

from app.bot.scenario_training import public_registry
from app.math.scenario_engine import PracticeMode, PracticeRequest, build_practice_plan
from app.math.scenarios.mobile_photos import font, scenario_photos

root = Path(sys.argv[1])
root.mkdir(parents=True, exist_ok=True)
for story in public_registry().available_stories(PracticeMode.FULL):
    columns = []
    for seed in (0, 42, 90126):
        snapshot = build_practice_plan(
            PracticeRequest(PracticeMode.FULL, seed, story), public_registry()
        ).snapshot
        column = []
        for index, photo in enumerate(scenario_photos(snapshot), 1):
            (root / f"{story}-{seed}-{index}.png").write_bytes(photo)
            img = Image.open(BytesIO(photo)).convert("RGB")
            column.append(img.resize((390, round(390 * img.height / img.width)),
                                     Image.Resampling.LANCZOS))
        columns.append((seed, column))
    height = max(48 + sum(image.height + 16 for image in col) for _, col in columns)
    sheet = Image.new("RGB", (1202, height), "#e1e8f0")
    draw = ImageDraw.Draw(sheet)
    for index, (seed, col) in enumerate(columns):
        x, y = 8 + 398 * index, 48
        draw.text((x, 8), f"{story} · seed {seed} · 390 px", fill="#182e43", font=font(20))
        for image in col:
            sheet.paste(image, (x, y))
            y += image.height + 16
    sheet.save(root / f"{story}-contact-390.png")
