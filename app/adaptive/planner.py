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
    while priority and len(slots) < size:

        def rank(k: str) -> tuple[float, ...]:
            same = bool(slots and construction(k) == construction(slots[-1]))
            same_number = sum(available.get(s) == available[k] for s in slots)
            recency = latest.get(k, 0)
            return (
                priority[k] - 4 * counts[k] - 3 * same - same_number,
                recency if priority[k] >= 4 else -recency,
            )

        choice = max(sorted(priority), key=rank)
        slots.append(choice)
        counts[choice] += 1
    return slots
