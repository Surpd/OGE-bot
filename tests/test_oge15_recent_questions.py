from dataclasses import replace

from app.bot.scenario_training import public_registry
from app.math.scenario_engine import PracticeMode, PracticeRequest, build_practice_plan
from app.math.scenarios.recent_questions import (
    is_recent_fixed_single,
    prefer_unseen,
    question_signature,
)


def test_retry_is_bounded_and_prefers_a_different_selected_question():
    registry = public_registry()
    old = build_practice_plan(PracticeRequest(PracticeMode.SINGLE, 0, "GARDEN", 1), registry)
    new = build_practice_plan(PracticeRequest(PracticeMode.SINGLE, 42, "GARDEN", 1), registry)
    recent = frozenset({question_signature(old.snapshot, old.snapshot.questions[0])})
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
        if question_signature(first.snapshot, q) != question_signature(second.snapshot, other)
    ]
    assert changes == [1, 2, 5]


def test_tariff_signature_tracks_month_usage_without_hashing_the_whole_snapshot():
    registry = public_registry()
    snapshot = build_practice_plan(
        PracticeRequest(PracticeMode.FULL, 0, "TARIFF"), registry
    ).snapshot
    question = snapshot.questions[1]
    original = question_signature(snapshot, question)
    assert question_signature(snapshot, replace(question, canonical_answer="999999")) == original
    month = question.math_model["month_index"]
    assert isinstance(month, int)
    minutes = list(snapshot.context["minutes"])
    minutes[month] += 25
    changed = replace(snapshot, context={**snapshot.context, "minutes": minutes})
    assert question_signature(changed, question) != original

    minutes = list(snapshot.context["minutes"])
    minutes[(month + 1) % 12] += 25
    unrelated = replace(snapshot, context={**snapshot.context, "minutes": minutes})
    assert question_signature(unrelated, question) == original


def test_recent_fixed_question_is_restricted_only_in_single_mode():
    registry = public_registry()
    single = build_practice_plan(PracticeRequest(PracticeMode.SINGLE, 0, "GARDEN", 3), registry)
    full = build_practice_plan(PracticeRequest(PracticeMode.FULL, 0, "GARDEN"), registry)
    recent = frozenset({question_signature(single.snapshot, single.snapshot.questions[2])})
    assert is_recent_fixed_single(single, recent)
    assert not is_recent_fixed_single(single, frozenset())
    assert not is_recent_fixed_single(full, recent)


def test_shared_heating_operands_affect_signature_but_derived_answer_does_not():
    snapshot = build_practice_plan(
        PracticeRequest(PracticeMode.FULL, 0, "GARDEN"), public_registry()
    ).snapshot
    question = snapshot.questions[4]
    original = question_signature(snapshot, question)
    heat = dict(snapshot.context["heat"])
    heat["break_even_hours"] = 999999
    assert (
        question_signature(replace(snapshot, context={**snapshot.context, "heat": heat}), question)
        == original
    )
    heat["gas_installation_cost"] += 100
    assert (
        question_signature(replace(snapshot, context={**snapshot.context, "heat": heat}), question)
        != original
    )


def test_source_fixed_paper_rounding_is_not_reissued_as_a_new_single():
    request = PracticeRequest(PracticeMode.SINGLE, 0, "PAPER", 3)
    single = build_practice_plan(request, public_registry())
    question = single.snapshot.questions[2]
    recent = frozenset({question_signature(single.snapshot, question)})
    assert question.family_id == "PAPER-F03"
    assert is_recent_fixed_single(single, recent)
    assert not is_recent_fixed_single(replace(single, mode=PracticeMode.FULL), recent)
