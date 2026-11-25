from collections.abc import Mapping, Sequence
from datetime import datetime

from app.adaptive.engine import Stage, State
from app.adaptive.skills import PREREQUISITES
from app.math.first_rotation import construction

History = Sequence[tuple[int, str, State, datetime]]


def unlocked(history: History) -> bool:
    return (
        any(s.opened or s.due is not None for _, _, s, _ in history)
        or sum(s.practice > 0 for _, _, s, _ in history) >= 3
    )


def plan(history: History, available: Mapping[str, int], now: float) -> list[str]:
    states = {skill: state for _, skill, state, _ in history}
    latest = {skill: at.timestamp() for _, skill, _, at in history}
    due = [k for k in available if (d := states.get(k, State()).due) is not None and d <= now]
    due.sort(key=lambda k: (states[k].due or 0, k))
    active = [
        k
        for k in available
        if k in states and states[k].opened > states[k].closed and states[k].due is None
    ]
    active.sort(key=lambda k: (-len(states[k].errors), latest[k], k))
    prerequisites = {
        PREREQUISITES[k] for k, s in states.items() if k in PREREQUISITES and s.opened > s.closed
    }
    ambiguous = states.get("OGE19-MIXED", State()).stage == Stage.CHECK
    diagnostic = sorted(
        (
            k
            for k in available
            if not (ambiguous and k == "OGE19-MIXED")
            and k not in active
            and k not in due
            and states.get(k, State()).stage in {Stage.UNCHECKED, Stage.CHECK, Stage.PRACTICE}
        ),
        key=lambda k: (
            states.get(k, State()).stage != Stage.CHECK,
            k not in prerequisites,
            not (ambiguous and k.startswith("OGE19-") and k != "OGE19-MIXED"),
            latest.get(k, 0),
            k,
        ),
    )
    slots: list[str] = []
    for preferred in (due or active, active, diagnostic, due or diagnostic, active):
        for pool in (preferred, diagnostic, active, due):
            choices = [k for k in pool if k not in slots or pool is active and slots.count(k) < 2]
            if choices:
                slots.append(
                    min(
                        choices,
                        key=lambda k: (
                            bool(slots and construction(slots[-1]) == construction(k)),
                            sum(available[s] == available[k] for s in slots),
                            choices.index(k),
                        ),
                    )
                )
                break
    return slots
