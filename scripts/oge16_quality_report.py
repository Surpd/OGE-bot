"""Compact, deterministic №16 preview report; no PNG bank or seed-volume quota."""

from __future__ import annotations

import hashlib
import json
import sys
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.math.oge16_circles import (  # noqa: E402
    ENABLED_FAMILIES,
    FAMILIES,
    GENERATOR_VERSION,
    from_snapshot,
    generate,
)
from app.math.oge16_complete import SOURCE_VARIANTS  # noqa: E402
from app.math.oge16_scheduler import finite_pool  # noqa: E402


def main() -> None:
    root = Path("reports/oge16")
    root.mkdir(parents=True, exist_ok=True)
    font = ImageFont.truetype("DejaVuSans.ttf", 14)
    rows = []
    tiles = []
    for family in FAMILIES:
        variants = len(SOURCE_VARIANTS[family[6:]])
        # Two visual examples: first source and the last source with a larger scale.
        seeds = (0, variants * 2 - 1)
        for index, seed in enumerate(seeds):
            problem = generate(family, seed)
            snapshot = problem.to_snapshot()
            if index == 0:
                (root / f"{family}.png").write_bytes(problem.png)
            assert hashlib.sha256(problem.png).hexdigest() == snapshot["figure"]["sha256"]
            for _ in range(5):
                assert from_snapshot(snapshot).png == problem.png
            tile = Image.new("RGB", (360, 394), "white")
            label = f"{family} · #{snapshot['provenance']['task_id']} · seed {seed}"
            ImageDraw.Draw(tile).text((8, 6), label, font=font, fill="black")
            diagram = Image.open(BytesIO(problem.png)).convert("RGB")
            tile.paste(diagram.resize((360, 360), Image.Resampling.LANCZOS), (0, 30))
            tiles.append(tile)
        rows.append(
            {
                "family_id": family,
                "sources": list(SOURCE_VARIANTS[family[6:]]),
                "mathematical_capacity": len(finite_pool(family)),
                "png_preview_samples": 2,
                "saved_snapshot_replays": 10,
                "public_enabled": family in ENABLED_FAMILIES,
                "preview": f"reports/oge16/{family}.png",
            }
        )
    sheets = []
    for page, start in enumerate(range(0, len(tiles), 12), 1):
        subset = tiles[start : start + 12]
        image = Image.new("RGB", (1080, 394 * ((len(subset) + 2) // 3)), "white")
        for index, tile in enumerate(subset):
            image.paste(tile, ((index % 3) * 360, (index // 3) * 394))
        path = root / f"contact-{page}.png"
        image.save(path, format="PNG")
        sheets.append(str(path))
    report = {
        "generator_version": GENERATOR_VERSION,
        "implemented_constructions": len(FAMILIES),
        "public_enabled": list(ENABLED_FAMILIES),
        "excluded_source_ids": ["323356"],
        "math_validation": (
            "Each finite 10–40 parameter-slot pool exhausted once in test_oge16_complete.py; "
            "no 1200-seed quota"
        ),
        "pixel_validation": (
            "Five PNG samples per family in tests; two visual previews; "
            "SHA, glyph and geometry audit at 360/390/430 pixels"
        ),
        "contact_sheets": sheets,
        "families": rows,
    }
    Path("reports/oge16-quality.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    print(f"№16: {len(rows)} constructions; {len(tiles)} visual tiles; {len(sheets)} sheets")


if __name__ == "__main__":
    main()
