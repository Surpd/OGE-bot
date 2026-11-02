from __future__ import annotations

import random

from app.math.oge11 import ENABLED_FAMILIES, FAMILIES, generate, verify

MAX_CANDIDATES = 32
SEEDS_PER_FAMILY = 6


def _deck(seed: int, last_family: str | None, families: tuple[str, ...]) -> list[str]:
    rng = random.Random(f"oge11-deck:{seed}")
    deck = list(families)
    rng.shuffle(deck)
    if len(deck) > 1 and deck[0] == last_family:
        deck[0], deck[1] = deck[1], deck[0]
    return deck


def build_task11_candidate_batch(
    state: dict[str, object],
    seed: int,
    *,
    enabled_families: tuple[str, ...] = ENABLED_FAMILIES,
    allow_disabled_for_quality: bool = False,
) -> list[dict[str, object]]:
    """Return snapshot candidates; learner sessions only use approved runtime families."""
    families = FAMILIES if allow_disabled_for_quality else enabled_families
    if not families:
        return []
    stored = state.get("family_queue")
    if isinstance(stored, list) and stored and all(item in families for item in stored):
        queue = list(stored)
    else:
        last = state.get("last_family_id")
        queue = _deck(seed, last if isinstance(last, str) else None, families)
    recent_value = state.get("recent_fingerprints", [])
    seen = (
        {item for item in recent_value if isinstance(item, str)}
        if isinstance(recent_value, list)
        else set()
    )
    rng = random.Random(f"oge11-candidates:{seed}")
    candidates: list[dict[str, object]] = []
    attempts = 0
    for index, family_id in enumerate(queue):
        for _ in range(SEEDS_PER_FAMILY):
            attempts += 1
            problem = generate(family_id, rng.randrange(2**63))
            valid, reason = verify(problem)
            if not valid:
                raise ValueError(f"task-11 quality gate failed for {family_id}: {reason}")
            if problem.fingerprint in seen:
                continue
            seen.add(problem.fingerprint)
            snapshot = problem.to_snapshot()
            snapshot.update(
                {
                    "selection_attempts": attempts,
                    "_family_queue_after": queue[index + 1 :],
                    "_last_family_after": family_id,
                }
            )
            candidates.append(snapshot)
            if len(candidates) >= MAX_CANDIDATES:
                return candidates
    return candidates
