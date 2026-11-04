from __future__ import annotations

from dataclasses import replace
from fractions import Fraction
from hashlib import sha256

import pytest

from app.math.scenario_engine import (
    FamilyRegistry,
    PracticeMode,
    PracticeRequest,
    QuestionSnapshot,
    RenderedScenario,
    ScenarioAssetRef,
    ScenarioSnapshot,
    ScenarioUnavailable,
    build_practice_plan,
    discover_story_registry,
    restore_asset_bytes,
)
from app.math.scenarios.stories.STOVE import (
    FAMILY_IDS,
    SOURCE_IDS,
    StoveAdapter,
    _svg_arc,
    _validate_arc_svg,
    build_adapter,
)


def _fixture(seed: int = 12345):
    adapter = build_adapter()
    scenario = adapter.generator.generate_scenario(seed)
    adapter.independent_oracle.validate_scenario(scenario)
    rendered = adapter.renderer.render_scenario(scenario)
    questions = tuple(
        adapter.question_builder.build_question(scenario, position) for position in range(1, 6)
    )
    return adapter, scenario, rendered, questions


def test_adapter_is_complete_and_remains_fail_closed() -> None:
    adapter = build_adapter()
    assert adapter.story_code == "STOVE"
    assert {item.family_id for item in adapter.family_registry} == set(FAMILY_IDS)
    assert len(adapter.family_registry) == 12
    assert all(item.enabled is False for item in adapter.family_registry)
    assert all(item.source_ids == SOURCE_IDS[item.family_id] for item in adapter.family_registry)
    registry = discover_story_registry()
    assert registry.story_codes == ("STOVE",)
    with pytest.raises(ScenarioUnavailable, match="no enabled family"):
        build_practice_plan(PracticeRequest(PracticeMode.FULL, 1, "STOVE"), registry)
    decimal_policy = adapter.answer_policies[("decimal_exact", "1")]
    assert decimal_policy.accepts("15,4", "15,4")
    assert decimal_policy.accepts("15.4", "15,4")
    assert not decimal_policy.accepts("15,5", "15,4")


@pytest.mark.parametrize("seed", [0, 1, 12, 12345, 2**31 - 1])
def test_seed_creates_one_valid_five_question_world(seed: int) -> None:
    adapter, scenario, rendered, questions = _fixture(seed)
    adapter.independent_oracle.validate_bundle(scenario, questions, rendered)
    assert len({question.scenario_seed for question in questions}) == 1
    assert [question.position for question in questions] == [1, 2, 3, 4, 5]
    assert len(rendered.assets) == 4


def test_generation_and_images_are_deterministic_and_restorable() -> None:
    adapter, scenario, rendered, questions = _fixture(8128)
    snapshot = ScenarioSnapshot(
        story_code=scenario.story_code,
        seed=scenario.seed,
        generator_version=scenario.generator_version,
        compatibility_matrix_version=scenario.compatibility_matrix_version,
        context=scenario.context,
        shared_context=rendered.shared_context,
        assets=rendered.assets,
        questions=tuple(QuestionSnapshot.from_draft(q) for q in questions),
        provenance=scenario.provenance,
    )
    repeated = adapter.generator.generate_scenario(8128)
    repeated_render = adapter.renderer.render_scenario(repeated)
    assert rendered == repeated_render
    for asset in snapshot.assets:
        first = restore_asset_bytes(adapter.renderer, snapshot, asset)
        second = restore_asset_bytes(adapter.renderer, snapshot, asset)
        assert first == second
        assert sha256(first).hexdigest() == asset.sha256
        assert len(first) > 100


@pytest.mark.parametrize("family_id", FAMILY_IDS)
def test_family_has_250_independent_oracle_valid_variants(family_id: str) -> None:
    adapter = build_adapter()
    position = next(
        item.position for item in adapter.family_registry if item.family_id == family_id
    )
    fingerprints: set[str] = set()
    for seed in range(250):
        scenario = adapter.generator.generate_scenario(seed + 100_000)
        adapter.independent_oracle.validate_scenario(scenario)
        rendered = adapter.renderer.render_scenario(scenario)
        question = adapter.question_builder.build_question_for_family(scenario, position, family_id)
        adapter.independent_oracle.validate_question(scenario, question, rendered)
        fingerprints.add(
            sha256((question.condition + "\n" + rendered.shared_context).encode()).hexdigest()
        )
    assert len(fingerprints) >= 200


def test_candidate_full_bundle_builds_through_common_contract_when_temporarily_enabled() -> None:
    adapter = StoveAdapter()
    adapter.family_registry = tuple(replace(item, enabled=True) for item in adapter.family_registry)
    registry = FamilyRegistry((adapter,))
    plan = build_practice_plan(PracticeRequest(PracticeMode.FULL, 55, "STOVE"), registry)
    assert plan.selected_positions == (1, 2, 3, 4, 5)
    assert plan.snapshot.story_code == "STOVE"
    assert len(plan.snapshot.questions) == 5
    scenario = adapter.generator.generate_scenario(plan.snapshot.seed)
    rendered = adapter.renderer.render_scenario(scenario)
    questions = tuple(adapter.question_builder.build_question(scenario, p) for p in range(1, 6))
    adapter.independent_oracle.validate_bundle(scenario, questions, rendered)


def test_oracle_rejects_visible_text_mutations() -> None:
    adapter, scenario, rendered, questions = _fixture(10)
    q1 = questions[0]
    changed_direction = replace(q1, condition=q1.condition.replace("наименьших", "наибольших"))
    with pytest.raises(ValueError):
        adapter.independent_oracle.validate_question(scenario, changed_direction, rendered)

    direct_discount = adapter.question_builder.build_question_for_family(
        scenario, 4, "STOVE-F09-DIRECT-DISCOUNT"
    )
    changed_discount = replace(
        direct_discount, condition=direct_discount.condition.replace("скидка 10%", "скидка 90%")
    )
    with pytest.raises(ValueError):
        adapter.independent_oracle.validate_question(scenario, changed_discount, rendered)

    conditional = adapter.question_builder.build_question_for_family(
        scenario, 4, "STOVE-F11-CONDITIONAL-TWO-DISCOUNTS"
    )
    threshold = conditional.condition.split("дороже ", maxsplit=1)[1].split(" руб.", maxsplit=1)[0]
    price = conditional.condition.split("Цена печи №3 — ", maxsplit=1)[1].split(
        " руб.", maxsplit=1
    )[0]
    boundary_condition = conditional.condition.replace(threshold, price, 1)
    with pytest.raises(ValueError):
        adapter.independent_oracle.validate_question(
            scenario, replace(conditional, condition=boundary_condition), rendered
        )
    omitted_delivery_discount = replace(
        conditional,
        condition=conditional.condition.replace(
            "на доставку — скидка 20%", "на доставку скидки нет"
        ),
    )
    with pytest.raises(ValueError):
        adapter.independent_oracle.validate_question(scenario, omitted_delivery_discount, rendered)


def test_oracle_rejects_wall_units_and_changed_arc_asset() -> None:
    adapter, scenario, rendered, _ = _fixture(77)
    walls = adapter.question_builder.build_question_for_family(
        scenario, 3, "STOVE-F05-WALL-AREA-NET"
    )
    wrong_units = replace(walls, condition=walls.condition.replace("см ×", "м ×"))
    with pytest.raises(ValueError):
        adapter.independent_oracle.validate_question(scenario, wrong_units, rendered)

    arc = adapter.question_builder.build_question(scenario, 5)
    svg_ref = next(a for a in rendered.assets if a.content_type == "image/svg+xml")
    altered_ref = ScenarioAssetRef("0" * 64, "image/svg+xml", f"sha256/{'0' * 64}.svg")
    changed = RenderedScenario(
        rendered.shared_context,
        tuple(altered_ref if asset == svg_ref else asset for asset in rendered.assets),
    )
    with pytest.raises(ValueError):
        adapter.independent_oracle.validate_question(scenario, arc, changed)


def test_arc_oracle_rejects_a_mutated_svg_endpoint() -> None:
    source = _svg_arc(60, 40)
    mutated = source.replace(b"M 280.000,340.000", b"M 282.000,340.000", 1)
    with pytest.raises(ValueError, match="endpoints"):
        _validate_arc_svg(mutated, 60, 40, 50)


def test_conflicted_catalog_answers_are_not_registered_as_families() -> None:
    adapter = build_adapter()
    registered_ids = {item.family_id for item in adapter.family_registry}
    assert "STOVE-F13-YEARLY-OPERATING-COSTS" not in registered_ids
    assert "STOVE-F14-UNVERIFIED-ARC-DESIGNS" not in registered_ids
    assert "STOVE-F15-BROKEN-PRICE-KEY" not in registered_ids
    assert all(
        "408240" not in item.source_ids and "408261" not in item.source_ids
        for item in adapter.family_registry
    )


def test_archive_positive_examples_are_independently_supported() -> None:
    adapter, scenario, rendered, _ = _fixture(123)
    assert "".join(str({8: 1, 10: 2, 9: 3}[value]) for value in (8, 9, 10)) == "132"
    assert "".join(str({40: 1, 48: 2, 15: 3}[value]) for value in (15, 40, 48)) == "312"
    assert Fraction(35, 10) * Fraction(22, 10) * 2 == Fraction(154, 10)
    assert Fraction(35, 10) * Fraction(22, 10) == Fraction(77, 10)
    wall_area = 2 * (Fraction(35, 10) + Fraction(22, 10)) * 2 - Fraction(60, 100) * Fraction(
        180, 100
    )
    assert wall_area == Fraction(2172, 100)
    assert 15_000 + 6_500 + 800 == 22_300
    assert 18_500 + 1_200 == 19_700
    assert abs(19_500 - (15_000 + 6_500)) == 2_000
    assert 19_500 - 15_000 == 4_500
    assert 18_000 * Fraction(90, 100) == 16_200
    assert Fraction(18_000, 1) / Fraction(90, 100) == 20_000
    assert Fraction(20_500 * 95 + 700 * 80, 100) == 20_035
    assert 15_000 + 6_500 + 1_000 == 22_500
    assert str(15_000 + 6_500 + 1_000) != "2"
    _validate_arc_svg(_svg_arc(60, 40), 60, 40, 50)
    adapter.independent_oracle.validate_scenario(scenario)
    assert "Печь | Тип" in rendered.shared_context
