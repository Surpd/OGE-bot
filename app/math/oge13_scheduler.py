from __future__ import annotations

import random

from app.math.inequalities import (
    ENABLED_FAMILIES,
    GENERATOR_VERSION,
    generate,
)

MAX_CANDIDATES = 54
SEEDS_PER_FAMILY = 6


def _deck(seed: int, last_family: str | None = None) -> list[str]:
    rng = random.Random(f"oge13-deck:{seed}")
    deck = list(ENABLED_FAMILIES)
    rng.shuffle(deck)
    if len(deck) > 1 and deck[0] == last_family:
        deck[0], deck[1] = deck[1], deck[0]
    return deck


def build_task13_candidate_batch(state: dict[str, object], seed: int) -> list[dict[str, object]]:
    enabled = tuple(ENABLED_FAMILIES)
    stored = state.get("family_queue")
    if (
        isinstance(stored, list)
        and stored
        and all(isinstance(item, str) and item in enabled for item in stored)
    ):
        queue = list(stored)
    else:
        last = state.get("last_family_id")
        queue = _deck(seed, last if isinstance(last, str) else None)

    recent_value = state.get("recent_fingerprints", [])
    seen = (
        {item for item in recent_value if isinstance(item, str)}
        if isinstance(recent_value, list)
        else set()
    )
    rng = random.Random(f"oge13-candidates:{seed}")
    candidates: list[dict[str, object]] = []
    for index, family_id in enumerate(queue):
        for _ in range(SEEDS_PER_FAMILY):
            try:
                problem = generate(
                    family_id, rng.randrange(2**63), generator_version=GENERATOR_VERSION
                )
            except RuntimeError:
                continue
            fingerprint = str(getattr(problem, "fingerprint", ""))
            if not fingerprint or fingerprint in seen:
                continue
            seen.add(fingerprint)
            snapshot = problem.to_snapshot()
            if not isinstance(snapshot, dict):
                continue
            snapshot.update(
                {
                    "selection_attempts": len(candidates) + 1,
                    "_family_queue_after": queue[index + 1 :],
                    "_last_family_after": family_id,
                }
            )
            candidates.append(snapshot)
            if len(candidates) >= MAX_CANDIDATES:
                return candidates
    return candidates
