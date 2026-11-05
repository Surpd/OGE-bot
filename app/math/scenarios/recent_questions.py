"""Bounded avoidance of recently issued questions."""

from collections.abc import Callable

from app.math.scenario_engine import PracticePlan, QuestionSnapshot


def question_signature(question: QuestionSnapshot) -> tuple[str, str, str]:
    """Compare displayed wording and outcome; ignore incidental changes in the world."""
    return question.family_id, " ".join(question.condition.split()), question.canonical_answer


def prefer_unseen(
    generate: Callable[[], PracticePlan],
    recent: frozenset[tuple[str, str, str]],
    *,
    attempts: int = 5,
) -> PracticePlan:
    best = generate()
    best_count = _repeat_count(best, recent)
    for _ in range(attempts - 1):
        if not best_count:
            break
        candidate = generate()
        count = _repeat_count(candidate, recent)
        if count < best_count:
            best, best_count = candidate, count
    return best


def _repeat_count(plan: PracticePlan, recent: frozenset[tuple[str, str, str]]) -> int:
    return sum(
        question_signature(plan.snapshot.questions[position - 1]) in recent
        for position in plan.selected_positions
    )
