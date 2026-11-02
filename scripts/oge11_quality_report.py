from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.math.oge11 import (  # noqa: E402
    FAMILIES,
    REFERENCE_IDS,
    RENDERER_VERSION,
    all_matching_codes,
    generate,
    verify,
)

DEFAULT_SAMPLES = 300
MAX_UNIQUE_ATTEMPTS = 1200


def build_report(samples: int, unique_target: int) -> dict[str, object]:
    if samples < 30 or samples > MAX_UNIQUE_ATTEMPTS:
        raise ValueError("samples must be between 30 and 1200")
    result: dict[str, object] = {
        "task": 11,
        "generator_version": "0.1.0",
        "renderer_version": RENDERER_VERSION,
        "quality_level": "main" if samples >= 200 else "fast",
        "source_gate": "blocked_pending_independent_source_image_audit",
        "runtime_enabled_families": [],
        "image_format": (
            "PNG; 700x1530; three vertically stacked independent graph panels; "
            "exact Fraction viewport [-5,5]x[-5,5]"
        ),
        "image_integrity": (
            "SHA-256 of immutable PNG bytes stored with base64 PNG and semantic graph snapshot"
        ),
        "visible_panel_label_contract": {
            "OGE11-F01": ["1", "2", "3"],
            "OGE11-F02": ["А", "Б", "В"],
            "OGE11-F03": ["А", "Б", "В"],
            "OGE11-F04": ["А", "Б", "В"],
            "OGE11-F05": ["1", "2", "3"],
            "OGE11-F06": ["1", "2", "3"],
            "OGE11-F07": ["1", "2", "3"],
            "OGE11-F08": ["1", "2", "3"],
        },
        "families": {},
    }
    families: dict[str, object] = {}
    for family_id in FAMILIES:
        started = time.perf_counter()
        fingerprints: set[str] = set()
        codes: set[str] = set()
        verified = 0
        failures: dict[str, int] = {}
        attempts = 0
        candidate_attempts = 0
        while attempts < MAX_UNIQUE_ATTEMPTS and (
            attempts < samples or len(fingerprints) < unique_target
        ):
            problem = generate(family_id, attempts + 20261102)
            attempts += 1
            candidate_attempts += problem.generation_attempts
            ok, reason = verify(problem)
            if ok:
                verified += 1
                fingerprints.add(problem.fingerprint)
                codes.add(problem.correct_answer)
            else:
                failures[reason] = failures.get(reason, 0) + 1
        status = (
            "pass"
            if len(fingerprints) >= unique_target and codes == all_matching_codes()
            else "fail"
        )
        families[family_id] = {
            "status": status,
            "research_status": "enabled_candidate" if family_id != "OGE11-F11" else "blocked",
            "runtime_enabled": False,
            "source_ids": list(REFERENCE_IDS[family_id]),
            "source_image_independently_verified": False,
            "attempts": attempts,
            "candidate_construction_attempts": candidate_attempts,
            "rejected_constructions": candidate_attempts - attempts,
            "verified": verified,
            "unique_fingerprints": len(fingerprints),
            "correct_code_permutations": sorted(codes),
            "oracle_failures": failures,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
        }
    result["families"] = families
    result["all_families_pass"] = all(
        record["status"] == "pass"
        and record["candidate_construction_attempts"] <= MAX_UNIQUE_ATTEMPTS  # type: ignore[index]
        for record in families.values()
    )
    result["important_limit"] = (
        "Mathematical generation and self-render audits only. Catalog graph SVGs "
        "were not independently viewable, so every student runtime flag remains off."
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=DEFAULT_SAMPLES)
    parser.add_argument("--unique-target", type=int, default=200)
    parser.add_argument("--output", type=Path, default=Path("reports/oge11-quality.json"))
    args = parser.parse_args()
    report = build_report(args.samples, args.unique_target)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {"all_families_pass": report["all_families_pass"], "output": str(args.output)},
            ensure_ascii=False,
        )
    )
    if not report["all_families_pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
