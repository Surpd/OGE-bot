"""Bounded NumericTraining candidate adapter; public issuance stays disabled."""

import random

from app.math.oge16_circles import ENABLED_FAMILIES, FAMILIES, generate


def build_task16_candidate_batch(
    state: dict[str, object], seed: int, *, enabled_families: tuple[str, ...] | None = None
) -> list[dict[str, object]]:
    families = ENABLED_FAMILIES if enabled_families is None else enabled_families
    if any(f not in FAMILIES for f in families):
        raise ValueError("Unimplemented circle family")
    preference = state.get("selected_family_id")
    if preference is not None:
        families = (preference,) if isinstance(preference, str) and preference in families else ()
    stored = state.get("family_queue")
    queue = (
        list(dict.fromkeys(f for f in stored if f in families)) if isinstance(stored, list) else []
    )
    rng = random.Random(seed)
    if not queue:
        queue = list(families)
        rng.shuffle(queue)
        if len(queue) > 1 and queue[0] == state.get("last_family_id"):
            queue.reverse()
    recent = state.get("recent_fingerprints", [])
    attempts = 0
    for index, family in enumerate(queue):
        for _ in range(12):
            attempts += 1
            problem = generate(family, rng.randrange(2**63))
            if isinstance(recent, list) and problem.fingerprint in recent:
                continue
            snapshot = problem.to_snapshot()
            snapshot.update(
                {
                    "_family_queue_after": queue[index + 1 :],
                    "_last_family_after": family,
                    "selection_attempts": attempts,
                }
            )
            return [snapshot]
    return []
