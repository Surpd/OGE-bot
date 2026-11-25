from dataclasses import replace
from datetime import UTC, datetime, timedelta

from app.adaptive.engine import Evidence, Stage, State, apply, family_status
from app.adaptive.planner import NumberPerformance, plan, plan_with_trace
from app.adaptive.skills import audit_student_titles, title


def evidence(task: str, variant: str, day: int, outcome: str = "correct", **changes):
    base = Evidence(task, variant, day * 86400, outcome, 1, False, True)
    return replace(base, **changes)


def project(*events: Evidence) -> State:
    state = State()
    for event in events:
        state, _ = apply(state, event)
    return state


def test_same_condition_is_one_observation_but_two_variants_open_gap():
    same = project(
        evidence("task-1", "math-A", 0, "wrong"),
        evidence("task-1", "math-A", 0, "wrong", attempt=2),
    )
    assert same.stage == Stage.CHECK and len(same.errors) == 1
    independent = apply(same, evidence("task-2", "math-B", 1, "wrong"))[0]
    assert independent.stage == Stage.GAP and independent.opened == 1


def test_nonfresh_or_unidentified_content_is_diagnostically_neutral():
    known = project(evidence("a", "A", 0))
    for event in (
        evidence("repeat", "A", 1, "wrong", fresh=False),
        evidence("repeat", "A", 1, "ambiguous", fresh=False),
        evidence("repeat", "A", 1, assisted=True, fresh=False),
        evidence("legacy", "", 1, "wrong"),
    ):
        assert apply(known, event)[0] == known


def test_independent_streak_crosses_modes_and_records_later_review():
    state = project(
        evidence("personal:1", "A", 0),
        evidence("ordinary:2", "B", 1),
        evidence("mixed:3", "C", 2),
    )
    assert family_status(state).label == "Получается"
    assert state.independent_count == 3
    assert state.confirmed_at == 2 * 86400
    reviewed, reason = apply(state, evidence("ordinary:4", "D", 40))
    assert reason == "independent_review" and reviewed.reviewed_at == 40 * 86400


def test_immediate_fourth_success_is_not_a_delayed_review():
    state = project(
        evidence("a", "A", 0), evidence("b", "B", 0), evidence("c", "C", 0)
    )
    state, reason = apply(state, evidence("d", "D", 0))
    assert reason is None and state.reviewed_at is None and state.independent_count == 4


def test_help_unknown_replay_and_other_family_do_not_create_false_streak():
    assert project(evidence("a", "A", 0, assisted=True)).practice == 0
    assert project(evidence("a", "A", 0, assisted=None)).practice == 0
    assert project(evidence("a", "A", 0, fresh=False)).practice == 0
    known = project(evidence("a", "A", 0))
    assert apply(known, evidence("b", "B", 1, assisted=None))[0].practice == 1
    # State is per family: an event from another family never enters this projection.
    assert project(evidence("a", "A", 0), evidence("b", "B", 1)).practice == 2


def test_number_accuracy_has_material_weight_and_trace_is_explainable():
    at = datetime(2026, 1, 1, tzinfo=UTC)
    catalog = {"weak-a": 13, "weak-b": 13, "strong-a": 9, "strong-b": 9, "gap": 9}
    history = [(9, "gap", State(stage=Stage.GAP, opened=1), at)]
    result = plan_with_trace(
        history,
        catalog,
        number_performance={13: NumberPerformance(10, 2), 9: NumberPerformance(10, 8)},
        seed=20261125,
    )
    assert result.slots[0] == "gap"
    assert result.slots[1] in {"weak-a", "weak-b"}
    assert "2 из 10" in result.reasons[1].reason


def test_fixed_seed_selection_is_reproducible_diverse_and_bounded():
    catalog = {f"f-{number}-{index}": number for number in range(6, 11) for index in range(2)}
    first = plan([], catalog, seed=73)
    assert first == plan([], catalog, seed=73)
    assert len(first) == 5 and len(set(first)) == 5
    assert max(first.count(family) for family in first) <= 2


def test_confirmed_family_can_be_sampled_without_becoming_a_debt():
    at = datetime(2025, 1, 1, tzinfo=UTC)
    history = [(6, "confirmed", State(stage=Stage.CONFIRMED, practice=3), at)]
    assert "confirmed" in plan(history, {"confirmed": 6}, seed=1)
    assert "confirmed" not in plan(history, {"confirmed": 6}, excluded=["confirmed"], seed=1)


def test_delayed_review_is_occasional_seeded_and_never_beats_a_gap():
    as_of = datetime(2026, 11, 25, tzinfo=UTC)
    old = as_of - timedelta(days=30)
    catalog = {"confirmed": 6, **{f"unknown-{i}": 7 + i % 12 for i in range(24)}}
    history = [(6, "confirmed", State(stage=Stage.CONFIRMED, practice=3), old)]

    assert "confirmed" in plan(history, catalog, seed=3, as_of=as_of)
    assert "confirmed" not in plan(history, catalog, seed=0, as_of=as_of)
    assert "confirmed" not in plan(
        [(6, "confirmed", State(stage=Stage.CONFIRMED, practice=3), as_of)],
        catalog,
        seed=3,
        as_of=as_of,
    )

    with_gap = [
        *history,
        (8, "gap", State(stage=Stage.GAP, opened=1), old),
    ]
    assert plan(with_gap, {**catalog, "gap": 8}, seed=3, as_of=as_of)[0] == "gap"


def test_public_labels_explain_the_student_action_without_internal_shorthand():
    sample = {
        "OGE09-L4A": 9,
        "OGE11-F01": 11,
        "OGE14-A10": 14,
        "OGE17-E03": 17,
        "OGE19-MIXED": 19,
    }
    assert not audit_student_titles(sample)
    assert "линейное уравнение" in title("OGE09-L4A").lower()
    assert "сопоставление" in title("OGE11-F01").lower()
    assert "арифметической прогрессии" in title("OGE14-A10").lower()
    assert "диагональ" in title("OGE17-E03").lower()
    assert "выбор верных утверждений" in title("OGE19-MIXED").lower()
