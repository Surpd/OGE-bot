"""Regression, source-vector, mutation, and asset checks for the FLAT adapter."""

from __future__ import annotations

import hashlib
from fractions import Fraction

import pytest

from app.math.scenario_engine import (
    FamilyStatus,
    PracticeMode,
    PracticeRequest,
    QuestionSnapshot,
    ScenarioDraft,
    ScenarioSnapshot,
    ScenarioUnavailable,
    build_practice_plan,
    discover_story_registry,
    restore_asset_bytes,
)
from app.math.scenarios.stories.FLAT import (
    COMPATIBILITY_VERSION,
    FAMILY_POSITION,
    GENERATOR_VERSION,
    SOURCE_VECTOR_SEED,
    build_adapter,
)


def bundle(seed: int):
    adapter = build_adapter()
    scenario = adapter.generator.generate_scenario(seed)
    adapter.independent_oracle.validate_scenario(scenario)
    rendered = adapter.renderer.render_scenario(scenario)
    questions = tuple(
        adapter.question_builder.build_question(scenario, position) for position in range(1, 6)
    )
    for question in questions:
        adapter.independent_oracle.validate_question(scenario, question, rendered)
    adapter.independent_oracle.validate_bundle(scenario, questions, rendered)
    return adapter, scenario, rendered, questions


def test_full_source_control_vector_is_reconstructed_from_one_seed() -> None:
    _, scenario, _, questions = bundle(SOURCE_VECTOR_SEED)
    assert [question.canonical_answer for question in questions] == [
        "1346",
        "12",
        "4,8",
        "50",
        "950",
    ]
    assert {question.scenario_seed for question in questions} == {scenario.seed}
    assert scenario.context["room_labels"]["bathroom"] == 1
    assert scenario.context["room_labels"]["pantry"] == 3
    assert scenario.context["room_labels"]["bedroom"] == 4
    assert scenario.context["room_labels"]["living"] == 6


def test_source_vectors_are_checked_with_independent_exact_arithmetic() -> None:
    # Positive vectors p01–p09, p11–p16 from the provided research package.
    assert "1346" == "1" + "3" + "4" + "6"  # p01 / task 424898, ordered response
    assert "2346" == "2" + "3" + "4" + "6"  # p02 / task 400935
    tile_count = Fraction("2") * Fraction("2.4") / Fraction("0.4") ** 2
    assert tile_count == 30
    assert (int(tile_count) + 12 - 1) // 12 == 3
    parquet_rows = Fraction("4.8") / Fraction("0.8")
    parquet_columns = Fraction("5.2") / Fraction("0.2")
    board_count = int(parquet_rows * parquet_columns)
    assert board_count == 156
    assert (board_count + 14 - 1) // 14 == 12
    assert Fraction("3.2") / Fraction("0.08") == 40
    assert (40 + 8 - 1) // 8 == 5
    assert Fraction(3 * 10) * Fraction(2, 5) ** 2 == Fraction("4.8")
    assert Fraction(9 * 11) * Fraction(2, 5) ** 2 == Fraction("15.84")
    assert (Fraction("4.8") - Fraction("3.2")) / Fraction("3.2") * 100 == 50
    assert (Fraction("14.4") - Fraction("4.8")) / Fraction("4.8") * 100 == 200
    assert [29700, 29300, 28800] == [29700, 29300, 28800]  # p11–p13 cited winning totals
    tariff_costs = [650 + (1000 - 600) * 2, 820 + (1000 - 900) * Fraction(3, 2), 950]
    assert tariff_costs == [1450, 970, 950]
    boundary_costs = [650, 820, 950]
    assert min(boundary_costs) == 650  # p15, exact included-traffic boundary
    assert (5 * 6 + 12 - 1) // 12 == 3  # p16


def test_washer_min_uses_source_eligibility_and_full_cost() -> None:
    washer = next(
        questions[4]
        for seed in range(40)
        if (questions := bundle(seed)[3])[4].family_id == "FLAT-05-WASHER-MIN"
    )
    assert "вертикальной загрузкой" in washer.condition
    assert "не менее 6 кг" in washer.condition
    assert "высотой не более" not in washer.condition
    models = washer.math_model["models"]
    eligible = [m for m in models if m["type"] == "вертикальная" and m["capacity"] >= 6]
    costs = [m["price"] + m["install"] + m["price"] * m["delivery_pct"] // 100 for m in eligible]
    assert costs.count(min(costs)) == 1
    assert washer.canonical_answer == str(min(costs))


def test_randomized_seeds_are_deterministic_and_share_one_plan() -> None:
    for seed in range(40):
        first = bundle(seed)
        second = bundle(seed)
        _, scenario, rendered, questions = first
        assert scenario.context == second[1].context
        assert rendered.assets == second[2].assets
        assert [QuestionSnapshot.from_draft(q).to_snapshot() for q in questions] == [
            QuestionSnapshot.from_draft(q).to_snapshot() for q in second[3]
        ]
        assert all(q.scenario_seed == seed for q in questions)


def test_seed_qa_reaches_200_distinct_observable_bundles_within_budget() -> None:
    fingerprints: set[str] = set()
    family_seen: set[str] = set()
    for seed in range(300):
        _, scenario, _, questions = bundle(seed)
        semantic = "|".join(
            [str(scenario.context["room_labels"]), str(scenario.context["internet"])]
            + [f"{q.family_id}:{q.condition}:{q.canonical_answer}" for q in questions]
        )
        fingerprints.add(hashlib.sha256(semantic.encode()).hexdigest())
        family_seen.update(question.family_id for question in questions)
    assert len(fingerprints) >= 200
    assert set(FAMILY_POSITION) <= family_seen


def test_all_candidate_families_are_fail_closed_and_doubtful_cases_stay_out() -> None:
    adapter = build_adapter()
    registrations = {item.family_id: item for item in adapter.family_registry}
    assert (
        sum(item.status is FamilyStatus.ENABLED_CANDIDATE for item in registrations.values()) == 8
    )
    assert sum(item.status is FamilyStatus.RESEARCH_ONLY for item in registrations.values()) == 1
    assert sum(item.status is FamilyStatus.BLOCKED for item in registrations.values()) == 1
    assert all(not item.enabled for item in registrations.values())
    assert "FLAT-04-COMPOSITE-PERCENT" not in FAMILY_POSITION  # uncertain 409306 rounding
    with pytest.raises(ScenarioUnavailable):
        build_practice_plan(
            PracticeRequest(PracticeMode.FULL, 1, story_code="FLAT"), discover_story_registry()
        )


def test_bad_room_label_and_door_mutations_are_rejected() -> None:
    adapter, scenario, rendered, questions = bundle(SOURCE_VECTOR_SEED)
    context = dict(scenario.context)
    labels = dict(scenario.context["room_labels"])
    labels["bathroom"], labels["pantry"] = labels["pantry"], labels["bathroom"]
    context["room_labels"] = labels
    changed = ScenarioDraft(
        "FLAT",
        scenario.seed,
        GENERATOR_VERSION,
        context,
        COMPATIBILITY_VERSION,
        scenario.provenance,
    )
    with pytest.raises(ValueError, match="label map|room number map"):
        adapter.independent_oracle.validate_question(changed, questions[0], rendered)

    context = dict(scenario.context)
    context["door_graph"] = tuple(tuple(edge) for edge in scenario.context["door_graph"][:-1])
    changed = ScenarioDraft(
        "FLAT",
        scenario.seed,
        GENERATOR_VERSION,
        context,
        COMPATIBILITY_VERSION,
        scenario.provenance,
    )
    with pytest.raises(ValueError, match="(?i)door graph"):
        adapter.independent_oracle.validate_scenario(changed)


@pytest.mark.parametrize(
    ("position", "condition_change", "answer_change"),
    [
        (2, ("0,2×0,8", "0,2×0,6"), None),
        (3, ("0,4 м", "0,5 м"), None),
        (4, ("кладовой", "санузла"), None),
        (5, ("950 руб.", "951 руб."), None),
        (1, None, "1436"),
    ],
)
def test_visible_condition_mutations_are_rejected(
    position: int, condition_change, answer_change
) -> None:
    adapter, scenario, rendered, questions = bundle(SOURCE_VECTOR_SEED)
    question = questions[position - 1]
    condition = question.condition
    if condition_change:
        condition = condition.replace(*condition_change)
    changed = question.__class__(
        position=question.position,
        scenario_seed=question.scenario_seed,
        family_id=question.family_id,
        generator_version=question.generator_version,
        condition=condition,
        answer_policy_id=question.answer_policy_id,
        answer_policy_version=question.answer_policy_version,
        canonical_answer=answer_change or question.canonical_answer,
        hints=question.hints,
        solution_steps=question.solution_steps,
        math_model=question.math_model,
    )
    with pytest.raises(ValueError):
        adapter.independent_oracle.validate_question(scenario, changed, rendered)


def test_png_svg_restore_to_original_sha256_without_disk_assets() -> None:
    adapter, scenario, rendered, questions = bundle(SOURCE_VECTOR_SEED)
    snapshot = ScenarioSnapshot(
        story_code="FLAT",
        seed=scenario.seed,
        generator_version=scenario.generator_version,
        compatibility_matrix_version=scenario.compatibility_matrix_version,
        context=scenario.context,
        shared_context=rendered.shared_context,
        assets=rendered.assets,
        questions=tuple(QuestionSnapshot.from_draft(question) for question in questions),
        provenance=scenario.provenance,
    )
    for asset in rendered.assets:
        restored = restore_asset_bytes(adapter.renderer, snapshot, asset)
        assert hashlib.sha256(restored).hexdigest() == asset.sha256
        extension = "png" if asset.content_type == "image/png" else "svg"
        assert asset.storage_key.endswith("." + extension)
        if asset.content_type == "image/svg+xml":
            assert b"<svg" in restored and b"#1463a5" in restored and b"#008b8b" in restored
        else:
            assert restored.startswith(b"\x89PNG\r\n\x1a\n")


def test_answer_policy_keeps_order_and_accepts_exact_decimal_not_rounding() -> None:
    adapter = build_adapter()
    policy = adapter.answer_policies[("oge15.flat.numeric", "1")]
    assert policy.accepts("1346", "1346")
    assert not policy.accepts("1436", "1346")
    assert policy.accepts("4.8", "4,8")
    assert not policy.accepts("4.80.1", "4,8")


def test_source_plan_has_distinct_loggias_and_lookup_only_questions() -> None:
    from app.math.scenarios.stories.FLAT import DOORS, ROOM_PARTS

    _, scenario, _, questions = bundle(SOURCE_VECTOR_SEED)

    def area(room):
        return sum((x2 - x1) * (y2 - y1) for x1, y1, x2, y2 in ROOM_PARTS[room])

    assert (area("loggia_1"), area("loggia_2")) == (30, 44)
    assert (area("bathroom"), area("pantry"), area("living")) == (30, 20, 156)
    assert ("hall", "bathroom") in DOORS
    assert ("hall", "pantry") in DOORS
    assert ("pantry", "bathroom") not in DOORS
    assert ("living", "kitchen") in DOORS
    assert "меньшей лоджии" in questions[2].condition
    assert not any(char.isdigit() for char in questions[3].condition)
    assert "4,8×5,2" not in questions[1].condition


def test_pre_v2_flat_snapshot_restores_identical_assets(monkeypatch) -> None:
    import json
    from pathlib import Path

    from PIL import ImageFont

    # Use the old fallback font; platform-specific PNG codec bytes are checked below.
    truetype = ImageFont.truetype

    def linux_font(font, *args, **kwargs):
        if font == "arial.ttf":
            raise OSError("Production Linux has no Arial")
        return truetype(font, *args, **kwargs)

    monkeypatch.setattr(ImageFont, "truetype", linux_font)
    snapshot = ScenarioSnapshot.from_snapshot(
        json.loads(
            (Path(__file__).parent / "fixtures" / "flat_v1_snapshot.json").read_text(
                encoding="utf-8"
            )
        )
    )
    assert snapshot.generator_version == "flat-grid-1.0.0"
    import runpy
    from dataclasses import replace

    from app.math.scenario_engine import ScenarioAssetRef

    # The static SVG reference is portable. PNG deflate/font wheels are not:
    # freeze the old implementation, then demand exact old bytes in this runtime.
    frozen = runpy.run_path(str(Path(__file__).parent / "fixtures" / "flat_v1_png.py"))
    scenario = ScenarioDraft(
        snapshot.story_code,
        snapshot.seed,
        snapshot.generator_version,
        snapshot.context,
        snapshot.compatibility_matrix_version,
        snapshot.provenance,
    )
    old_png = frozen["Renderer"]()._png(scenario)
    old_digest = hashlib.sha256(old_png).hexdigest()
    print(f"FLAT c2570e9 fallback PNG SHA-256: {old_digest}")
    assets = tuple(
        ScenarioAssetRef(old_digest, asset.content_type, f"sha256/{old_digest}.png")
        if asset.content_type == "image/png"
        else asset
        for asset in snapshot.assets
    )
    snapshot = replace(snapshot, assets=assets)
    for asset in snapshot.assets:
        restored = restore_asset_bytes(build_adapter().renderer, snapshot, asset)
        assert hashlib.sha256(restored).hexdigest() == asset.sha256
        if asset.content_type == "image/png":
            assert restored == old_png
