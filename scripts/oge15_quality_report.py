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
            "status": "implemented_closed", "public_enabled": False,
            "smoke_seeds": 50, "generations": 1200, "fingerprints": len(seen),
            "answer_distribution": dict(answers), "oracle_failures": 0,
            "snapshot_failures": 0, "png": "not_required_text_complete",
        }
        print(f"{family}: 1200 generated; {len(seen)} fingerprints")
    (ROOT / "reports/oge15-quality.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2) + "\n"
    )
    vectors = [
        {"family_id": family, "seed": seed, "snapshot": generate(family, seed).to_snapshot()}
        for family in FAMILIES for seed in (0, 42, 123)
    ]
    path = ROOT / "atlas/oge15_regression_vectors.json"
    if path.exists():
        assert json.loads(path.read_text()) == vectors, "Regression vectors changed"
    else:
        path.write_text(json.dumps(vectors, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    run()
