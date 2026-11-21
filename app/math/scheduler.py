from __future__ import annotations

import random
from typing import cast
from uuid import uuid4

from app.math.generator import generate, training_rejection
from app.math.registry import SPEC_BY_ID

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


def build_family_deck(seed: int, previous: object = None) -> list[str]:
    """Rotate all distinct constructions once; weights only influence their order."""
    deck = _weighted_unique_order(seed)
    if len(deck) > 1 and deck[0] == previous:
        deck[0], deck[1] = deck[1], deck[0]
    return deck


def build_candidate_batch(state: dict[str, object], seed: int) -> list[dict[str, object]]:
    selected = state.get("selected_family_id")
    if isinstance(selected, str):
        return _candidates_from_queue(state, seed, [selected]) if selected in SPEC_BY_ID else []
    stored_queue = state.get("family_queue")
    if (
        isinstance(stored_queue, list)
        and stored_queue
        and all(isinstance(item, str) and item in SPEC_BY_ID for item in stored_queue)
    ):
        family_queue = list(dict.fromkeys(cast(list[str], stored_queue)))
        if family_queue[0] == state.get("last_family_id"):
            family_queue = family_queue[1:]
        if not family_queue:
            family_queue = build_family_deck(seed, state.get("last_family_id"))
    else:
        family_queue = build_family_deck(seed, state.get("last_family_id"))

    candidates = _candidates_from_queue(state, seed, family_queue)
    if candidates:
        return candidates
    # The tail of an old deck can contain only an exhausted finite family.
    fresh = [family for family in build_family_deck(seed, state.get("last_family_id"))
             if family not in family_queue]
    return _candidates_from_queue(state, seed, fresh)


def _candidates_from_queue(
    state: dict[str, object], seed: int, family_queue: list[str],
) -> list[dict[str, object]]:
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
            if problem.fingerprint in fingerprints or training_rejection(problem):
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
