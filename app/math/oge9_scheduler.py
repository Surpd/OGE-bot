from __future__ import annotations

import random
from typing import cast
from uuid import uuid4

from app.math.equations import ENABLED_FAMILIES, generate_equation

MAX_CANDIDATES = 48
SEEDS_PER_FAMILY = 4
RECENT_FINGERPRINTS = 30


def _deck(seed: int, last_family: str | None = None) -> list[str]:
    rng = random.Random(f"oge9-deck:{seed}")
    linear = [family for family in ENABLED_FAMILIES if family.startswith("OGE09-L")]
    quadratic = [family for family in ENABLED_FAMILIES if family.startswith("OGE09-K")]
    # Eight cards per cycle: four linear and four quadratic. Since K2/K3/K6
    # currently form a group of three, one is repeated, chosen afresh per cycle.
    quadratic.append(rng.choice(quadratic))
    rng.shuffle(linear)
    rng.shuffle(quadratic)
    for cards in (linear, quadratic):
        for index in range(1, len(cards)):
            if cards[index] == cards[index - 1]:
                swap = next(
                    (pos for pos in range(index + 1, len(cards)) if cards[pos] != cards[index - 1]),
                    None,
                )
                if swap is not None:
                    cards[index], cards[swap] = cards[swap], cards[index]
    start_linear = bool(rng.getrandbits(1))
    deck = [
        card
        for index in range(4)
        for card in (
            (linear[index], quadratic[index]) if start_linear else (quadratic[index], linear[index])
        )
    ]
    if last_family is not None and deck[0] == last_family:
        swap = next((index for index, family in enumerate(deck) if family != last_family), None)
        if swap is not None:
            deck[0], deck[swap] = deck[swap], deck[0]
    return deck


def build_task9_candidate_batch(state: dict[str, object], seed: int) -> list[dict[str, object]]:
    stored = state.get("family_queue")
    queue = (
        cast(list[str], stored)
        if isinstance(stored, list)
        and stored
        and all(isinstance(item, str) and item in ENABLED_FAMILIES for item in stored)
        else _deck(seed, str(state.get("last_family_id", "")) or None)
    )
    stored_recent = state.get("recent_fingerprints", [])
    recent = (
        {item for item in stored_recent if isinstance(item, str)}
        if isinstance(stored_recent, list)
        else set()
    )
    seen = set(recent)
    rng = random.Random(f"oge9-candidates:{seed}")
    result: list[dict[str, object]] = []
    attempts = 0
    for index, family_id in enumerate(queue):
        for _ in range(SEEDS_PER_FAMILY):
            attempts += 1
            problem = generate_equation(family_id, rng.randrange(2**63))
            if problem.fingerprint in seen:
                continue
            seen.add(problem.fingerprint)
            snapshot = problem.to_snapshot()
            snapshot.update(
                {
                    "problem_id": str(uuid4()),
                    "selection_attempts": attempts,
                    "_family_queue_after": queue[index + 1 :],
                }
            )
            result.append(snapshot)
            if len(result) >= MAX_CANDIDATES:
                return result
    return result
