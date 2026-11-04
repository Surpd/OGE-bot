from __future__ import annotations

from dataclasses import replace

import pytest

from app.math.scenario_engine import (
    FamilyRegistry,
    PracticeMode,
    PracticeRequest,
    ScenarioDraft,
    build_practice_plan,
    restore_asset_bytes,
)
from app.math.scenarios.stories.TARIFF import (
    BILL_FAMILY,
    IMPLEMENTED_FAMILIES,
    MINIMUM_FAMILY,
    MINUTES_FAMILY,
    PERCENT_FAMILY,
    SET_A,
    TariffAnswerPolicy,
    _ceil_packages,
    _isp_costs_cents,
    _monthly_bill_cents,
    build_adapter,
)


@pytest.fixture
def adapter():
    return build_adapter(enabled_families=frozenset(IMPLEMENTED_FAMILIES))


def _registry(adapter):
    return FamilyRegistry((adapter,))


def _question_content_fingerprint(question, context) -> tuple[object, ...]:
    common = (
        question.family_id,
        question.condition,
        question.canonical_answer,
        question.solution_steps,
    )
    if question.position == 1:
        return common
    if question.position == 2:
        month = question.math_model["month_index"]
        tariff = context["tariff"]
        relevant_tariff = tuple(
            tariff[key]
            for key in (
                "monthly_fee_cents",
                "included_minutes",
                "included_gb_quarters",
                "extra_minute_cents",
                "data_pack_quarters",
                "data_pack_price_cents",
                "included_sms_month",
                "annual_sms",
            )
        )
        return common + (
            context["minutes"][month],
            context["gb_quarters"][month],
            relevant_tariff,
        )
    if question.position == 3:
        return common + (tuple(context["minutes"]),)
    if question.position == 4:
        return common
    isp = context["isp"]
    table = tuple(
        tuple(plan[key] for key in ("name", "monthly_fee_cents", "included_mb", "per_mb_cents"))
        for plan in isp["plans"]
    )
    return common + (question.math_model["usage_mb"], table)


def test_seed_is_deterministic_and_full_bundle_uses_source_compatible_set(adapter) -> None:
    first = adapter.generator.generate_scenario(924)
    second = adapter.generator.generate_scenario(924)
    assert first.context == second.context
    plan = build_practice_plan(
        PracticeRequest(PracticeMode.FULL, 924, story_code="TARIFF"), _registry(adapter)
    )
    assert plan.snapshot.context["compatible_set_id"] == SET_A
    assert tuple(question.family_id for question in plan.snapshot.questions) == (
        MINUTES_FAMILY,
        BILL_FAMILY,
        MINIMUM_FAMILY,
        PERCENT_FAMILY,
        "TARIFF-F12-HOME-ISP",
    )
    assert all(question.scenario_seed == plan.snapshot.seed for question in plan.snapshot.questions)


def test_every_position_builds_in_single_mode_from_the_same_world(adapter) -> None:
    registry = _registry(adapter)
    for position in range(1, 6):
        plan = build_practice_plan(
            PracticeRequest(PracticeMode.SINGLE, 1200 + position, "TARIFF", position), registry
        )
        assert plan.selected_positions == (position,)
        assert len(plan.snapshot.questions) == 5
        assert plan.snapshot.questions[position - 1].position == position
        assert all(
            question.scenario_seed == plan.snapshot.seed for question in plan.snapshot.questions
        )


def test_1200_seed_oracle_and_per_question_content_diversity(adapter) -> None:
    registry = _registry(adapter)
    fingerprints: dict[str, set[tuple[object, ...]]] = {
        family: set() for family in IMPLEMENTED_FAMILIES
    }
    for seed in range(1200):
        plan = build_practice_plan(PracticeRequest(PracticeMode.FULL, seed, "TARIFF"), registry)
        context = plan.snapshot.context
        for question in plan.snapshot.questions:
            family = question.family_id
            fingerprints[family].add(_question_content_fingerprint(question, context))
    assert {family: len(items) for family, items in fingerprints.items()} == {
        MINUTES_FAMILY: 1200,
        BILL_FAMILY: 992,
        MINIMUM_FAMILY: 1200,
        PERCENT_FAMILY: 4,
        "TARIFF-F12-HOME-ISP": 220,
    }


def test_snapshot_keeps_graph_and_table_assets_restorable(adapter) -> None:
    plan = build_practice_plan(
        PracticeRequest(PracticeMode.FULL, 841, "TARIFF"), _registry(adapter)
    )
    hashes = [asset.sha256 for asset in plan.snapshot.assets]
    assert len(hashes) == 2
    assert len(set(hashes)) == 2
    for asset in plan.snapshot.assets:
        content = restore_asset_bytes(adapter.renderer, plan.snapshot, asset)
        assert content
        assert len(content) < 100_000


def test_renderer_does_not_retain_assets_across_scenarios(adapter) -> None:
    renderer = adapter.renderer
    plan = build_practice_plan(
        PracticeRequest(PracticeMode.FULL, 842, "TARIFF"), _registry(adapter)
    )
    before = tuple(
        restore_asset_bytes(renderer, plan.snapshot, asset) for asset in plan.snapshot.assets
    )
    for seed in range(256):
        scenario = adapter.generator.generate_scenario(seed)
        renderer.render_scenario(scenario)
    after = tuple(
        restore_asset_bytes(renderer, plan.snapshot, asset) for asset in plan.snapshot.assets
    )
    assert before == after
    assert not hasattr(renderer, "_asset_cache")


def test_money_uses_exact_kopecks_and_ceil_for_partial_data_packages(adapter) -> None:
    scenario = adapter.generator.generate_scenario(3)
    context = dict(scenario.context)
    context["minutes"] = (300,) * 12
    context["gb_quarters"] = (12, 13, 14, 16) + (12,) * 8
    context["tariff"] = dict(context["tariff"])
    assert _monthly_bill_cents(context, 0) == 35_000
    assert _monthly_bill_cents(context, 1) == 44_000
    assert _monthly_bill_cents(context, 2) == 44_000
    assert _monthly_bill_cents(context, 3) == 53_000
    assert _ceil_packages(1, 2) == 1
    assert _ceil_packages(2, 2) == 1
    assert _ceil_packages(3, 2) == 2
    assert _ceil_packages(0, 2) == 0


def test_research_vectors_for_bill_percentage_and_home_internet(adapter) -> None:
    """Regression vectors P04/P09/P13 from the V1 TARIFF oracle dossier."""
    scenario = adapter.generator.generate_scenario(461_832)
    context = dict(scenario.context)
    context["minutes"] = (175, 275, 150, 350, 300, 325, 375, 325, 200, 200, 325, 350)
    context["gb_quarters"] = (10, 14, 8, 16, 11, 12, 4, 6, 11, 13, 15, 9)
    assert _monthly_bill_cents(context, 7) == 42_500  # Aug: 350 + 25 × 3

    old_fee_cents, new_fee_cents = 35_000, 49_000
    assert (new_fee_cents - old_fee_cents) * 100 // old_fee_cents == 40

    isp = {
        "plans": (
            {
                "name": "Поминутный",
                "monthly_fee_cents": 0,
                "included_mb": 0,
                "per_mb_cents": 150,
            },
            {
                "name": "Домашний-200",
                "monthly_fee_cents": 20_400,
                "included_mb": 200,
                "per_mb_cents": 120,
            },
            {
                "name": "Домашний-700",
                "monthly_fee_cents": 67_200,
                "included_mb": 700,
                "per_mb_cents": 50,
            },
        )
    }
    assert _isp_costs_cents(isp, 700) == (105_000, 80_400, 67_200)
    assert _isp_costs_cents(isp, 1_000) == (150_000, 116_400, 82_200)

    context["isp"] = {"usage_mb": 1_000, "plans": isp["plans"]}
    scenario_1000 = replace(scenario, context=context)
    rendered_1000 = adapter.renderer.render_scenario(scenario_1000)
    question_1000 = adapter.question_builder.build_question(scenario_1000, 5)
    adapter.independent_oracle.validate_question(scenario_1000, question_1000, rendered_1000)
    assert question_1000.canonical_answer == "822"


def test_answer_policies_preserve_month_code_and_normalize_money() -> None:
    month_policy = TariffAnswerPolicy("tariff.tariff-f01-months-minutes")
    assert month_policy.accepts(" 61142 ", "61142")
    assert not month_policy.accepts("6,11,4,2", "61142")
    assert not month_policy.accepts("61143", "61142")
    money_policy = TariffAnswerPolicy("tariff.tariff-f04-monthly-bill")
    assert money_policy.accepts("425,00", "425")
    assert money_policy.accepts("425", "425")
    assert not money_policy.accepts("-425", "425")
    assert not money_policy.accepts("425.001", "425")


def test_source_incompatible_families_stay_disabled(adapter) -> None:
    registrations = {item.family_id: item for item in adapter.family_registry}
    assert all(registrations[family].available for family in IMPLEMENTED_FAMILIES)
    for family in (
        "TARIFF-F02-MONTHS-GB",
        "TARIFF-F03-TRENDS",
        "TARIFF-F06-COUNT-ONE-LIMIT",
        "TARIFF-F07-COUNT-BOTH-LIMITS",
        "TARIFF-F08-COUNT-BASE-PRICE",
        "TARIFF-F10-PERCENT-TRAFFIC",
        "TARIFF-F11-ANNUAL-SWITCH",
        "TARIFF-F13-SMARTPHONE-CREDIT",
        "TARIFF-F14-LEGACY-STANDALONE",
        "TARIFF-F15-SMS-MONTHLY-OVERAGE",
    ):
        assert not registrations[family].available


def test_adapter_fails_closed_by_default() -> None:
    adapter = build_adapter()
    assert not any(family.available for family in adapter.family_registry)


def test_oracle_rejects_question_answer_mutation(adapter) -> None:
    scenario = adapter.generator.generate_scenario(903)
    rendered = adapter.renderer.render_scenario(scenario)
    question = adapter.question_builder.build_question(scenario, 2)
    mutated = replace(question, canonical_answer=str(int(question.canonical_answer) + 1))
    with pytest.raises(ValueError, match="answer|bill|solution"):
        adapter.independent_oracle.validate_question(scenario, mutated, rendered)


def test_oracle_rejects_rendered_graph_axis_mutation(adapter, monkeypatch) -> None:
    scenario = adapter.generator.generate_scenario(904)
    rendered = adapter.renderer.render_scenario(scenario)
    original = adapter.renderer.asset_bytes(scenario, "usage-chart")
    original_asset_bytes = adapter.renderer.asset_bytes
    mutated = original.replace(b">400</text>", b">500</text>", 1)
    monkeypatch.setattr(
        adapter.renderer,
        "asset_bytes",
        lambda current, name: mutated
        if name == "usage-chart"
        else original_asset_bytes(current, name),
    )
    question = adapter.question_builder.build_question(scenario, 1)
    with pytest.raises(ValueError, match="axis|graph|chart|label"):
        adapter.independent_oracle.validate_question(scenario, question, rendered)


def test_oracle_rejects_changed_data_limit_when_bill_answer_is_unchanged(adapter) -> None:
    scenario = adapter.generator.generate_scenario(905)
    changed = dict(scenario.context)
    tariff = dict(changed["tariff"])
    tariff["included_gb_quarters"] = 8
    changed["tariff"] = tariff
    mutated_scenario = ScenarioDraft(
        scenario.story_code,
        scenario.seed,
        scenario.generator_version,
        changed,
        scenario.compatibility_matrix_version,
        scenario.provenance,
    )
    rendered = adapter.renderer.render_scenario(mutated_scenario)
    question = adapter.question_builder.build_question(scenario, 2)
    with pytest.raises(ValueError, match="bill|answer|tariff"):
        adapter.independent_oracle.validate_question(mutated_scenario, question, rendered)
