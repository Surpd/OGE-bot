from __future__ import annotations

import random
from typing import cast
from uuid import uuid4

from app.math.equations import ENABLED_FAMILIES, generate_equation

MAX_CANDIDATES = 48
SEEDS_PER_FAMILY = 4
RECENT_FINGERPRINTS = 30


def _deck(
    seed: int,
    last_family: str | None = None,
    last_group: str | None = None,
    group_run_length: int = 0,
) -> list[str]:
    rng = random.Random(f"oge9-deck:{seed}")
    linear = [family for family in ENABLED_FAMILIES if family.startswith("OGE09-L")]
    quadratic = [family for family in ENABLED_FAMILIES if family.startswith("OGE09-K")]
    if len(linear) > 4:
        linear = rng.sample(linear, k=4)
    # Four equally represented group slots per deck. Type probabilities inside
    # each group remain uniform; there are no hand-tuned weights per family.
    quadratic.append(rng.choice(quadratic))
    rng.shuffle(linear)
    rng.shuffle(quadratic)
    cards = linear + quadratic

    def group(family: str) -> str:
        return "linear" if family.startswith("OGE09-L") else "quadratic"

    # Shuffle the balanced multiset, allowing runs of up to three and requiring
    # at least one same-group adjacency so the schedule is not strict L-K alternation.
    for _ in range(256):
        deck = cards.copy()
        rng.shuffle(deck)
        if (last_family is not None and deck[0] == last_family) or any(
            left == right for left, right in zip(deck, deck[1:], strict=False)
        ):
            continue
        run_group = last_group
        run_length = group_run_length if last_group is not None else 0
        has_short_run = False
        valid = True
        for family in deck:
            current_group = group(family)
            if current_group == run_group:
                run_length += 1
            else:
                run_group, run_length = current_group, 1
            if run_length > 3:
                valid = False
                break
            if run_length == 2:
                has_short_run = True
        if valid and has_short_run:
            return deck
    raise RuntimeError("Unable to build a bounded task-9 schedule")


def build_task9_candidate_batch(state: dict[str, object], seed: int) -> list[dict[str, object]]:
    stored = state.get("family_queue")
    queue = (
        cast(list[str], stored)
        if isinstance(stored, list)
        and stored
        and all(isinstance(item, str) and item in ENABLED_FAMILIES for item in stored)
        else _deck(
            seed,
            str(state.get("last_family_id", "")) or None,
            str(state.get("last_group", "")) or None,
            _group_run_length(state),
        )
    )
    stored_recent = state.get("recent_fingerprints", [])
    recent = (
        {item for item in stored_recent if isinstance(item, str)}
        if isinstance(stored_recent, list)
        else set()
    )
    seen = set(recent)
    rng = random.Random(f"oge9-candidates:{seed}")
    result: list[dict[str, object]] = []
    attempts = 0
    previous_group = (
        str(state.get("last_group", "")) or None
        if isinstance(state.get("last_group"), str)
        else None
    )
    previous_run = _group_run_length(state)
    group_state_after: list[tuple[str, int]] = []
    for family_id in queue:
        current_group = "linear" if family_id.startswith("OGE09-L") else "quadratic"
        previous_run = previous_run + 1 if current_group == previous_group else 1
        previous_group = current_group
        group_state_after.append((current_group, previous_run))
    for index, family_id in enumerate(queue):
        for _ in range(SEEDS_PER_FAMILY):
            attempts += 1
            problem = generate_equation(family_id, rng.randrange(2**63))
            if problem.fingerprint in seen:
                continue
            seen.add(problem.fingerprint)
            snapshot = problem.to_snapshot()
            snapshot.update(
                {
                    "problem_id": str(uuid4()),
                    "selection_attempts": attempts,
                    "_family_queue_after": queue[index + 1 :],
                    "_last_group_after": group_state_after[index][0],
                    "_group_run_length_after": group_state_after[index][1],
                }
            )
            result.append(snapshot)
            if len(result) >= MAX_CANDIDATES:
                return result
    return result


def _group_run_length(state: dict[str, object]) -> int:
    value = state.get("group_run_length", 0)
    return value if isinstance(value, int) else 0
