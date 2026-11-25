from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime

from app.adaptive.engine import Stage, State
from app.math.first_rotation import construction

History = Sequence[tuple[int, str, State, datetime]]


def unlocked(history: History) -> bool:
    return any(
        1 <= number <= 19 and state.stage != Stage.UNCHECKED for number, _, state, _ in history
    )


def plan(
    history: History,
    available: Mapping[str, int],
    *,
    prefix: Sequence[str] = (),
    excluded: Sequence[str] = (),
    size: int = 5,
    support: Mapping[str, float] | None = None,
) -> list[str]:
    """Keep the delivered prefix. Rank the remainder again after each result."""
    states = {k: s for _, k, s, _ in history}
    latest = {k: at.timestamp() for _, k, _, at in history}
    ambiguous = states.get("OGE19-MIXED", State()).stage == Stage.CHECK
    priority = {}
    for k, n in available.items():
        if not 1 <= n <= 19 or k in excluded or ambiguous and k == "OGE19-MIXED":
            continue
        state = states.get(k, State())
        if state.opened > state.closed:
            weight = 9
        elif state.stage == Stage.CHECK or state.errors or ambiguous and n == 19:
            weight = 6
        elif state.stage == Stage.PRACTICE:
            weight = 4
        elif state.stage == Stage.CONFIRMED:
            weight = 0
        else:
            weight = 2
        priority[k] = weight
    slots = list(prefix)
    counts = Counter(prefix)
    # Each standalone story position brings its own statement and visual materials.
    load_group = {k: n if n > 5 else 1 for k, n in available.items()}
    group_counts = Counter(load_group[k] for k in prefix if k in load_group)
    ordered = sorted(priority)
    while ordered and len(slots) < size:

        def rank(k: str) -> tuple[float, ...]:
            same = bool(slots and construction(k) == construction(slots[-1]))
            recency = latest.get(k, 0)
            return (
                priority[k]
                + (support or {}).get(k, 0)
                - 4 * counts[k]
                - 3 * same
                - group_counts[load_group[k]],
                recency if priority[k] >= 4 else -recency,
            )

        choice = max(ordered, key=rank)
        slots.append(choice)
        counts[choice] += 1
        group_counts[load_group[choice]] += 1
    return slots
