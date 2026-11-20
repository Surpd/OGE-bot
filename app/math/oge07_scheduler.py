"""No-fallback candidate deck for OGE-7; only accepted families can be issued."""

from __future__ import annotations

import random

from app.math.numbers import ENABLED_FAMILIES as TEXT_ENABLED
from app.math.numbers import FAMILIES as TEXT_FAMILIES
from app.math.numbers import generate
from app.math.oge07_graph import GRAPH_SOURCES, generate_graph_problem

ALL_FAMILIES = (*TEXT_FAMILIES, *GRAPH_SOURCES)
ENABLED_FAMILIES: tuple[str, ...] = (
    *TEXT_ENABLED,
    "OGE07-N01",
    "OGE07-N04",
)
MAX_CANDIDATES = 54
SEEDS_PER_FAMILY = 6


def build_task7_candidate_batch(
    state: dict[str, object],
    seed: int,
    *,
    family_ids: tuple[str, ...] | None = None,
    limit: int = MAX_CANDIDATES,
) -> list[dict[str, object]]:
    """Build candidates in stable shuffled order; no fallback to held families."""
    requested = family_ids if family_ids is not None else ENABLED_FAMILIES
    selected = tuple(f for f in requested if f in ENABLED_FAMILIES and f in ALL_FAMILIES)
    if not selected:
        return []
    recent_raw = state.get("recent_fingerprints", [])
    recent = (
        {x for x in recent_raw if isinstance(x, str)} if isinstance(recent_raw, list) else set()
    )
    rng = random.Random(f"oge07-candidates:{seed}")
    saved = state.get("family_queue")
    tail = (
        list(dict.fromkeys(f for f in saved if isinstance(f, str) and f in selected))
        if isinstance(saved, list)
        else []
    )
    fresh = [f for f in selected if f not in tail]
    rng.shuffle(fresh)
    if len(fresh) > 1 and fresh[0] == state.get("last_family_id"):
        fresh[0], fresh[1] = fresh[1], fresh[0]
    candidates: list[dict[str, object]] = []
    for deck in (tail, fresh):
        for index, family in enumerate(deck):
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
                snapshot["_family_queue_after"] = deck[index + 1 :]
                snapshot["_last_family_after"] = family
                candidates.append(snapshot)
                if len(candidates) >= limit:
                    return candidates
        if candidates:
            break
    return candidates
