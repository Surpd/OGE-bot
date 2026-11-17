"""Bounded closed-family queue; never count cosmetic changes as novelty."""

import random

from app.math.oge18 import ENABLED_FAMILIES, GENERATOR_VERSION_V2, NEW_FAMILIES, generate
from app.math.oge18_render import VERSION_V3


def build_task18_candidate_batch(
    state: dict[str, object], seed: int, *, enabled_families: tuple[str, ...] | None = None
) -> list[dict[str, object]]:
    families = ENABLED_FAMILIES if enabled_families is None else enabled_families
    stored = state.get("family_queue")
    queue = [f for f in stored if f in families] if isinstance(stored, list) else []
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
            version = GENERATOR_VERSION_V2 if family in NEW_FAMILIES else None
            problem = (
                generate(
                    family,
                    rng.randrange(2**63),
                    version,
                    renderer_version=VERSION_V3,
                )
                if version is not None
                else generate(
                    family,
                    rng.randrange(2**63),
                    renderer_version=VERSION_V3,
                )
            )
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
