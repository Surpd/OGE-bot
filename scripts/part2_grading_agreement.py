"""Offline comparison of externally obtained predictions with the pinned development set."""

import argparse
import json
from pathlib import Path
from typing import Any

from app.part2_grading import Assessment

CASES = Path(__file__).resolve().parents[1] / "tests/fixtures/part2-grading/cases.json"


def compare(predictions: dict[str, Any]) -> dict[str, int]:
    cases = json.loads(CASES.read_text())
    if set(predictions) != {r["id"] for r in cases}:
        raise ValueError("Supply one prediction for every case")
    exact = false_full = false_zero = 0
    for row in cases:
        actual = Assessment.model_validate(predictions[row["id"]])
        exact += actual.status == row["expected_status"] and actual.score == row["expected_score"]
        false_full += actual.score == 2 and row["expected_score"] == 0
        false_zero += actual.score == 0 and row["expected_score"] == 2
    return {
        "cases": len(cases),
        "exact": exact,
        "wrong_to_full": false_full,
        "full_to_zero": false_zero,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("predictions", type=Path)
    print(json.dumps(compare(json.loads(parser.parse_args().predictions.read_text()))))
