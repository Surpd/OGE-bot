"""Paired bootstrap of aggregate ratio differences, clustered by seed (all profiles)."""

import csv
import gzip
import random
from collections import defaultdict

from simulate import HERE
from summarize import RATIOS, write_csv


def main():
    path = HERE / "results" / "runs.csv"
    open_rows = (
        path.open if path.exists() else lambda mode: gzip.open(path.with_suffix(".csv.gz"), mode)
    )
    fields = [
        "gap_precision",
        "gap_recall",
        "false_closure_rate",
        "delayed_probe",
        "fresh_accuracy",
    ]
    counts = defaultdict(lambda: [0.0] * 10)
    with open_rows("rt") as data:
        for r in csv.DictReader(data):
            if r["setting"] != "base" or r["day"] != "90":
                continue
            v = counts[r["policy"], int(r["seed"])]
            for i, key in enumerate(fields):
                a, b = RATIOS[key]
                v[2 * i] += float(r[a])
                v[2 * i + 1] += float(r[b])
    seeds = sorted(s for a, s in counts if a == "rules")
    rng = random.Random(10409)
    result = []
    for p in ("weighted", "bkt"):
        for i, metric in enumerate(fields):
            pairs = [
                (
                    counts[p, s][2 * i],
                    counts[p, s][2 * i + 1],
                    counts["rules", s][2 * i],
                    counts["rules", s][2 * i + 1],
                )
                for s in seeds
            ]

            def delta(tuples):
                a, b, c, d = map(sum, zip(*tuples, strict=False))
                return 100 * (a / b - c / d)

            diffs = sorted(delta(rng.choices(pairs, k=len(pairs))) for _ in range(2000))
            result.append(
                dict(
                    policy=p,
                    metric=metric,
                    difference_pp=delta(pairs),
                    low_pp=diffs[49],
                    high_pp=diffs[1949],
                )
            )
    write_csv(HERE / "results" / "ratio_intervals.csv", result)
    print(*result, sep="\n")


if __name__ == "__main__":
    main()
