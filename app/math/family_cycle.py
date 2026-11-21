"""Ordinary practice consumes the saved permutation only on a successful issue."""

import random
from collections.abc import Callable
from typing import Any

from app.math.first_rotation import construction, topics


def _shuffle(families: list[str], seed: int, previous: str) -> list[str]:
    pool = families.copy()
    random.Random(seed).shuffle(pool)
    result = []
    while pool:
        counts = [construction(f) for f in pool]
        # Use larger groups early so their last members do not bunch at the end.
        chosen = min(
            pool,
            key=lambda f: (
                f == previous,
                construction(f) == construction(previous),
                -counts.count(construction(f)),
                topics().get(f) == topics().get(previous),
            ),
        )
        result.append(chosen)
        pool.remove(chosen)
        previous = chosen
    return result


def ordinary_candidates(
    builder: Callable[..., list[dict[str, object]]],
    state: dict[str, object],
    seed: int,
    **kwargs: Any,
) -> list[dict[str, object]]:
    families = state.get("cycle_families")
    if not isinstance(families, list):
        return builder(state, seed, **kwargs)
    allowed = kwargs.get("enabled_families")
    if allowed is not None:
        families = [family for family in families if family in allowed]
    previous = str(state.get("cycle_last") or state.get("last_family_id", ""))
    raw = state.get("cycle_tail")
    tail = list(dict.fromkeys(f for f in raw if f in families)) if isinstance(raw, list) else []
    fixed = state.get("selected_family_id")
    if isinstance(fixed, str):
        if fixed not in families:
            return []
        deck = [fixed]
    else:
        deck = tail or _shuffle(families, seed, previous)
    shared_last = str(state.get("last_family_id") or "")
    if not fixed and deck and construction(deck[0]) == construction(shared_last):
        for index, alternative in enumerate(deck):
            if construction(alternative) != construction(shared_last) and alternative != previous:
                deck.insert(0, deck.pop(index))
                break
    opening_cycle = not fixed and not tail
    tried: set[str] = set()
    while deck:
        if opening_cycle and deck[0] == previous and len(deck) > 1:
            # Earlier entries may have been exhausted. Try all other families
            # before allowing a repeat across this cycle boundary.
            deck = [*deck[1:], previous]
        family, *rest = deck
        tried.add(family)
        local = {**state, "family_queue": [family], "selected_family_id": family}
        batch = [c for c in builder(local, seed, **kwargs) if c.get("family_id") == family]
        if batch:
            for item in batch:
                item["_family_queue_after"] = tail if fixed else rest
            return batch
        deck = rest
        if not deck and tail and not fixed:
            # Old tail can consist entirely of exhausted shapes. Open the next
            # cycle without retrying those families in this same request.
            deck = _shuffle([f for f in families if f not in tried], seed, previous)
            opening_cycle = True
    return []
