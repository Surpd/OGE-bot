from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.math.oge8 import ENABLED_FAMILIES, generate, verify_problem  # noqa: E402
from app.math.oge8 import _oracle_text  # noqa: E402


def build_report(samples: int) -> dict[str, object]:
    families: dict[str, object] = {}
    for family in ENABLED_FAMILIES:
        unique: set[str] = set()
        oracle_failures = 0
        rendered_mismatches = 0
        max_answer = 0
        for seed in range(samples):
            problem = generate(family, seed)
            unique.add(problem.fingerprint)
            oracle_failures += not verify_problem(problem)
            rendered_mismatches += _oracle_text(problem.condition) != problem.exact_value
            max_answer = max(max_answer, abs(problem.exact_value.numerator))
        attempts = samples
        while len(unique) < 200 and attempts < 1_200:
            problem = generate(family, attempts)
            unique.add(problem.fingerprint)
            oracle_failures += not verify_problem(problem)
            attempts += 1
        families[family] = {
            "sample_count": samples,
            "oracle_failures": oracle_failures,
            "rendered_mismatches": rendered_mismatches,
            "unique_fingerprints": len(unique),
            "attempts_to_200_unique": attempts if len(unique) >= 200 else None,
            "max_absolute_answer_numerator": max_answer,
            "acceptance_passed": oracle_failures == 0 and len(unique) >= 200 and attempts <= 1_200,
        }
    return {
        "exam_number": 8,
        "generator_version": "0.1.0",
        "level": "quick" if samples < 200 else "main",
        "enabled_family_count": len(ENABLED_FAMILIES),
        "families": families,
        "all_families_passed": all(
            bool(result["acceptance_passed"]) for result in families.values()
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--level", choices=("quick", "main"), default="main")
    parser.add_argument("--output", type=Path, default=Path("reports/oge8-quality.json"))
    args = parser.parse_args()
    report = build_report(40 if args.level == "quick" else 250)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["all_families_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
