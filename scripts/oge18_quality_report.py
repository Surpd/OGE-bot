"""Reproduce OGE18 coordinate/pixel QA and bounded source previews."""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from io import BytesIO
from pathlib import Path
from statistics import median
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw  # noqa: E402

from app.math.answer_policy import NUMERIC_SHORT_ANSWER  # noqa: E402
from app.math.oge18 import (  # noqa: E402
    FAMILIES,
    GENERATOR_VERSION,
    GENERATOR_VERSION_V2,
    NEW_FAMILIES,
    SOURCES,
    from_snapshot,
    generate,
)
from app.math.oge18_oracle import answer, answer_family  # noqa: E402
from app.math.oge18_render import VERSION, VERSION_V2, audit, audit_family  # noqa: E402

PUBLIC_ENABLED: tuple[str, ...] = ()
LOW_CAPACITY = {
    "OGE18-D05": 3,
    "OGE18-L02": 21,
    "OGE18-A03": 130,
    "OGE18-A04": 75,
    "OGE18-A05": 6,
}


def _contact_sheet(
    family: str, variants: list[tuple[int, bytes]], width: int, directory: Path
) -> None:
    height = round(640 * width / 720)
    cell_height = height + 30
    columns = 4
    rows = max(1, (len(variants) + columns - 1) // columns)
    sheet = Image.new("RGB", (width * columns, cell_height * rows), "white")
    draw = ImageDraw.Draw(sheet)
    for index, (seed, png) in enumerate(variants):
        image = Image.open(BytesIO(png)).convert("RGB")
        image = image.resize((width, height), Image.Resampling.LANCZOS)
        x, y = (index % columns) * width, (index // columns) * cell_height
        sheet.paste(image, (x, y + 30))
        draw.text((x + 8, y + 7), f"{family} seed={seed}", fill="black")
    sheet.save(directory / f"{family}-{width}-contact.png", optimize=True)


def run() -> dict[str, object]:
    directory = ROOT / "reports/previews/oge18"
    directory.mkdir(parents=True, exist_ok=True)
    all_families = (*FAMILIES, *NEW_FAMILIES)
    records: dict[str, object] = {}
    for family in all_families:
        new = family in NEW_FAMILIES
        version = GENERATOR_VERSION_V2 if new else GENERATOR_VERSION
        seen: set[str] = set()
        previews: list[tuple[int, bytes]] = []
        answers: Counter[str] = Counter()
        generation_ms: list[float] = []
        restore_ms: list[float] = []
        pixel_audit_ms: list[float] = []
        attempts = 0
        accepted = 0
        for seed in range(1200):
            started = perf_counter()
            problem = generate(family, seed, version)
            generation_ms.append((perf_counter() - started) * 1000)
            snapshot = problem.to_snapshot()
            points = tuple(tuple(point) for point in snapshot["points"])
            oracle_result = answer(points) if not new else answer_family(family, points)
            if NUMERIC_SHORT_ANSWER.parse(snapshot["correct_answer"]) != oracle_result:
                raise AssertionError(f"Oracle mismatch: {family} seed={seed}")
            png = problem.png_bytes
            if hashlib.sha256(png).hexdigest() != snapshot["image_sha256"]:
                raise AssertionError(f"PNG hash mismatch: {family} seed={seed}")
            with Image.open(BytesIO(png)) as raster:
                if raster.format != "PNG" or raster.size != (720, 640):
                    raise AssertionError(f"PNG contract mismatch: {family} seed={seed}")
                raster.verify()
            if seed < 50:
                started = perf_counter()
                restored = from_snapshot(snapshot, audit_pixels=False)
                restore_ms.append((perf_counter() - started) * 1000)
                if restored.png_bytes != png:
                    raise AssertionError(f"Restore PNG mismatch: {family} seed={seed}")
                started = perf_counter()
                if new:
                    audit_family(png, family, points)
                else:
                    audit(png, points, family == FAMILIES[0])
                pixel_audit_ms.append((perf_counter() - started) * 1000)
            answers[str(snapshot["correct_answer"])] += 1
            if problem.fingerprint not in seen and len(previews) < 20:
                previews.append((seed, problem.png_bytes))
            seen.add(problem.fingerprint)
            attempts += 1
            accepted += 1
            unique_target = LOW_CAPACITY.get(family, 200)
            if accepted >= 300 and len(seen) >= unique_target:
                break
        if new:
            for width in (720, 360):
                _contact_sheet(family, previews, width, directory)
            (directory / f"{family}-seed0.png").write_bytes(previews[0][1])
        if new and family in LOW_CAPACITY:
            quality_status = "math_hold"
            capacity_note = (
                f"Finite implemented parameter model has exactly {LOW_CAPACITY[family]} "
                "normalized shapes; no synthetic novelty added."
            )
        else:
            quality_status = "implemented_closed"
            capacity_note = (
                "At least 200 distinct normalized model fingerprints found within the "
                "1200-seed budget."
                if len(seen) >= 200
                else (
                    f"Observed {len(seen)} distinct fingerprints in {attempts} seeds; "
                    "see implementation note."
                )
            )
        records[family] = {
            "qa_status": quality_status,
            "source_status": "catalog_visual_verified"
            if new
            else "prior_reference_visual_verified",
            "public_enabled": family in PUBLIC_ENABLED,
            "source_id": SOURCES[family],
            "source_url": f"https://math-oge.sdamgia.ru/problem?id={SOURCES[family]}",
            "generator_version": version,
            "renderer_version": VERSION_V2 if new else VERSION,
            "smoke_seed_count": 50,
            "candidate_count": accepted,
            "seed_attempts_for_novelty": attempts,
            "unique_content_fingerprints": len(seen),
            "known_model_capacity_note": capacity_note,
            "answers": dict(sorted(answers.items(), key=lambda item: float(item[0]))),
            "independent_oracle_failures": 0,
            "versioned_png_restore_failures": 0,
            "full_pixel_audit_count": 50,
            "contact_sheet_distinct_variants": len(previews),
            "performance_ms_median": {
                "generation_and_png_hash": round(median(generation_ms), 3),
                "repeat_restore_sha_and_renderer_bytes": round(median(restore_ms), 3),
                "full_pixel_audit_smoke": round(median(pixel_audit_ms), 3),
            },
            "hold_reason": capacity_note if quality_status == "math_hold" else None,
        }
        print(
            f"{family}: {accepted} candidates / {len(seen)} fingerprints / {quality_status}",
            flush=True,
        )
    report = {
        "task": 18,
        "generator_versions": {"legacy": GENERATOR_VERSION, "new": GENERATOR_VERSION_V2},
        "renderer_versions": {"legacy": VERSION, "new": VERSION_V2},
        "families": records,
        "status_taxonomy": [
            "implemented_closed",
            "source_hold",
            "math_hold",
            "visual_hold",
            "public_enabled",
        ],
        "status_counts": {
            "implemented_closed": sum(
                record["qa_status"] == "implemented_closed" for record in records.values()
            ),
            "source_hold": sum(record["qa_status"] == "source_hold" for record in records.values()),
            "math_hold": sum(record["qa_status"] == "math_hold" for record in records.values()),
            "visual_hold": sum(record["qa_status"] == "visual_hold" for record in records.values()),
            "public_enabled": sum(record["public_enabled"] for record in records.values()),
        },
        "smoke_samples_per_family": 50,
        "main_candidate_target": 300,
        "uniqueness_seed_budget": 1200,
        "phone_widths": [360, 390, 430],
        "visual_review": (
            "All six original catalog source diagrams were manually inspected. The 360px and "
            "720px contact sheets for all six new families were manually inspected; this covers "
            "20 distinct variants per family where available, 3 for D05, and 6 for A05."
        ),
        "manual_contact_sheet_review": {
            "new_families_reviewed": list(NEW_FAMILIES),
            "widths": [360, 720],
            "distinct_variants_seen": {
                "OGE18-D05": 3,
                "OGE18-L02": 20,
                "OGE18-A01": 20,
                "OGE18-A03": 20,
                "OGE18-A04": 20,
                "OGE18-A05": 6,
            },
        },
        "live_telegram_mobile_smoke": "not_performed; no public release claim",
        "public_enabled_families": list(PUBLIC_ENABLED),
        "source_originals_embedded": False,
        "preview_policy": (
            "Maximum 20 distinct generated PNG per family in each contact sheet; one seed0 PNG "
            "retained; existing M01/M02 previews retained."
        ),
    }
    (ROOT / "reports/oge18-quality.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    return report


if __name__ == "__main__":
    run()
