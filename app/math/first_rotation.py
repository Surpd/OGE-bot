"""Prefer another mathematical topic when the current deck still offers one."""

import json
from functools import lru_cache
from pathlib import Path
from typing import cast


@lru_cache(maxsize=1)
def topics() -> dict[str, str]:
    return cast(
        dict[str, str],
        json.loads(Path(__file__).with_name("first_rotation_groups.json").read_text()),
    )


def rotate_tail(
    number: int,
    state: dict[str, object],
    other_family: str | None,
    revisit: set[str] | None = None,
) -> None:
    queue = state.get("family_queue")
    # Number 9 constructs an entire deck with its own linear/quadratic run constraint.
    if number == 9 or not isinstance(queue, list) or len(queue) < 2:
        return
    groups = topics()
    previous = {
        groups[f]
        for f in (other_family, state.get("last_family_id"))
        if isinstance(f, str) and f in groups
    }
    if not previous or groups.get(queue[0]) not in previous:
        return
    alternatives = [i for i, family in enumerate(queue) if groups.get(family) not in previous]
    if alternatives:
        index = next((i for i in alternatives if revisit and queue[i] in revisit), alternatives[0])
        state["family_queue"] = [queue[index], *queue[:index], *queue[index + 1 :]]
