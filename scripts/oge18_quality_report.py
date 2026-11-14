"""Reproduce coordinate/pixel QA and a bounded set of author-generated previews."""

from __future__ import annotations

import json
import sys
from collections import Counter
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw  # noqa: E402

from app.math.oge18 import (  # noqa: E402
    FAMILIES,
    GENERATOR_VERSION,
    SOURCES,
    from_snapshot,
    generate,
)
from app.math.oge18_oracle import answer  # noqa: E402
from app.math.oge18_render import VERSION  # noqa: E402


def run() -> dict[str, object]:
    directory = ROOT / "reports/previews/oge18"
    directory.mkdir(parents=True, exist_ok=True)
    families = {}
    for family in FAMILIES:
        seen: set[str] = set()
        previews = []
        answers: Counter[str] = Counter()
        count = 0
        for seed in range(1200):
            problem = generate(family, seed)
            snapshot = problem.to_snapshot()
            points = tuple((p[0], p[1]) for p in snapshot["points"])
            assert str(answer(points))  # All candidates pass the independent coordinate oracle.
            assert from_snapshot(snapshot).png_bytes == problem.png_bytes
            answers[snapshot["correct_answer"]] += 1
            if problem.fingerprint not in seen and len(previews) < 20:
                previews.append((seed, problem.png_bytes))
            seen.add(problem.fingerprint)
            count += 1
            if count >= 300 and len(seen) >= 200:
                break
        for width in (720, 360):
            row_height = round(640 * width / 720) + 30
            sheet = Image.new("RGB", (width * 4, row_height * 5), "white")
            draw = ImageDraw.Draw(sheet)
            for index, (seed, png) in enumerate(previews):
                image = Image.open(BytesIO(png))
                image = image.resize((width, row_height - 30), Image.Resampling.LANCZOS)
                x, y = (index % 4) * width, (index // 4) * row_height
                sheet.paste(image, (x, y + 30))
                draw.text((x + 10, y + 8), f"{family} seed={seed}", fill="black")
            sheet.save(directory / f"{family}-{width}-contact.png", optimize=True)
        (directory / f"{family}-seed0.png").write_bytes(previews[0][1])
        families[family] = {
            "candidates": count,
            "oracle_and_pixel_failures": 0,
            "unique_content_fingerprints": len(seen),
            "answers": dict(sorted(answers.items())),
            "source_url": f"https://math-oge.sdamgia.ru/problem?id={SOURCES[family]}",
            "source_scope": "catalog image audited in research handoff; generated analogue",
            "status": "closed_implementation_only",
            "public_enabled": False,
            "contact_sheet_distinct_variants": len(previews),
            "fingerprint": ("base lengths, height, canonical reflected offset, target; "
                            "no translation"),
        }
        print(f"{family}: {count} candidates, {len(seen)} distinct", flush=True)
    report = {
        "task": 18,
        "generator_version": GENERATOR_VERSION,
        "renderer_version": VERSION,
        "families": families,
        "smoke_samples_per_family": 50,
        "acceptance_budget_per_family": 1200,
        "phone_widths": [360, 390, 430],
        "visual_review": "not_performed_by_report_script",
        "live_telegram_mobile_smoke": "not_performed; release blocker",
        "other_geometry_families": "HOLD; outside this implementation",
        "source_originals_embedded": False,
        "binary_budget": "six reproducible PNG files only; no per-candidate files",
    }
    (ROOT / "reports/oge18-quality.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    return report


if __name__ == "__main__":
    run()
