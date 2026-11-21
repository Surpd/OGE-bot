"""Compare committed issue traces from random_training_acceptance (use the same seeds)."""

import argparse
import json
from collections import Counter
from itertools import groupby
from pathlib import Path
from statistics import median

from app.math.first_rotation import construction, topics


def longest(items):
    return max((sum(1 for _ in group) for _, group in groupby(items)), default=0)


def summarize(rows):
    families = [row[0] for row in rows]
    prints = [row[1] for row in rows]
    narrow = [construction(f) for f in families]
    broad = [topics()[f] for f in families]
    streak = longest(narrow)
    end = next(i for i in range(streak, len(rows) + 1) if len(set(narrow[i - streak : i])) == 1)
    return {
        "issued": len(rows),
        "fingerprint_repeats": len(rows) - len(set(prints)),
        "fingerprint_in_previous_5": sum(
            fp in prints[max(0, i - 5) : i] for i, fp in enumerate(prints)
        ),
        "same_narrow_adjacent": sum(a == b for a, b in zip(narrow, narrow[1:], strict=False)),
        "narrow_in_previous_5": sum(op in narrow[max(0, i - 5) : i] for i, op in enumerate(narrow)),
        "longest_narrow": streak,
        "longest_broad": longest(broad),
        "worst_narrow_context": families[max(0, end - streak - 1) : end + 1],
        "first_issue_of_streak": end - streak + 1,
        "family_counts": dict(sorted(Counter(families).items())),
        "narrow_count": len(set(narrow)),
        "broad_count": len(set(broad)),
        "median_ms": round(median(row[2] for row in rows), 1),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("before", "after", "output"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    before, after = (json.loads(path.read_text()) for path in (args.before, args.after))
    assert before.keys() == after.keys()
    result = {k: {"before": summarize(before[k]), "after": summarize(after[k])} for k in after}
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
