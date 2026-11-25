"""Transparent deterministic selection for five-position personal sessions."""

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256

from app.adaptive.engine import CURRENT, Stage, State
from app.math.first_rotation import construction

History = Sequence[tuple[int, str, State, datetime]]


@dataclass(frozen=True)
class NumberPerformance:
    answered: int
    correct: int

    @property
    def needs_practice(self) -> bool:
        return self.answered >= 5 and self.correct * 5 <= self.answered * 3

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
    by_number: bool = False


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
    if state.stage == Stage.CHECK:
        return 7.0, "стоит проверить на новом задании"
    if state.stage == Stage.PRACTICE:
        return 6.0, f"самостоятельно решено подряд {state.practice}/{CURRENT.practice_count}"
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
    difficulties: Mapping[str, int] | None = None,
    recommendations_only: bool = False,
    include_practice: bool = True,
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
    candidates: dict[str, tuple[float, str, bool]] = {}
    for family, number in available.items():
        if not 1 <= number <= 19 or family in excluded_set:
            continue
        if ambiguous_19 and family == "OGE19-MIXED":
            continue
        state = states.get(family, State())
        base, reason = _stage_weight(state)
        if ambiguous_19 and number == 19:
            base, reason = max(base, 7.0), "тематическая проверка №19"
        difficulty = (difficulties or {}).get(family, 0)
        if difficulty and state.opened <= state.closed and state.stage != Stage.CONFIRMED:
            base = max(base, 7.0)
            reason = "в этой тренировке были ошибки или понадобилась помощь"
        else:
            difficulty = 0
        focus = (
            state.opened > state.closed or state.stage == Stage.CHECK or bool(difficulty)
            or ambiguous_19 and number == 19
            or include_practice and state.stage == Stage.PRACTICE
        )
        performance = (number_performance or {}).get(number)
        number_focus = bool(performance and performance.needs_practice)
        if recommendations_only and not (focus or number_focus):
            continue
        support_bonus = 2 * (support or {}).get(family, 0.0)
        candidates[family] = (
            base + number_bonus.get(number, 0.0) + support_bonus + min(difficulty, 2),
            reason,
            not focus and number_focus,
        )

    slots = list(prefix[:size])
    operations = {family: construction(family) for family in candidates}
    seeded_ties = {family: _tie(seed, family) for family in candidates}
    if as_of is not None:
        now = as_of.timestamp()
        for family, state in states.items():
            if (
                family in candidates
                and not recommendations_only
                and state.stage == Stage.CONFIRMED
                and now - latest.get(family, now) >= 7 * 86400
                and seeded_ties[family] % 4 == 0
            ):
                raw, _, by_number = candidates[family]
                # Optional and individually bounded: it can beat an unchecked
                # family, but never a check, active gap or practice streak.
                candidates[family] = (raw + 3.5, "можно повторить после перерыва", by_number)
    counts = Counter(slots)
    construction_counts = Counter(construction(family) for family in slots)
    load_group = {family: number if number > 5 else 1 for family, number in available.items()}
    group_counts = Counter(load_group[f] for f in slots if f in load_group)
    reasons: list[SelectionReason] = []

    while candidates and len(slots) < size:

        def rank(family: str) -> tuple[float, float, int]:
            raw, _, _ = candidates[family]
            operation = operations[family]
            diversity = 6 * counts[family] + 3 * construction_counts[operation]
            score = raw - diversity - group_counts[load_group[family]]
            recency = latest.get(family, 0)
            state = states.get(family)
            recent_error = state and (state.opened > state.closed or state.stage == Stage.CHECK)
            return score, recency if recent_error else -recency, seeded_ties[family]

        choice = max(candidates, key=rank)
        score = rank(choice)[0]
        _, reason, by_number = candidates[choice]
        number = available[choice]
        performance = (number_performance or {}).get(number)
        if performance and performance.needs_practice:
            accuracy = f"по №{number} верно {performance.correct} из {performance.answered}"
            reason = accuracy if by_number else f"{reason} · {accuracy}"
        slots.append(choice)
        reasons.append(SelectionReason(len(slots) - 1, choice, number, reason, score, by_number))
        counts[choice] += 1
        construction_counts[operations[choice]] += 1
        group_counts[load_group[choice]] += 1
        if recommendations_only:
            del candidates[choice]
            if by_number:
                for family in tuple(candidates):
                    if available[family] == number and candidates[family][2]:
                        del candidates[family]

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
