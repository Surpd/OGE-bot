"""Finite exact pools: one raster per issued task and deliberate cycles on exhaustion."""

from __future__ import annotations

import hashlib
import json
import random
from functools import lru_cache

from app.math.oge16_circles import ENABLED_FAMILIES, FAMILIES, generate
from app.math.oge16_complete import SOURCE_VARIANTS, content, parameters


@lru_cache(maxsize=23)
def finite_pool(family: str) -> tuple[tuple[str, int], ...]:
    """Enumerate mathematical variants once, without rendering any PNG."""
    result: dict[str, int] = {}
    for seed in range(10 * len(SOURCE_VARIANTS[family[6:]])):
        text, _, _, _, _ = content(family, parameters(family, seed))
        fingerprint = hashlib.sha256(json.dumps([family, text]).encode()).hexdigest()
        result.setdefault(fingerprint, seed)
    return tuple(result.items())


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
    recent_value = state.get("recent_fingerprints", [])
    recent = set(recent_value) if isinstance(recent_value, list) else set()
    if not queue:
        return []
    # Every implemented pool is finite. Restart only after consuming its complete
    # mathematical pool; duplicates across source IDs do not count as novelty.
    family = queue[0]
    pool = finite_pool(family)
    available = [(fp, s) for fp, s in pool if fp not in recent]
    cycle = not available
    choices = available or list(pool)
    if cycle and len(choices) > 1 and isinstance(recent_value, list) and recent_value:
        choices = [(fp, s) for fp, s in choices if fp != recent_value[-1]]
    other = state.get("other_mode_fingerprints")
    if isinstance(other, list):
        choices = [pair for pair in choices if pair[0] not in other] or choices
    chosen_fp, base_seed = rng.choice(choices)
    period = 10 * len(SOURCE_VARIANTS[family[6:]])
    actual_seed = base_seed + period * rng.randrange((2**63 - period) // period)
    snapshot = generate(family, actual_seed).to_snapshot()
    assert snapshot["fingerprint"] == chosen_fp
    snapshot.update(
        {
            "_family_queue_after": queue[1:],
            "_last_family_after": family,
            "selection_attempts": 1,
        }
    )
    if cycle:
        snapshot["_finite_cycle_fingerprints"] = [fp for fp, _ in pool]
    return [snapshot]
