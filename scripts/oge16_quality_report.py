"""Reproducible closed-family gates. Run from repository root; never enables families."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.math.oge16_circles import (  # noqa: E402
    CAPACITY,
    FAMILIES,
    GENERATOR_VERSION,
    POLICY,
    content,
    from_snapshot,
    generate,
    parameters,
)
from app.math.oge16_oracle import audit, solve_visible  # noqa: E402


def report(samples: int) -> dict[str, Any]:
    rows = []
    for family in FAMILIES:
        answers: list[str] = []
        duplicates: Counter[str] = Counter()
        for seed in range(samples):
            problem = generate(family, seed)
            snapshot = problem.to_snapshot()
            assert audit(snapshot) == POLICY.parse(snapshot["correct_answer"])
            if seed < 3:
                assert from_snapshot(snapshot).png == problem.png
            answers.append(snapshot["correct_answer"])
            duplicates[problem.fingerprint] += 1
        # Acceptance budget counts mathematical inputs only, never raster/layout variation.
        unique: set[str] = set()
        for seed in range(1200):
            p = parameters(family, seed)
            text, _, _, result, scene = content(family, p)
            assert solve_visible(family, text, scene.to_dict()) == result
            identity = json.dumps([family, [str(v) for v in p]])
            unique.add(hashlib.sha256(identity.encode()).hexdigest())
        capacity = CAPACITY[family]
        threshold = min(200, capacity)
        assert len(unique) >= threshold
        row = {
            "family_id": family,
            "status": "implemented_closed",
            "public_enabled": False,
            "full_png_and_oracle_samples": samples,
            "failures": 0,
            "sample_unique": len(duplicates),
            "sample_duplicate_count": samples - len(duplicates),
            "acceptance_attempts": 1200,
            "acceptance_unique": len(unique),
            "mathematical_capacity": capacity,
            "acceptance_target": threshold,
            "finite_capacity_exception": capacity < 200,
            "exception_reason": (
                "Integer angles in documented safe interval; no cosmetic novelty. "
                "Bounded exhaustion and no-fallback preference tested; publication disabled."
                if capacity < 200
                else None
            ),
            "answer_min": min(float(a.replace(",", ".")) for a in answers),
            "answer_max": max(float(a.replace(",", ".")) for a in answers),
            "max_answer_decimal_places": max(
                len(a.split(",")[1]) if "," in a else 0 for a in answers
            ),
            "mobile_sizes": [360, 390, 430],
        }
        rows.append(row)
        print(
            f"{family}: {samples} PNG/oracle; {len(unique)}/{capacity} unique in 1200", flush=True
        )
    return {
        "generator_version": GENERATOR_VERSION,
        "public_enabled": [],
        "families": rows,
        "scope": "six candidates, not whole-bank coverage; no Telegram or DB integration",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=300)
    parser.add_argument("--output", type=Path, default=Path("reports/oge16-quality.json"))
    args = parser.parse_args()
    if not 1 <= args.samples <= 300:
        parser.error("samples must be in 1..300")
    result = report(args.samples)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
