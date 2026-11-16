"""Bounded reproducible QA for closed geometry №15."""

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.math.oge15_oracle import answer  # noqa: E402
from app.math.oge15_triangles import FAMILIES, POLICY, from_snapshot, generate  # noqa: E402


def run():
    records = {}
    for family in FAMILIES:
        seen = set()
        answers = Counter()
        for seed in range(1200):
            problem = generate(family, seed)
            snapshot = problem.to_snapshot()
            assert answer(family, tuple(snapshot["parameters"])) == POLICY.parse(
                snapshot["correct_answer"]
            )
            assert from_snapshot(snapshot) == problem
            seen.add(problem.fingerprint)
            answers[snapshot["correct_answer"]] += 1
        records[family] = {
            "status": "implemented_closed",
            "public_enabled": False,
            "smoke_seeds": 50,
            "generations": 1200,
            "fingerprints": len(seen),
            "answer_distribution": dict(answers),
            "oracle_failures": 0,
            "snapshot_failures": 0,
            "png": "not_required_text_complete",
        }
        print(f"{family}: 1200 generated; {len(seen)} fingerprints")
    (ROOT / "reports/oge15-quality.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2) + "\n"
    )
    vectors = [
        {"family_id": family, "seed": seed, "snapshot": generate(family, seed).to_snapshot()}
        for family in FAMILIES
        for seed in (0, 42, 123)
    ]
    path = ROOT / "atlas/oge15_regression_vectors.json"
    if path.exists():
        assert json.loads(path.read_text()) == vectors, "Regression vectors changed"
    else:
        path.write_text(json.dumps(vectors, ensure_ascii=False, indent=2) + "\n")


def write_overviews(directory: Path) -> None:
    from PIL import Image

    from app.math.oge15_complete import ALL_FAMILIES

    for width in (360, 390):
        cell_height = round(520 * width / 720) + 28
        for batch in range(3):
            sheet = Image.new("RGB", (width * 4, cell_height * 7), "white")
            for row, family in enumerate(ALL_FAMILIES[1 + 7 * batch : 1 + 7 * (batch + 1)]):
                contact = Image.open(directory / f"{family}-{width}-contact.png")
                for seed in range(4):
                    x, y = seed % 2 * width, seed // 2 * cell_height
                    tile = contact.crop((x, y, x + width, y + cell_height))
                    sheet.paste(tile, (seed * width, row * cell_height))
            sheet.save(directory / f"overview-{batch + 1}-{width}.png", optimize=True)


def run_complete(families: tuple[str, ...] | None = None):
    import base64
    from io import BytesIO
    from statistics import median
    from time import perf_counter

    from PIL import Image, ImageDraw

    from app.math.oge15_complete import ALL_FAMILIES, VERSION, content, content_key, parameters
    from app.math.oge15_coordinate_oracle import validate
    from app.math.oge15_geometry import construct

    if families is None:
        run()  # Preserve the original six immutable regression vectors.
        legacy = json.loads((ROOT / "reports/oge15-quality.json").read_text())
        records = {}
    else:
        previous = json.loads((ROOT / "reports/oge15-quality.json").read_text())
        legacy = previous["legacy_v1"]
        records = previous["complete_v2"]
    previews = ROOT / "reports/previews/oge15"
    previews.mkdir(parents=True, exist_ok=True)
    for n, family in enumerate(ALL_FAMILIES, 1):
        if families is not None and family not in families:
            continue
        seen = set()
        answers = Counter()
        pngs = []
        timing = []
        for seed in range(1200):
            p = parameters(n, seed)
            value = content(n, p)[3]
            validate(n, p, construct(n, p), value)
            seen.add(content_key(n, p))
            if seed < 300:
                started = perf_counter()
                problem = generate(family, seed, VERSION)
                snapshot = problem.to_snapshot()
                try:
                    assert from_snapshot(snapshot) == problem
                except ValueError as exc:
                    raise ValueError(f"{family} seed={seed}: {exc}") from exc
                timing.append((perf_counter() - started) * 1000)
                answers[snapshot["correct_answer"]] += 1
                if n != 1 and len(pngs) < 4:
                    pngs.append(base64.b64decode(snapshot["png_base64"]))
        for width in (360, 390) if n != 1 else ():
            height = round(520 * width / 720)
            sheet = Image.new("RGB", (width * 2, (height + 28) * 2), "white")
            draw = ImageDraw.Draw(sheet)
            for index, png in enumerate(pngs):
                image = Image.open(BytesIO(png)).resize((width, height), Image.Resampling.LANCZOS)
                x, y = index % 2 * width, index // 2 * (height + 28)
                sheet.paste(image, (x, y + 28))
                draw.text((x + 6, y + 6), f"{family} seed={index}", fill="black")
            sheet.save(previews / f"{family}-{width}-contact.png", optimize=True)
        records[family] = {
            "status": "public_enabled",
            "generator_version": VERSION,
            "source_status": "original_condition_answer_and_diagram_verified"
            if n != 1
            else "text_only_original_verified",
            "oracle_model_checks": 1200,
            "render_and_snapshot_checks": 300,
            "smoke_seeds": 50,
            "unique_content_fingerprints_in_1200": len(seen),
            "answers": dict(answers),
            "median_generate_restore_ms": round(median(timing), 3),
            "visual_review": "pending",
            "preview_seed_count": len(pngs),
            "failures": 0,
        }
        print(f"{family} v2: 300 raster/replay, 1200 model; {len(seen)} fingerprints", flush=True)
    review_path = ROOT / "reports/oge15-visual-review.json"
    if review_path.exists():
        import hashlib

        reviewed = json.loads(review_path.read_text())["contact_sha256"]
        for family, record in records.items():
            matching = (
                all(
                    reviewed.get(f"{family}-{width}-contact.png")
                    == hashlib.sha256(
                        (previews / f"{family}-{width}-contact.png").read_bytes()
                    ).hexdigest()
                    for width in (360, 390)
                )
                if family != "OGE15-F01"
                else False
            )
            record["visual_review"] = (
                "assistant_visual_review_passed_seed0_3_at_360_390"
                if matching
                else "not_applicable"
                if family == "OGE15-F01"
                else "pending"
            )
    write_overviews(previews)
    (ROOT / "reports/oge15-quality.json").write_text(
        json.dumps(
            {
                "legacy_v1": legacy,
                "complete_v2": records,
                "visual_review_record": "reports/oge15-visual-review.json",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    run_complete()
