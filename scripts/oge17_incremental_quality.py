"""Bounded QA for explicitly selected changed №17 families; preserve previous evidence."""

import argparse
import base64
import json
import sys
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.math.oge17_generator import build, from_snapshot, generate, parameters  # noqa: E402
from app.math.oge17_models import FAMILIES  # noqa: E402
from app.math.oge17_oracle import audit_math  # noqa: E402


def run(families: list[str]) -> None:
    output = Path("reports/oge17-incremental-quality.json")
    report = json.loads(output.read_text()) if output.exists() else {}
    for family in families:
        if family not in FAMILIES:
            raise ValueError(f"Unknown implemented family: {family}")
        for seed in range(150):
            data = build(family, parameters(family, seed))
            audit_math({**data, "family_id": family})
        sheet = Image.new("RGB", (720, 580), "white")
        draw = ImageDraw.Draw(sheet)
        for seed in range(10):
            item = generate(family, seed)
            snapshot = item.to_snapshot()
            assert from_snapshot(snapshot, expected_problem_id=snapshot["problem_id"]) == item
            if seed < 4:
                png = Image.open(BytesIO(base64.b64decode(snapshot["png_base64"])))
                x, y = (seed % 2) * 360, (seed // 2) * 290
                sheet.paste(png.resize((360, 270), Image.Resampling.LANCZOS), (x, y + 20))
                draw.text((x + 8, y + 3), f"{family} seed={seed}", fill="black")
        sheet.save(f"reports/oge17-previews/{family}-review.png")
        report[family] = {
            "mathematical_audits": 150,
            "snapshot_replays": 10,
            "png_pixel_audits": 10,
            "visual_examples": 4,
            "public_enabled": False,
            "failures": 0,
        }
        print(f"{family}: 150 math, 10 replay/PNG, four review examples", flush=True)
    output.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("families", nargs="+", choices=FAMILIES)
    run(parser.parse_args().families)
