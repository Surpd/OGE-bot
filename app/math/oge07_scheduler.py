"""No-fallback candidate deck for OGE-7; only accepted families can be issued."""

from __future__ import annotations

import random

from app.math.numbers import ENABLED_FAMILIES as TEXT_ENABLED
from app.math.numbers import FAMILIES as TEXT_FAMILIES
from app.math.numbers import generate
from app.math.oge07_graph import GRAPH_SOURCES, generate_graph_problem

ALL_FAMILIES = (*TEXT_FAMILIES, *GRAPH_SOURCES)
ENABLED_FAMILIES: tuple[str, ...] = tuple(TEXT_ENABLED)
MAX_CANDIDATES = 54
SEEDS_PER_FAMILY = 6


def build_task7_candidate_batch(
    state: dict[str, object], seed: int, *, family_ids: tuple[str, ...] | None = None
) -> list[dict[str, object]]:
    """Build candidates in stable shuffled order; no fallback to held families."""
    selected = tuple(
        f for f in (family_ids if family_ids is not None else ENABLED_FAMILIES) if f in ALL_FAMILIES
    )
    if not selected:
        return []
    recent_raw = state.get("recent_fingerprints", [])
    recent = (
        {x for x in recent_raw if isinstance(x, str)} if isinstance(recent_raw, list) else set()
    )
    rng = random.Random(f"oge07-candidates:{seed}")
    families = list(selected)
    rng.shuffle(families)
    candidates: list[dict[str, object]] = []
    for family in families:
        for _ in range(SEEDS_PER_FAMILY):
            task_seed = rng.randrange(2**63)
            if family in TEXT_FAMILIES:
                snapshot = generate(family, task_seed).to_snapshot()
            else:
                snapshot = generate_graph_problem(family, task_seed).to_snapshot()
            fingerprint = snapshot.get("fingerprint")
            if not isinstance(fingerprint, str) or fingerprint in recent:
                continue
            recent.add(fingerprint)
            snapshot["selection_attempts"] = len(candidates) + 1
            snapshot["_family_queue_after"] = families[families.index(family) + 1 :]
            snapshot["_last_family_after"] = family
            candidates.append(snapshot)
            if len(candidates) >= MAX_CANDIDATES:
                return candidates
    return candidates
