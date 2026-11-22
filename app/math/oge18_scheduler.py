"""Bounded closed-family queue; never count cosmetic changes as novelty."""

import random
from functools import lru_cache

from app.math.oge18 import (
    ENABLED_FAMILIES,
    GENERATOR_VERSION,
    GENERATOR_VERSION_V2,
    NEW_FAMILIES,
    _model_for_seed,
    fingerprint,
    generate,
)
from app.math.oge18_render import VERSION_V3

# Observed shapes have an exact finite parameter space. Larger polygon and
# midline families keep the ordinary bounded random search.
CAPACITIES = {
    "OGE18-D05": 3,
    "OGE18-H01": 5,
    "OGE18-L01": 6,
    "OGE18-L02": 21,
    "OGE18-A05": 6,
    "OGE18-C01": 5,
}


@lru_cache(maxsize=len(CAPACITIES))
def _shapes(family: str) -> frozenset[str]:
    found = set()
    for seed in range(1200):
        points, _ = _model_for_seed(family, seed, GENERATOR_VERSION_V2)
        found.add(fingerprint(family, points))
        if len(found) == CAPACITIES[family]:
            return frozenset(found)
    raise ValueError(f"Finite parameter space disagrees with the registry: {family}")


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
    deferred = []
    for index, family in enumerate(queue):
        recent_list = recent if isinstance(recent, list) else []
        eligible = None
        reset_pool = None
        if family in CAPACITIES:
            pool = _shapes(family)
            eligible = pool.difference(recent_list)
            if not eligible:
                if index + 1 < len(queue):
                    deferred.append(family)
                    continue
                local = state.get("local_fingerprints", recent_list)
                current = [fp for fp in local if fp in pool] if isinstance(local, list) else []
                eligible = pool.difference(current)
                if not eligible:
                    reset_pool = sorted(pool)
                    eligible = pool
                # Use the least recently seen eligible shape after exhaustion.
                history = [fp for fp in reversed(recent_list) if fp in eligible]
                if history:
                    eligible = frozenset([list(dict.fromkeys(history))[-1]])
        for _ in range(600 if eligible else 12):
            attempts += 1
            version = GENERATOR_VERSION_V2 if family in NEW_FAMILIES else GENERATOR_VERSION
            candidate_seed = rng.randrange(2**63)
            points, _ = _model_for_seed(family, candidate_seed, version)
            fp = fingerprint(family, points)
            if (fp not in eligible if eligible is not None else fp in recent_list):
                continue
            snapshot = generate(
                family, candidate_seed, version, renderer_version=VERSION_V3
            ).to_snapshot()
            snapshot.update(
                {
                    "_family_queue_after": [*queue[index + 1 :], *deferred],
                    "_last_family_after": family,
                    "selection_attempts": attempts,
                }
            )
            if reset_pool:
                snapshot["_finite_cycle_fingerprints"] = reset_pool
            return [snapshot]
    return []
