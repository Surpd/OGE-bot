"""Transparent deterministic selection for five-position personal sessions."""

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256

from app.adaptive.engine import Stage, State
from app.math.first_rotation import construction

History = Sequence[tuple[int, str, State, datetime]]


@dataclass(frozen=True)
class NumberPerformance:
    answered: int
    correct: int

    @property
    def weakness(self) -> float:
        if self.answered <= 0:
            return 0.0
        confidence = min(self.answered / 5, 1.0)
        accuracy = min(max(self.correct, 0), self.answered) / self.answered
        return confidence * (1 - accuracy)


@dataclass(frozen=True)
class SelectionReason:
    position: int
    family: str
    number: int
    reason: str
    score: float


@dataclass(frozen=True)
class PlanResult:
    slots: tuple[str, ...]
    reasons: tuple[SelectionReason, ...]


def unlocked(history: History) -> bool:
    """Whether reliable diagnostic history exists (not a navigation gate)."""
    return any(
        1 <= number <= 19 and state.stage != Stage.UNCHECKED for number, _, state, _ in history
    )


def _stage_weight(state: State) -> tuple[float, str]:
    if state.opened > state.closed:
        return 10.0, "актуальное затруднение"
    if state.stage == Stage.CHECK or state.errors:
        return 7.0, "нужно проверить после ошибки"
    if state.stage == Stage.PRACTICE:
        return 6.0, f"закрепление {state.practice}/3"
    if state.stage == Stage.CONFIRMED:
        return 1.0, "повторение ранее закреплённого типа"
    return 3.0, "пока недостаточно данных"


def _tie(seed: int | str, family: str) -> int:
    return int.from_bytes(sha256(f"{seed}:{family}".encode()).digest()[:8], "big")


def plan_with_trace(
    history: History,
    available: Mapping[str, int],
    *,
    prefix: Sequence[str] = (),
    excluded: Sequence[str] = (),
    size: int = 5,
    support: Mapping[str, float] | None = None,
    number_performance: Mapping[int, NumberPerformance] | None = None,
    seed: int | str = 0,
    as_of: datetime | None = None,
) -> PlanResult:
    """Keep issued positions and explain every newly selected family."""
    states = {family: state for _, family, state, _ in history}
    latest = {family: at.timestamp() for _, family, _, at in history}
    ambiguous_19 = states.get("OGE19-MIXED", State()).stage == Stage.CHECK
    excluded_set = set(excluded)
    number_bonus = {
        number: 5 * performance.weakness
        for number, performance in (number_performance or {}).items()
    }
    candidates: dict[str, tuple[float, str]] = {}
    for family, number in available.items():
        if not 1 <= number <= 19 or family in excluded_set:
            continue
        if ambiguous_19 and family == "OGE19-MIXED":
            continue
        state = states.get(family, State())
        base, reason = _stage_weight(state)
        if ambiguous_19 and number == 19:
            base, reason = max(base, 7.0), "тематическая проверка №19"
        compatibility_bonus = 2 * (support or {}).get(family, 0.0)
        candidates[family] = (
            base + number_bonus.get(number, 0.0) + compatibility_bonus,
            reason,
        )

    slots = list(prefix[:size])
    operations = {family: construction(family) for family in candidates}
    seeded_ties = {family: _tie(seed, family) for family in candidates}
    if as_of is not None:
        now = as_of.timestamp()
        for family, state in states.items():
            if (
                family in candidates
                and state.stage == Stage.CONFIRMED
                and now - latest.get(family, now) >= 7 * 86400
                and seeded_ties[family] % 4 == 0
            ):
                raw, _ = candidates[family]
                # Optional and individually bounded: it can beat an unchecked
                # family, but never a check, active gap or practice streak.
                candidates[family] = (raw + 3.5, "необязательная проверка после перерыва")
    counts = Counter(slots)
    construction_counts = Counter(construction(family) for family in slots)
    load_group = {family: number if number > 5 else 1 for family, number in available.items()}
    group_counts = Counter(load_group[f] for f in slots if f in load_group)
    reasons: list[SelectionReason] = []

    while candidates and len(slots) < size:

        def rank(family: str) -> tuple[float, float, int]:
            raw, _ = candidates[family]
            operation = operations[family]
            diversity = 6 * counts[family] + 3 * construction_counts[operation]
            score = raw - diversity - group_counts[load_group[family]]
            recency = latest.get(family, 0)
            return score, recency if raw >= 6 else -recency, seeded_ties[family]

        choice = max(candidates, key=rank)
        score = rank(choice)[0]
        reason = candidates[choice][1]
        number = available[choice]
        performance = (number_performance or {}).get(number)
        if performance and performance.weakness:
            reason += f"; №{number}: {performance.correct} из {performance.answered} верно"
        slots.append(choice)
        reasons.append(SelectionReason(len(slots) - 1, choice, number, reason, score))
        counts[choice] += 1
        construction_counts[operations[choice]] += 1
        group_counts[load_group[choice]] += 1

    return PlanResult(tuple(slots), tuple(reasons))


def plan(
    history: History,
    available: Mapping[str, int],
    *,
    prefix: Sequence[str] = (),
    excluded: Sequence[str] = (),
    size: int = 5,
    support: Mapping[str, float] | None = None,
    number_performance: Mapping[int, NumberPerformance] | None = None,
    seed: int | str = 0,
    as_of: datetime | None = None,
) -> list[str]:
    return list(plan_with_trace(
        history,
        available,
        prefix=prefix,
        excluded=excluded,
        size=size,
        support=support,
        number_performance=number_performance,
        seed=seed,
        as_of=as_of,
    ).slots)
