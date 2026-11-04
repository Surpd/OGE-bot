from __future__ import annotations

import re
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from app.math.scenario_engine import (
    FamilyRegistry,
    FamilyStatus,
    PracticeMode,
    PracticeRequest,
    ScenarioSnapshot,
    build_practice_plan,
    restore_asset_bytes,
)
from app.math.scenarios.stories.PAPER import (
    _DIAGRAM_PNG,
    _SOURCE_IDS,
    DIMENSIONS_MM,
    _font_answer,
    _make_world,
    _round_multiple_half_up,
    _round_ratio_tenths,
    _round_sqrt_ratio_tenths,
    build_adapter,
)


@pytest.fixture
def adapter():
    return build_adapter()


def _bundle(adapter, seed: int):
    scenario = adapter.generator.generate_scenario(seed)
    adapter.independent_oracle.validate_scenario(scenario)
    rendered = adapter.renderer.render_scenario(scenario)
    questions = tuple(adapter.question_builder.build_question(scenario, n) for n in range(1, 6))
    for question in questions:
        adapter.independent_oracle.validate_question(scenario, question, rendered)
    adapter.independent_oracle.validate_bundle(scenario, questions, rendered)
    return scenario, rendered, questions


def test_registry_exposes_only_the_six_source_checked_candidate_families(adapter) -> None:
    registry = FamilyRegistry((adapter,))
    available = {family.family_id for family in adapter.family_registry if family.available}
    assert available == set(_SOURCE_IDS)
    assert registry.available_stories(PracticeMode.FULL) == ("PAPER",)
    assert registry.available_positions("PAPER") == (1, 2, 3, 4, 5)

    disabled = {
        family.family_id: family for family in adapter.family_registry if not family.enabled
    }
    assert disabled["PAPER-F05"].status is FamilyStatus.RESEARCH_ONLY
    assert disabled["PAPER-F08"].status is FamilyStatus.BLOCKED
    assert disabled["PAPER-F09"].status is FamilyStatus.BLOCKED
    assert disabled["PAPER-F05"].source_ids == ("no_catalog_task_id",)


def test_seed_is_deterministic_and_builds_one_coherent_five_question_world(adapter) -> None:
    first = _bundle(adapter, 987654)
    second = _bundle(adapter, 987654)
    assert first == second
    scenario, rendered, questions = first
    assert scenario.seed == 987654
    assert {question.scenario_seed for question in questions} == {987654}
    assert tuple(question.position for question in questions) == (1, 2, 3, 4, 5)
    assert {question.math_model["content_kind"] for question in questions} == {"generated_analogue"}
    assert all(question.math_model["source_ids"] for question in questions)
    assert "1 м²" in rendered.shared_context
    assert "Таблица размеров" in rendered.shared_context


def test_single_and_full_practice_plans_share_the_same_snapshot_and_restore_assets(adapter) -> None:
    registry = FamilyRegistry((adapter,))
    full = build_practice_plan(
        PracticeRequest(PracticeMode.FULL, seed=2301, story_code="PAPER"), registry
    )
    single = build_practice_plan(
        PracticeRequest(PracticeMode.SINGLE, seed=2301, story_code="PAPER", position=3), registry
    )
    assert full.snapshot == single.snapshot
    assert full.selected_positions == (1, 2, 3, 4, 5)
    assert single.selected_positions == (3,)
    restored = ScenarioSnapshot.from_snapshot(full.snapshot.to_snapshot())
    assert restored == full.snapshot
    assert len(restored.assets) == 2
    for asset in restored.assets:
        data = restore_asset_bytes(adapter.renderer, restored, asset)
        assert sha256(data).hexdigest() == asset.sha256
        image = Image.open(BytesIO(data))
        assert image.format == "PNG"
        assert image.size == (
            (960, 640) if asset.sha256 == sha256(_DIAGRAM_PNG).hexdigest() else (1024, 520)
        )


def test_research_positive_vectors_recompute_exact_answers(adapter) -> None:
    # Cases are the ten positive examples in STORIES/PAPER/ORACLE_TEST_VECTORS.json.
    rows_408268 = (("A4", 297, 210), ("A3", 420, 297), ("A0", 1189, 841), ("A1", 841, 594))
    order_408268 = ("A0", "A1", "A3", "A4")
    ids_408268 = {label: index for index, (label, _, _) in enumerate(rows_408268, start=1)}
    assert "".join(str(ids_408268[label]) for label in order_408268) == "3421"
    rows_spb = (("A2", 594, 420), ("A6", 148, 105), ("A5", 210, 148), ("A1", 841, 594))
    order_spb = ("A1", "A2", "A5", "A6")
    ids_spb = {label: index for index, (label, _, _) in enumerate(rows_spb, start=1)}
    assert "".join(str(ids_spb[label]) for label in order_spb) == "4132"
    assert 2 ** (3 - 2) == 2
    assert 2 ** (5 - 0) == 32
    assert _round_multiple_half_up(841, 10) == 840
    assert _round_multiple_half_up(105, 5) == 105
    assert _round_ratio_tenths(297, 420) == "0,7"
    assert _round_sqrt_ratio_tenths(594**2 + 420**2, 420) == "1,7"
    assert _font_answer(15, 297, 420) == "21"
    assert _font_answer(10, 297, 420) == "14"
    assert _font_answer(16, 297, 210) == "11"
    assert adapter.answer_policies[("paper.mapping_four", "1")].accepts("3421", "3421")
    assert adapter.answer_policies[("paper.sheet_count", "1")].accepts("32", "32")
    assert adapter.answer_policies[("paper.font_scale", "1")].accepts("21", "21")
    assert adapter.answer_policies[("paper.ratio_tenths", "1")].accepts("0.7", "0,7")


def test_answer_policies_reject_wrong_shape_and_ambiguous_inputs(adapter) -> None:
    assert not adapter.answer_policies[("paper.mapping_four", "1")].accepts("1123", "1123")
    assert not adapter.answer_policies[("paper.mapping_four", "1")].accepts("1 2 3 4", "1234")
    assert not adapter.answer_policies[("paper.sheet_count", "1")].accepts("0", "2")
    assert not adapter.answer_policies[("paper.rounded_mm", "1")].accepts("840,0", "840")
    assert not adapter.answer_policies[("paper.ratio_tenths", "1")].accepts("0,70", "0,7")
    assert not adapter.answer_policies[("paper.font_scale", "1")].accepts("14.0", "14")


def test_exact_rounding_handles_half_boundaries_without_binary_float() -> None:
    assert _round_multiple_half_up(125, 10) == 130
    assert _round_multiple_half_up(124, 10) == 120
    assert _round_ratio_tenths(1, 16) == "0,1"
    assert _round_ratio_tenths(3, 16) == "0,2"
    assert _round_sqrt_ratio_tenths(49, 20) == "0,4"
    assert _round_sqrt_ratio_tenths(121, 20) == "0,6"


@pytest.mark.parametrize("field", ["canonical_answer", "condition", "hints", "solution_steps"])
def test_oracle_rejects_mutated_answer_condition_hint_or_solution(adapter, field: str) -> None:
    scenario, rendered, questions = _bundle(adapter, 43)
    question = questions[2]
    mutation = {
        "canonical_answer": "999",
        "condition": question.condition.replace("мм", "см", 1),
        "hints": ("Готовый ответ: 999",),
        "solution_steps": ("Подменённое решение: ответ 999",),
    }[field]
    changed = replace(question, **{field: mutation})
    with pytest.raises(ValueError, match="PAPER"):
        adapter.independent_oracle.validate_question(scenario, changed, rendered)


def test_oracle_rejects_mutated_dimensions_labels_and_table_values(adapter) -> None:
    scenario, rendered, questions = _bundle(adapter, 51)
    rows = [list(row) for row in scenario.context["rows"]]
    rows[0][1] += 1
    changed_context = {**scenario.context, "rows": rows}
    changed_scenario = replace(scenario, context=changed_context)
    with pytest.raises(ValueError, match="dimensions"):
        adapter.independent_oracle.validate_scenario(changed_scenario)

    changed_rendered = replace(
        rendered,
        shared_context=rendered.shared_context.replace("1. A", "4. A", 1),
    )
    with pytest.raises(ValueError, match="rendered table|visible table"):
        adapter.independent_oracle.validate_question(scenario, questions[0], changed_rendered)


def test_oracle_rejects_mutated_order_and_format_direction(adapter) -> None:
    scenario, rendered, questions = _bundle(adapter, 76)
    changed_order = list(scenario.context["target_order"])
    changed_order[0], changed_order[1] = changed_order[1], changed_order[0]
    changed = replace(scenario, context={**scenario.context, "target_order": changed_order})
    with pytest.raises(ValueError, match="condition"):
        adapter.independent_oracle.validate_question(changed, questions[0], rendered)

    q2 = questions[1]
    backward = replace(q2, condition=q2.condition.replace("формата A", "формата A7", 1))
    with pytest.raises(ValueError, match="format|direction|condition"):
        adapter.independent_oracle.validate_question(scenario, backward, rendered)


def test_oracle_rejects_mutated_font_units_labels_or_numbers(adapter) -> None:
    scenario, rendered, questions = _bundle(adapter, 91)
    q5 = questions[4]
    changed = replace(q5, condition=q5.condition.replace("пт", "мм", 1))
    with pytest.raises(ValueError, match="condition|units|dimensions"):
        adapter.independent_oracle.validate_question(scenario, changed, rendered)


def test_blocked_area_and_mass_vectors_are_not_registered_as_available(adapter) -> None:
    registered = {item.family_id: item for item in adapter.family_registry}
    assert registered["PAPER-F08"].status is FamilyStatus.BLOCKED
    assert registered["PAPER-F09"].status is FamilyStatus.BLOCKED
    assert not registered["PAPER-F08"].available
    assert not registered["PAPER-F09"].available
    # The two independent models remain observably different for the published examples.
    ideal_area = 10_000 / 2
    rounded_area = 841 * 594 / 100
    assert ideal_area == 5000 and rounded_area == 4995.54
    ideal_mass = 500 * 80 / 32
    rounded_mass = 500 * 80 * 210 * 148 / 1_000_000
    assert ideal_mass == 1250 and rounded_mass == 1243.2


def test_dimensional_reference_has_exactly_the_researched_a0_to_a7_pairs() -> None:
    assert DIMENSIONS_MM == {
        0: (1189, 841),
        1: (841, 594),
        2: (594, 420),
        3: (420, 297),
        4: (297, 210),
        5: (210, 148),
        6: (148, 105),
        7: (105, 74),
    }


def test_static_diagram_source_preserves_the_a0_to_a5_ratio_and_half_area_chain() -> None:
    source = (
        Path(__file__).parents[1] / "app/math/scenarios/stories/assets/paper-a0-a5-folding-v1.svg"
    )
    svg = source.read_text(encoding="utf-8")
    labels = re.findall(r">(A[0-5])</text>", svg)
    rectangles = [
        (int(w), int(h))
        for w, h in re.findall(r'<rect x="\d+" y="\d+" width="(\d+)" height="(\d+)"', svg)
    ]
    assert labels == [f"A{n}" for n in range(6)]
    assert len(rectangles) == 6
    for width, height in rectangles:
        assert abs(width / height - 2**0.5) < 0.02
    for current, following in zip(rectangles[:-1], rectangles[1:], strict=True):
        area_ratio = (current[0] * current[1]) / (following[0] * following[1])
        assert abs(area_ratio - 2) < 0.02


def test_seed_space_has_expected_structural_capacity() -> None:
    fingerprints: dict[str, set[str]] = {family_id: set() for family_id in _SOURCE_IDS}
    for seed in range(1200):
        world = _make_world(seed)
        rows = world["rows"]
        target_order = world["target_order"]
        questions = world["questions"]
        assert (
            isinstance(rows, list)
            and isinstance(target_order, list)
            and isinstance(questions, dict)
        )
        fingerprints["PAPER-F01"].add(repr((target_order, rows)))
        q2 = questions["2"]
        q3 = questions["3"]
        q4 = questions["4"]
        q5 = questions["5"]
        assert (
            isinstance(q2, dict)
            and isinstance(q3, dict)
            and isinstance(q4, dict)
            and isinstance(q5, dict)
        )
        fingerprints["PAPER-F02"].add(repr((q2["source_index"], q2["target_index"])))
        fingerprints["PAPER-F03"].add(repr((q3["format_index"], q3["side"], q3["multiple"])))
        if q4["family_id"] == "PAPER-F04":
            fingerprints["PAPER-F04"].add(repr(q4["format_index"]))
        else:
            fingerprints["PAPER-F06"].add("A2:diagonal_over_short")
        fingerprints["PAPER-F07"].add(repr((q5["source_index"], q5["target_index"], q5["old_pt"])))

    assert len(fingerprints["PAPER-F01"]) >= 200
    assert len(fingerprints["PAPER-F07"]) >= 200
    assert len(fingerprints["PAPER-F02"]) <= 21
    assert len(fingerprints["PAPER-F03"]) <= 2
    assert len(fingerprints["PAPER-F04"]) <= 7
    assert len(fingerprints["PAPER-F06"]) == 1


def test_snapshot_asset_tampering_is_rejected(adapter) -> None:
    plan = build_practice_plan(
        PracticeRequest(PracticeMode.FULL, seed=101, story_code="PAPER"), FamilyRegistry((adapter,))
    )
    snapshot = plan.snapshot
    asset = snapshot.assets[0]

    class CorruptRenderer:
        def restore_asset(self, stored: ScenarioSnapshot, reference):
            assert stored == snapshot
            return b"not-the-original-png"

    with pytest.raises(ValueError, match="digest"):
        restore_asset_bytes(CorruptRenderer(), snapshot, asset)


def test_question_snapshot_keeps_family_policy_and_source_provenance(adapter) -> None:
    plan = build_practice_plan(
        PracticeRequest(PracticeMode.FULL, seed=211, story_code="PAPER"), FamilyRegistry((adapter,))
    )
    restored = ScenarioSnapshot.from_snapshot(plan.snapshot.to_snapshot())
    for question in restored.questions:
        assert question.answer_policy_version == "1"
        assert question.math_model["source_ids"]
        assert question.math_model["content_kind"] == "generated_analogue"
