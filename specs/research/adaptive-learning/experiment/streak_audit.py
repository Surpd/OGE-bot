"""Exact streak probabilities and optional replay against the unmodified PR 110 reducer."""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path


def at_least_one_streak(p: float, opportunities: int, threshold: int = 3) -> float:
    """Transient probabilities for terminal run lengths before the first streak."""
    alive = [1.0] + [0.0] * (threshold - 1)
    for _ in range(opportunities):
        alive = [sum(alive) * (1 - p)] + [value * p for value in alive[:-1]]
    return 1 - sum(alive)


def replay(engine_path: Path) -> None:
    spec = importlib.util.spec_from_file_location("pinned_reducer", engine_path)
    assert spec and spec.loader
    engine = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = engine
    spec.loader.exec_module(engine)
    assert engine.CURRENT.version == 2
    sequences = {
        "two errors on one item": [("x", "wrong", 1, False, True), ("x", "wrong", 2, False, False)],
        "three distinct same-day first attempts": [
            (str(i), "correct", 1, False, True) for i in range(3)
        ],
        "viewed or unknown help": [
            (str(i), "correct", 1, help_flag, True)
            for i, help_flag in enumerate([True, None, True])
        ],
    }
    for label, observations in sequences.items():
        state = engine.State()
        trace = []
        for second, (key, result, attempt, assisted, fresh) in enumerate(observations):
            evidence = engine.Evidence(key, key, second, result, attempt, assisted, fresh)
            state, reason = engine.apply(state, evidence)
            trace.append((str(state.stage), reason))
        print(label, trace)
    assert at_least_one_streak(0.5, 3) == 0.125


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reducer", type=Path)
    args = parser.parse_args()
    if args.reducer:
        replay(args.reducer)
    print("Fixed independent success probability; chances of observing any streak of three.")
    for p in (1 / 3, 0.50, 0.80):
        print(f"{p:.4f}", *(f"{at_least_one_streak(p, n):.4f}" for n in (3, 10, 30)))
