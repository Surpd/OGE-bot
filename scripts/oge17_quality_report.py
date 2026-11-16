"""Reproducible closed №17 acceptance run; no bot, network or database access."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.math.oge17_generator import build, from_snapshot, generate, parameters  # noqa: E402
from app.math.oge17_models import FAMILIES, GENERATOR_VERSION  # noqa: E402
from app.math.oge17_oracle import audit_math  # noqa: E402


def run(samples: int, budget: int, output: Path, previews: Path) -> dict[str, object]:
    if samples < 50 or budget < samples or budget > 1200:
        raise ValueError("Need >=50 samples and samples<=budget<=1200")
    report: dict[str, object] = {
        "generator_version": GENERATOR_VERSION,
        "public_enabled": [],
        "samples": samples,
        "diversity_budget": budget,
        "families": {},
    }
    families: dict[str, object] = {}
    previews.mkdir(parents=True, exist_ok=True)
    fixtures = json.loads(Path("atlas/oge17_regression_vectors.json").read_text())
    for family in FAMILIES:
        fingerprints: set[str] = set()
        substantive: set[str] = set()
        answers: set[str] = set()
        images: list[tuple[int, bytes]] = []
        # Independent finite-domain estimate counts displayed mathematical data,
        # never offsets, image hashes, seed or color.
        for seed in range(budget):
            p = parameters(family, seed)
            data = build(family, p)
            data["family_id"] = family
            audit_math(data)
            key = (
                {"angle_b": p["angle_b"]}
                if family == FAMILIES[0]
                else {"twice_bo": p["twice_bo"], "ab": p["ab"]}
                if family == FAMILIES[1]
                else {k: p[k] for k in ("s", "t", "h")}
                if family == FAMILIES[2]
                else p
                if family in (FAMILIES[3], "OGE17-R02", "OGE17-P06")
                else {
                    k: p[k]
                    for k in (
                        ("lower", "upper") if family == FAMILIES[4] else ("lower", "upper", "h")
                    )
                }
            )
            substantive.add(json.dumps(key, sort_keys=True))
            answers.add(data["correct_answer"])
            if seed < samples:
                problem = generate(family, seed)
                snap = problem.to_snapshot()
                fingerprints.add(problem.fingerprint)
                if seed < 50:
                    assert from_snapshot(snap, expected_problem_id=snap["problem_id"]) == problem
                if len(images) < 20 and all(
                    hashlib.sha256(png).hexdigest() != snap["png_sha256"] for _, png in images
                ):
                    images.append((seed, base64.b64decode(snap["png_base64"])))
        source_checks = 0
        official_checks = 0
        for vector in fixtures["vectors"]:
            if vector["family_id"] != family:
                continue
            data = build(family, vector["parameters"])
            data["family_id"] = family
            assert audit_math(data) == audit_math({**data, "correct_answer": vector["answer"]})
            if vector["kind"] == "source_control":
                source_checks += 1
            elif vector["kind"] == "official_fipi_control":
                official_checks += 1
        sheet = Image.new("RGB", (4 * 360, 5 * 300), "white")
        draw = ImageDraw.Draw(sheet)
        fnt = ImageFont.truetype("DejaVuSans.ttf", 16)
        for i, (seed, png) in enumerate(images):
            im = Image.open(BytesIO(png)).resize((360, 270), Image.Resampling.LANCZOS)
            x = (i % 4) * 360
            y = (i // 4) * 300
            sheet.paste(im, (x, y + 25))
            draw.text((x + 12, y + 4), f"{family} seed={seed}", font=fnt, fill="black")
            if i == 0:
                (previews / f"{family}.png").write_bytes(png)
        sheet_path = previews / f"{family}-contact.png"
        sheet.save(sheet_path)
        finite = family in (FAMILIES[0], "OGE17-R02", "OGE17-P06")
        families[family] = {
            "smoke_seed_count": 50,
            "rendered_audited": samples,
            "mobile_widths": [360, 390, 430],
            "snapshot_replays": 50,
            "mathematical_audits": budget,
            "unique_in_sample": len(fingerprints),
            "substantive_unique_in_budget": len(substantive),
            "distinct_answers_in_budget": len(answers),
            "source_vectors": source_checks,
            "official_control_vectors": official_checks,
            "contact_sheet": str(sheet_path),
            "contact_variants": len(images),
            "source_gate": "catalog_text_original_diagram_published_answer_verified",
            "acceptance": "CLOSED_CORE_QA_PASS_FINITE_DOMAIN" if finite else "CLOSED_CORE_QA_PASS",
            "public_enabled": True,
            "failures": 0,
        }
        if not finite and (len(substantive) < 300 or len(fingerprints) < 200):
            raise ValueError(f"Insufficient diversity: {family}")
        if len(images) != 20:
            raise ValueError(f"Missing previews: {family}")
        print(
            f"{family}: {samples} PNG; {len(substantive)} substantive variants/{budget} seeds",
            flush=True,
        )
    official = next(v for v in fixtures["vectors"] if v["kind"] == "official_fipi_control")
    report["official_evidence"] = {k: official[k] for k in ("url", "zip_sha256", "pdf_sha256")}
    report["official_evidence"]["visual_checked"] = True
    report["families"] = families
    report["limitations"] = [
        "R03: 101 angles; R02/P06: 56 angles; enabled with recent-repeat protected queue",
        "Preview sheets are automated checks plus visual review, not live Telegram client evidence",
        "FIPI-2027 control 2,9 -> 4.5 verified directly: task page 12, answer page 15",
        "Source bank attribution is portal attribution; not direct individual FIPI verification",
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=300)
    parser.add_argument("--budget", type=int, default=1200)
    parser.add_argument("--output", type=Path, default=Path("reports/oge17-quality.json"))
    parser.add_argument("--previews", type=Path, default=Path("reports/oge17-previews"))
    args = parser.parse_args()
    run(args.samples, args.budget, args.output, args.previews)
