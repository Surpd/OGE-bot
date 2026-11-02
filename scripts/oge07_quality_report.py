"""Run an independent OGE-7 release sample and write its JSON evidence report."""

from __future__ import annotations

import json
from pathlib import Path

from app.math.numbers import FAMILIES as TEXT_FAMILIES
from app.math.numbers import audit_condition, audit_explanation, generate
from app.math.oge07_graph import (
    GRAPH_SOURCES,
    audit_graph_explanation,
    audit_graph_problem,
    generate_graph_problem,
)
from app.math.oge07_scheduler import ENABLED_FAMILIES
from app.math.oge07_validation import validate_task7_snapshot

SEEDS = 300
ROOT = Path(__file__).resolve().parents[1]


def family_report(family_id: str) -> dict[str, object]:
    fingerprints: set[str] = set()
    failures: list[dict[str, object]] = []
    for seed in range(SEEDS):
        if seed % 50 == 0:
            print(f"{family_id}: seed {seed + 1}/{SEEDS}", flush=True)
        if family_id in TEXT_FAMILIES:
            problem = generate(family_id, seed)
            snapshot = problem.to_snapshot()
            valid = audit_condition(
                family_id, problem.condition, problem.options, problem.correct_option_index
            ) and audit_explanation(problem) and validate_task7_snapshot(snapshot)
        else:
            task = generate_graph_problem(family_id, seed)
            snapshot = task.to_snapshot()
            valid = (
                audit_graph_problem(task)
                and audit_graph_explanation(task)
                and validate_task7_snapshot(snapshot)
            )
        fingerprint = snapshot["fingerprint"]
        if not valid:
            failures.append(
                {"seed": seed, "reason": "independent oracle/snapshot validation failed"}
            )
        fingerprints.add(str(fingerprint))
    return {
        "enabled": family_id in ENABLED_FAMILIES,
        "seeds_checked": SEEDS,
        "unique_fingerprints": len(fingerprints),
        "oracle_failures": failures,
        "passed": not failures and len(fingerprints) >= 200,
    }


def main() -> None:
    families = (*TEXT_FAMILIES, *GRAPH_SOURCES)
    report = {
        "task_number": 7,
        "sample_size_per_family": SEEDS,
        "enabled_families": list(ENABLED_FAMILIES),
        "families": {family: family_report(family) for family in families},
    }
    print("Writing OGE-7 quality report", flush=True)
    destination = ROOT / "reports" / "oge07-quality.json"
    destination.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(destination)
    if any(not item["passed"] for item in report["families"].values()):
        raise SystemExit("OGE-7 quality gate failed")


if __name__ == "__main__":
    main()
