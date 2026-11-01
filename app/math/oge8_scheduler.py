from __future__ import annotations

import random

from app.math.oge8 import (
    ENABLED_FAMILIES,
    MAX_CANDIDATES,
    SEEDS_PER_FAMILY,
    generate,
    verify_problem,
)


def build_task8_candidate_batch(state: dict[str, object], seed: int) -> list[dict[str, object]]:
    stored = state.get("family_queue")
    if isinstance(stored, list) and stored and all(
        isinstance(item, str) and item in ENABLED_FAMILIES for item in stored
    ):
        queue = list(stored)
    else:
        queue = list(ENABLED_FAMILIES)
        random.Random(f"oge8-deck:{seed}").shuffle(queue)
        previous = state.get("last_family_id")
        if len(queue) > 1 and queue[0] == previous:
            queue[0], queue[1] = queue[1], queue[0]

    recent_value = state.get("recent_fingerprints", [])
    seen = (
        {item for item in recent_value if isinstance(item, str)}
        if isinstance(recent_value, list)
        else set()
    )
    rng = random.Random(f"oge8-candidates:{seed}")
    candidates: list[dict[str, object]] = []
    attempts = 0
    for index, family_id in enumerate(queue):
        for _ in range(SEEDS_PER_FAMILY):
            attempts += 1
            try:
                problem = generate(family_id, rng.randrange(2**63))
            except (ArithmeticError, RuntimeError, ValueError):
                continue
            if not verify_problem(problem) or problem.fingerprint in seen:
                continue
            seen.add(problem.fingerprint)
            snapshot = problem.to_snapshot()
            snapshot.update({
                "selection_attempts": attempts,
                "_family_queue_after": queue[index + 1 :],
                "_last_family_after": family_id,
            })
            candidates.append(snapshot)
            if len(candidates) >= MAX_CANDIDATES:
                return candidates
    return candidates
