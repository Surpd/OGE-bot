from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from io import BytesIO

import pytest
from PIL import Image, ImageChops

from app.math.scenario_engine import (
    FamilyRegistry,
    PracticeMode,
    PracticeRequest,
    build_practice_plan,
    discover_story_registry,
    restore_asset_bytes,
)
from app.math.scenarios.stories.TYRES import (
    _WHEEL_BYTES,
    NUMBER_POLICY_ID,
    NUMBER_POLICY_VERSION,
    build_adapter,
)


def _plan(seed: int = 2026, mode: PracticeMode = PracticeMode.FULL, position: int | None = None):
    adapter = build_adapter()
    return adapter, build_practice_plan(
        PracticeRequest(mode, seed, story_code="TYRES", position=position),
        FamilyRegistry((adapter,)),
    )


def test_tyres_full_and_single_plans_share_one_world_and_all_five_questions() -> None:
    adapter, full = _plan(7301)
    assert full.selected_positions == (1, 2, 3, 4, 5)
    assert tuple(question.position for question in full.snapshot.questions) == (1, 2, 3, 4, 5)
    assert {question.scenario_seed for question in full.snapshot.questions} == {7301}
    assert len(full.snapshot.assets) == 1
    _, single = _plan(7301, PracticeMode.SINGLE, position=4)
    assert single.selected_positions == (4,)
    assert len(single.snapshot.questions) == 5
    assert single.snapshot.context == full.snapshot.context
    assert single.snapshot.shared_context == full.snapshot.shared_context
    assert single.snapshot.assets == full.snapshot.assets

    rendered = adapter.renderer.render_scenario(adapter.generator.generate_scenario(7301))
    assert all(question.condition for question in full.snapshot.questions)
    assert "разрешённые размеры шин" in rendered.shared_context
    assert "B, H, d и D" in rendered.shared_context


def test_seed_is_deterministic_snapshot_roundtrip_and_asset_restores_after_rebuild() -> None:
    adapter, plan = _plan(401)
    repeated = build_adapter()
    repeated_scenario = repeated.generator.generate_scenario(401)
    repeated_render = repeated.renderer.render_scenario(repeated_scenario)
    assert repeated_render == adapter.renderer.render_scenario(
        adapter.generator.generate_scenario(401)
    )

    restored_snapshot = type(plan.snapshot).from_snapshot(plan.snapshot.to_snapshot())
    assert restored_snapshot == plan.snapshot
    assert (
        restore_asset_bytes(repeated.renderer, restored_snapshot, restored_snapshot.assets[0])
        == _WHEEL_BYTES
    )
    assert sha256(_WHEEL_BYTES).hexdigest() == restored_snapshot.assets[0].sha256


def test_all_enabled_families_pass_250_seed_quality_and_uniqueness_gate() -> None:
    adapter = build_adapter()
    registry = FamilyRegistry((adapter,))
    assert registry.available_stories(PracticeMode.FULL) == ("TYRES",)
    assert registry.available_positions("TYRES") == (1, 2, 3, 4, 5)
    seen: dict[str, set[tuple[object, ...]]] = {
        family.family_id: set() for family in adapter.family_registry if family.available
    }

    # Main correctness sweep (250 scenarios), followed by the family acceptance
    # budget (1,200 deterministic attempts) used by the research gate.
    for seed in range(1200):
        plan = build_practice_plan(
            PracticeRequest(PracticeMode.FULL, seed, story_code="TYRES"), registry
        )
        for question in plan.snapshot.questions:
            if question.position == 1:
                table_text = plan.snapshot.shared_context.split(
                    "В таблице приведены разрешённые размеры шин:\n\n", 1
                )[1].split("\n\nСхема показывает", 1)[0]
                variant = (
                    table_text,
                    question.condition,
                    question.canonical_answer,
                )
            elif question.position == 2:
                variant = (question.condition, question.canonical_answer)
            elif question.position == 3:
                variant = (
                    question.math_model["factory_marking"],
                    question.canonical_answer,
                )
            elif question.position == 4:
                variant = (question.condition, question.canonical_answer)
            else:
                variant = (
                    question.math_model["factory_marking"],
                    question.condition,
                    question.canonical_answer,
                )
            seen[question.family_id].add(variant)

    assert set(seen) == {
        "TYRES-TABLE-EXTREME",
        "TYRES-SIDEWALL",
        "TYRES-DIAMETER",
        "TYRES-RADIUS-DELTA",
        "TYRES-PERCENT-ROTATION",
    }
    assert all(len(variants) >= 200 for variants in seen.values())


def test_disabled_diameter_delta_family_is_not_selected_by_any_mode() -> None:
    adapter = build_adapter()
    delta = next(
        item for item in adapter.family_registry if item.family_id == "TYRES-DIAMETER-DELTA"
    )
    assert not delta.available
    plan = build_practice_plan(
        PracticeRequest(PracticeMode.SINGLE, 808, story_code="TYRES", position=4),
        FamilyRegistry((adapter,)),
    )
    assert plan.snapshot.questions[3].family_id == "TYRES-RADIUS-DELTA"


def test_answer_policy_accepts_decimal_comma_and_rejects_units_or_extra_text() -> None:
    adapter = build_adapter()
    policy = adapter.answer_policies[(NUMBER_POLICY_ID, NUMBER_POLICY_VERSION)]
    assert policy.accepts("115,5", "115.5")
    assert policy.accepts(" 115.50 ", "115.5")
    assert not policy.accepts("115.5 мм", "115.5")
    assert not policy.accepts("115,5,0", "115.5")


def test_researched_fipi_2026_full_kit_and_reshu_source_answer_vectors() -> None:
    adapter = build_adapter()
    scenario = adapter.generator.generate_scenario(2026)
    context = dict(scenario.context)
    context.update(
        {
            "base_marking": "175/70 R12",
            "base": [175, 70, 12],
            "table_rims": [12, 13, 14],
            "table_target_rim": 13,
            "table": [
                {"width_mm": 175, "aspect_ratios_by_rim": [[70], [65], []]},
                {"width_mm": 185, "aspect_ratios_by_rim": [[], [60], []]},
                {"width_mm": 195, "aspect_ratios_by_rim": [[], [60], []]},
            ],
            "sidewall_marking": "165/65 R14",
            "sidewall": [165, 65, 14],
            "comparison_markings": ["185/60 R13", "175/65 R13"],
            "comparison": [[185, 60, 13], [175, 65, 13]],
            "replacement_marking": "175/65 R13",
            "replacement": [175, 65, 13],
        }
    )
    scenario = replace(scenario, context=context)
    rendered = adapter.renderer.render_scenario(scenario)
    adapter.independent_oracle.validate_scenario(scenario)
    expected_answers = ("195", "107.25", "549.8", "2.75", "1.4")
    questions = tuple(
        adapter.question_builder.build_question(scenario, position) for position in range(1, 6)
    )
    assert tuple(question.canonical_answer for question in questions) == expected_answers
    adapter.independent_oracle.validate_bundle(scenario, questions, rendered)


def test_oracle_rejects_visible_unit_marking_table_diameter_rounding_and_image_mutations() -> None:
    adapter, plan = _plan(77)
    scenario = adapter.generator.generate_scenario(77)
    rendered = adapter.renderer.render_scenario(scenario)
    questions = tuple(
        adapter.question_builder.build_question(scenario, position) for position in range(1, 6)
    )
    oracle = adapter.independent_oracle

    q2 = questions[1]
    with pytest.raises(ValueError, match="unit or math model"):
        oracle.validate_question(
            scenario, replace(q2, condition=q2.condition.replace("миллиметров", "дюймов")), rendered
        )

    with pytest.raises(ValueError, match="tyre marking"):
        oracle.validate_question(
            scenario, replace(q2, condition=q2.condition.replace(" R", " X")), rendered
        )

    q1_table_line = next(
        line
        for line in rendered.shared_context.splitlines()
        if line.startswith("| ") and "/" in line
    )
    mutated_context = rendered.shared_context.replace(
        q1_table_line, q1_table_line.replace("/", "x", 1)
    )
    with pytest.raises(ValueError, match="Visible table cells"):
        oracle.validate_question(
            scenario, questions[0], replace(rendered, shared_context=mutated_context)
        )

    base = str(scenario.context["base_marking"])
    other = "205/70 R18" if base != "205/70 R18" else "155/45 R12"
    mutated_context = rendered.shared_context.replace(base, other, 1)
    with pytest.raises(ValueError, match="factory marking differs"):
        oracle.validate_question(
            scenario, questions[2], replace(rendered, shared_context=mutated_context)
        )

    q5 = questions[4]
    with pytest.raises(ValueError, match="positive increase rounded to tenths"):
        oracle.validate_question(
            scenario,
            replace(q5, condition=q5.condition.replace("Результат округлите до десятых.", "")),
            rendered,
        )

    fake_asset = replace(
        rendered.assets[0], sha256="0" * 64, storage_key="sha256/" + "0" * 64 + ".png"
    )
    with pytest.raises(ValueError, match="wheel image is missing or changed"):
        oracle.validate_question(scenario, questions[0], replace(rendered, assets=(fake_asset,)))

    with pytest.raises(ValueError, match="same scenario seed"):
        oracle.validate_bundle(
            scenario,
            (questions[0], replace(questions[1], scenario_seed=78), *questions[2:]),
            rendered,
        )
    assert plan.snapshot.seed == 77


def test_png_schematic_has_no_clipping_and_is_invariant_across_parameter_changes() -> None:
    image = Image.open(BytesIO(_WHEEL_BYTES)).convert("RGB")
    assert image.size == (960, 620)
    background = Image.new("RGB", image.size, "white")
    bounds = ImageChops.difference(image, background).getbbox()
    assert bounds is not None
    assert bounds[0] > 0 and bounds[1] > 0
    assert bounds[2] < image.width and bounds[3] < image.height

    first_adapter = build_adapter()
    first = first_adapter.renderer.render_scenario(first_adapter.generator.generate_scenario(1))
    second_adapter = build_adapter()
    second = second_adapter.renderer.render_scenario(
        second_adapter.generator.generate_scenario(9999)
    )
    assert first.assets == second.assets
    assert _WHEEL_BYTES.startswith(b"\x89PNG\r\n\x1a\n")


def test_story_module_is_discovered_without_registering_number_in_training_menu() -> None:
    registry = discover_story_registry()
    assert registry.story_codes == ("TYRES",)
    from app.bot.trainings import BY_NUMBER

    assert not any(number in BY_NUMBER for number in range(1, 6))
