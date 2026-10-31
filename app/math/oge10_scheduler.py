from __future__ import annotations

import random
from uuid import uuid4

from app.math.probability import ENABLED_FAMILIES, generate

MAX_CANDIDATES = 36
SEEDS_PER_FAMILY = 3


def _deck(seed: int, last_family: str | None) -> list[str]:
    rng = random.Random(f"oge10-deck:{seed}")
    deck = list(ENABLED_FAMILIES)
    rng.shuffle(deck)
    if last_family is not None and len(deck) > 1 and deck[0] == last_family:
        deck[0], deck[1] = deck[1], deck[0]
    return deck


def build_task10_candidate_batch(state: dict[str, object], seed: int) -> list[dict[str, object]]:
    stored = state.get("family_queue")
    queue = (
        [item for item in stored if isinstance(item, str) and item in ENABLED_FAMILIES]
        if isinstance(stored, list)
        else []
    )
    if not queue:
        last = state.get("last_family_id")
        queue = _deck(seed, last if isinstance(last, str) else None)

    recent_value = state.get("recent_fingerprints", [])
    recent = (
        {item for item in recent_value if isinstance(item, str)}
        if isinstance(recent_value, list)
        else set()
    )
    rng = random.Random(f"oge10-candidates:{seed}")
    candidates: list[dict[str, object]] = []
    attempts = 0
    for index, family_id in enumerate(queue):
        for _ in range(SEEDS_PER_FAMILY):
            attempts += 1
            try:
                problem = generate(family_id, rng.randrange(2**63))
            except RuntimeError:
                continue
            if problem.fingerprint in recent:
                continue
            snapshot = problem.to_snapshot()
            snapshot.update(
                {
                    "problem_id": str(uuid4()),
                    "selection_attempts": attempts,
                    "_family_queue_after": queue[index + 1 :],
                    "_last_family_after": family_id,
                }
            )
            candidates.append(snapshot)
            if len(candidates) >= MAX_CANDIDATES:
                return candidates
    return candidates
