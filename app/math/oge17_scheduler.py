"""Recent-repeat protected family queue for OGE №17."""

from __future__ import annotations

import random

from app.math.oge17_generator import generate
from app.math.oge17_models import ENABLED_FAMILIES


def build_task17_candidate_batch(
    state: dict[str, object], seed: int, *, enabled_families: tuple[str, ...] | None = None
) -> list[dict[str, object]]:
    families = ENABLED_FAMILIES if enabled_families is None else enabled_families
    rng = random.Random(seed)
    queue = state.get("family_queue")
    queue = [f for f in queue if f in families] if isinstance(queue, list) else []
    if not queue:
        queue = list(families)
        rng.shuffle(queue)
        if len(queue) > 1 and queue[0] == state.get("last_family_id"):
            queue.reverse()
    recent = state.get("recent_fingerprints", [])
    attempts = 0
    for i, family in enumerate(queue):
        for _ in range(12):
            attempts += 1
            problem = generate(family, rng.randrange(2**63)).to_snapshot()
            if isinstance(recent, list) and problem["fingerprint"] in recent:
                continue
            problem.update(
                _family_queue_after=queue[i + 1 :],
                _last_family_after=family,
                selection_attempts=attempts,
            )
            return [problem]
    return []
