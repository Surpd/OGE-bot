"""Replay 100 real candidate selections per number with deterministic scheduling seeds."""

import argparse
import json
import random
import statistics
import time
from collections import Counter
from itertools import groupby
from pathlib import Path

from app.bot.mixed_training import _builders
from app.math.first_rotation import rotate_tail
from app.persistence.mixed_training import _capture_scheduler_state


def measure(number, builder):
    rng = random.Random(20261121 + number)
    state = {}
    sequence = []
    fingerprints = []
    timings = []
    for _ in range(100):
        current = state.get("generator_states", {}).get(str(number), {})
        start = time.perf_counter()
        current = dict(current)
        rotate_tail(number, current, None)
        candidates = builder(current, rng.getrandbits(63))
        timings.append((time.perf_counter() - start) * 1000)
        if not candidates:
            continue
        snapshot = candidates[0]
        _capture_scheduler_state(state, number, snapshot)
        sequence.append(snapshot["family_id"])
        fingerprints.append(snapshot["fingerprint"])
    return {
        "issued": len(sequence),
        "families": dict(sorted(Counter(sequence).items())),
        "longest_same_family": max(
            (sum(1 for _ in group) for _, group in groupby(sequence)), default=0
        ),
        "repeated_fingerprints": len(fingerprints) - len(set(fingerprints)),
        "median_ms": round(statistics.median(timings), 1),
        "sequence": sequence,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = {n: measure(n, builder) for n, builder in _builders().items()}
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
