from __future__ import annotations

import random
from typing import cast
from uuid import uuid4

from app.math.generator import generate
from app.math.registry import GENERATOR_SPECS, SPEC_BY_ID

FINGERPRINT_HISTORY_LIMIT = 30
MAX_FAMILY_QUEUE_CANDIDATES = 60
SEEDS_PER_FAMILY_SLOT = 4


def _weighted_unique_order(seed: int) -> list[str]:
    rng = random.Random(f"oge6-family-cycle:{seed}")
    return sorted(
        SPEC_BY_ID,
        key=lambda family_id: rng.random() ** (1 / SPEC_BY_ID[family_id].selection_weight),
        reverse=True,
    )


def build_family_deck(seed: int) -> list[str]:
    """Put every enabled family once before catalog-weighted extra cards."""
    core = _weighted_unique_order(seed)
    extras = [spec.family_id for spec in GENERATOR_SPECS for _ in range(spec.selection_weight - 1)]
    random.Random(f"oge6-family-extras:{seed}").shuffle(extras)
    if extras and extras[0] == core[-1]:
        different = next(
            (index for index, family_id in enumerate(extras) if family_id != core[-1]),
            None,
        )
        if different is not None:
            extras[0], extras[different] = extras[different], extras[0]
    return [*core, *extras]


def build_candidate_batch(state: dict[str, object], seed: int) -> list[dict[str, object]]:
    stored_queue = state.get("family_queue")
    if (
        isinstance(stored_queue, list)
        and stored_queue
        and all(isinstance(item, str) and item in SPEC_BY_ID for item in stored_queue)
    ):
        family_queue = cast(list[str], stored_queue)
    else:
        family_queue = build_family_deck(seed)

    stored_recent = state.get("recent_fingerprints", [])
    recent = (
        {item for item in stored_recent if isinstance(item, str)}
        if isinstance(stored_recent, list)
        else set()
    )
    rng = random.Random(f"oge6-task-candidates:{seed}")
    candidates: list[dict[str, object]] = []
    fingerprints = set(recent)
    selection_attempts = 0
    for slot, family_id in enumerate(family_queue):
        for _ in range(SEEDS_PER_FAMILY_SLOT):
            selection_attempts += 1
            try:
                problem = generate(family_id, rng.randrange(2**63))
            except RuntimeError:
                # A family that exhausts its own bounded construction retries is
                # skipped for this issuance; later families can still produce a task.
                continue
            if problem.fingerprint in fingerprints:
                continue
            fingerprints.add(problem.fingerprint)
            snapshot = problem.to_snapshot()
            snapshot.update(
                {
                    "problem_id": str(uuid4()),
                    "selection_attempts": selection_attempts,
                    "_family_queue_after": family_queue[slot + 1 :],
                }
            )
            candidates.append(snapshot)
            if len(candidates) >= MAX_FAMILY_QUEUE_CANDIDATES:
                return candidates
    return candidates
