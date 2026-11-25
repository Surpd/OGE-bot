"""Pure observational engine. Dates are elapsed UTC days from the experiment start."""

from collections import deque
from dataclasses import dataclass, field
from math import exp


@dataclass(frozen=True)
class Event:
    event_id: str
    day: int
    skill: int
    item: str
    family: int
    outcome: str


@dataclass
class Skill:
    stage: str = "unknown"
    due: int | None = None
    seen: set = field(default_factory=set)
    recent: deque = field(default_factory=lambda: deque(maxlen=6))
    posterior: float = 0.35
    good: float = 0.0
    bad: float = 0.0
    last: int = -1
    promoted: int = -1
    interval: int = 7
    exposure: int = 0
    last_offer: int = -1


DEFAULT_SKILLS = tuple(range(8))


class Engine:
    def __init__(self, policy="rules", skills=DEFAULT_SKILLS):
        if policy not in ("rules", "weighted", "bkt"):
            raise ValueError(policy)
        self.policy = policy
        self.skills = {key: Skill() for key in skills}
        self.events = {}
        self.awards = set()

    def queue(self, day, limit=5):
        """At most 2 overdue + 2 weak + 1 exploration; fill vacancies fairly."""
        order = sorted(
            self.skills, key=lambda k: (self.skills[k].last_offer, self.skills[k].exposure, k)
        )
        overdue = {k for k in order if self.skills[k].due is not None and self.skills[k].due <= day}
        selected = []
        for candidates, capacity in [
            ([k for k in order if k in overdue], 2),
            (
                [
                    k
                    for k in order
                    if k not in overdue and self.skills[k].stage in ("practice", "check")
                ],
                2,
            ),
            ([k for k in order if k not in overdue and self.skills[k].stage == "unknown"], 1),
            ([k for k in order if k not in overdue], limit),
        ]:
            additions = [k for k in candidates if k not in selected]
            selected.extend(additions[: max(0, min(capacity, limit - len(selected)))])
        return selected

    def apply(self, e):
        if e.event_id in self.events:
            return False
        if e.outcome not in ("clean", "error", "hint", "solution", "retry", "skip", "unknown"):
            raise ValueError(e.outcome)
        s = self.skills[e.skill]
        if e.day < s.last_offer:
            raise ValueError("replay events in canonical order")
        self.events[e.event_id] = e
        s.last_offer = e.day
        s.exposure += 1
        fresh = e.item not in s.seen
        s.seen.add(e.item)
        if not fresh or e.outcome not in ("clean", "error"):
            return True
        success = e.outcome == "clean"
        elapsed = max(0, e.day - s.last)
        decay = exp(-elapsed / 30)
        s.good = s.good * decay + int(success)
        s.bad = s.bad * decay + int(not success)
        p = 0.15 + (s.posterior - 0.15) * exp(-elapsed / 90)
        a, b = (0.9, 0.20) if success else (0.10, 0.80)
        post = a * p / (a * p + b * (1 - p))
        s.posterior = post + (1 - post) * 0.10
        s.last = e.day
        while s.recent and e.day - s.recent[0][2] > 45:
            s.recent.popleft()
        s.recent.append((success, e.family, e.day))
        good = [r for r in s.recent if r[0]]
        # All models share minimum independent items and transfer coverage.
        diverse = len(good) >= 2 and len({r[1] for r in good}) >= 2
        if self.policy == "rules":
            qualifies = len(good) >= 3 and all(r[0] for r in list(s.recent)[-2:])
            weak = sum(not r[0] for r in list(s.recent)[-3:]) >= 2
        elif self.policy == "weighted":
            score = (1 + s.good) / (2 + s.good + s.bad)
            qualifies = score >= 0.72
            weak = score < 0.45
        else:
            qualifies = s.posterior >= 0.88
            weak = s.posterior <= 0.45
        if success and diverse and qualifies:
            if s.stage in ("provisional", "confirmed"):
                if s.due is not None and e.day >= s.due:
                    s.stage = "confirmed"
                    self.awards.add(e.skill)
                    s.interval = min(30, s.interval * 2)
                    s.due = e.day + s.interval
            else:
                s.stage = "provisional"
                s.promoted = e.day
                s.interval = 7
                s.due = e.day + s.interval
        elif not success:
            # Only two recent independent failures can reopen a stable skill.
            repeated = sum(not r[0] for r in list(s.recent)[-3:]) >= 2
            if weak and repeated:
                s.stage, s.due = "practice", None
            elif s.stage in ("provisional", "confirmed"):
                # A failed check never shortens the seven-day qualification delay.
                s.due = max(s.promoted + 7, e.day + 1)
            elif s.stage == "unknown":
                s.stage = "check"
        return True
