from __future__ import annotations

from dataclasses import replace
from xml.etree import ElementTree

import pytest

from app.math.scenario_engine import (
    FamilyRegistry,
    PracticeMode,
    PracticeRequest,
    build_practice_plan,
    restore_asset_bytes,
)
from app.math.scenarios.stories.GARDEN import (
    FAMILIES,
    _Builder,
    _Generator,
    _Oracle,
    _Renderer,
    build_adapter,
)


def _plan(seed: int = 0):
    adapter = build_adapter(enabled_families=frozenset(FAMILIES))
    return build_practice_plan(
        PracticeRequest(PracticeMode.FULL, seed, "GARDEN"), FamilyRegistry((adapter,))
    )


def test_sosnovka_source_fixture_answers_and_single_full_identity() -> None:
    full = _plan(0)
    assert [q.canonical_answer for q in full.snapshot.questions] == ["7425", "7", "36", "29", "500"]
    adapter = build_adapter(enabled_families=frozenset(FAMILIES))
    single = build_practice_plan(
        PracticeRequest(PracticeMode.SINGLE, 0, "GARDEN", 3), FamilyRegistry((adapter,))
    )
    assert single.snapshot == full.snapshot
    assert single.selected_positions == (3,)


def test_quarantined_and_research_only_types_stay_disabled() -> None:
    adapter = build_adapter(enabled_families=frozenset(FAMILIES))
    by_id = {f.family_id: f for f in adapter.family_registry}
    assert all(
        not by_id[name].enabled
        for name in {
            "GARDEN-10-PAINT-CHEAPEST",
            "GARDEN-11-OPEN-SOIL",
            "GARDEN-12-PERCENT-AREA-DIFF",
        }
    )
    assert by_id["GARDEN-11-OPEN-SOIL"].status.value == "blocked"


def test_svg_labels_scale_and_asset_restore_are_snapshot_stable() -> None:
    adapter = build_adapter()
    plan = _plan(42)
    asset = plan.snapshot.assets[0]
    image = restore_asset_bytes(adapter.renderer, plan.snapshot, asset)
    root = ElementTree.fromstring(image)
    assert root.find(".//*[@data-label='greenhouse']").text == str(
        plan.snapshot.context["labels"]["greenhouse"]
    )
    assert "2 м".encode() in image and "1 м".encode() in image
    assert image == restore_asset_bytes(adapter.renderer, plan.snapshot, asset)


def test_independent_oracle_rejects_question_answer_mutations() -> None:
    scenario = _Generator().generate_scenario(0)
    rendered = _Renderer().render_scenario(scenario)
    oracle = _Oracle()
    for position in range(1, 6):
        question = _Builder().build_question(scenario, position)
        oracle.validate_question(scenario, question, rendered)
        with pytest.raises(ValueError):
            oracle.validate_question(scenario, replace(question, canonical_answer="999"), rendered)
    with pytest.raises(ValueError):
        oracle.validate_question(
            scenario,
            _Builder().build_question(scenario, 5),
            replace(rendered, shared_context=rendered.shared_context + "8.84"),
        )


def test_svg_mutations_for_building_scale_path_width_and_labels_are_rejected() -> None:
    from app.math.scenarios.stories.GARDEN import _Generator, _Oracle, _Renderer

    scenario = _Generator().generate_scenario(0)
    image = _Renderer().render_scenario(scenario)
    svg = _Renderer().restore_asset(_plan(0).snapshot, _plan(0).snapshot.assets[0])
    oracle = _Oracle()
    mutations = (
        (b"M120 20H200", b"M121 20H200"),
        (b'data-role="paving" x="290"', b'data-role="paving" x="289"'),
        (b'viewBox="0 0 400 300"', b'viewBox="0 0 800 600"'),
        (b'data-label="house"', b'data-label="shed"'),
    )
    assert image.assets
    oracle.validate_svg_bytes(scenario, svg)
    for old, new in mutations:
        with pytest.raises(ValueError):
            oracle.validate_svg_bytes(scenario, svg.replace(old, new, 1))


def test_quality_250_seeds_answers_unique_and_restorable() -> None:
    adapter = build_adapter(enabled_families=frozenset(FAMILIES))
    fingerprints: set[tuple[str, ...]] = set()
    for seed in range(250):
        plan = build_practice_plan(
            PracticeRequest(PracticeMode.FULL, seed, "GARDEN"), FamilyRegistry((adapter,))
        )
        fingerprints.add(tuple(q.condition for q in plan.snapshot.questions))
        assert tuple(q.family_id for q in plan.snapshot.questions) == FAMILIES
        assert restore_asset_bytes(adapter.renderer, plan.snapshot, plan.snapshot.assets[0])
    assert len(fingerprints) >= 200
