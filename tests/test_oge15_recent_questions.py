from app.bot.scenario_training import public_registry
from app.math.scenario_engine import PracticeMode, PracticeRequest, build_practice_plan
from app.math.scenarios.recent_questions import prefer_unseen, question_signature


def test_retry_is_bounded_and_prefers_a_different_selected_question():
    registry = public_registry()
    old = build_practice_plan(PracticeRequest(PracticeMode.SINGLE, 0, "GARDEN", 1), registry)
    new = build_practice_plan(PracticeRequest(PracticeMode.SINGLE, 42, "GARDEN", 1), registry)
    recent = frozenset({question_signature(old.snapshot.questions[0])})
    candidates = iter((old, new))
    assert prefer_unseen(lambda: next(candidates), recent) == new
    calls = []

    def exhausted():
        calls.append(None)
        return old

    assert prefer_unseen(exhausted, recent, attempts=3) == old
    assert len(calls) == 3


def test_garden_full_bundle_changes_three_questions_without_changing_geometry():
    registry = public_registry()
    first, second = (
        build_practice_plan(PracticeRequest(PracticeMode.FULL, seed, "GARDEN"), registry)
        for seed in (0, 42)
    )
    changes = [
        q.position
        for q, other in zip(first.snapshot.questions, second.snapshot.questions, strict=True)
        if question_signature(q) != question_signature(other)
    ]
    assert changes == [1, 2, 5]
