from __future__ import annotations

import json
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from xml.etree import ElementTree

import pytest

from app.math.scenario_engine import (
    FamilyRegistry,
    PracticeMode,
    PracticeRequest,
    QuestionSnapshot,
    ScenarioSnapshot,
    build_practice_plan,
    restore_asset_bytes,
)
from app.math.scenarios.stories.GARDEN import (
    FAMILIES,
    _Builder,
    _Generator,
    _Oracle,
    _Renderer,
    _svg,
    _world,
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


def test_garden_heat_uses_two_stage_source_operands_and_independent_oracle() -> None:
    plan = _plan(0)
    question = plan.snapshot.questions[4]
    context = plan.snapshot.shared_context
    assert question.canonical_answer == "500"
    assert "числовые исходные данные приведены в отдельной таблице" in context
    assert all(value not in context for value in ("20000", "15370", "15000", "14000"))
    assert all(value not in question.condition for value in ("20000", "15370", "1.6", "4.9"))
    assert "Используйте таблицу исходных данных" in question.condition
    assert "7.84" not in context and "20.58" not in context
    assert "Сколько часов" in question.condition or "Через сколько часов" in question.condition

    scenario = _Generator().generate_scenario(0)
    rendered = _Renderer().render_scenario(scenario)
    oracle = _Oracle()
    altered = replace(rendered, shared_context=context + "\nМонтаж: 15370 руб.")
    with pytest.raises(ValueError, match="Shared plan/table text"):
        oracle.validate_question(scenario, _Builder().build_question(scenario, 5), altered)
    question = _Builder().build_question(scenario, 5)
    with pytest.raises(ValueError):
        oracle.validate_question(
            scenario,
            replace(
                question,
                solution_steps=(*question.solution_steps[:-1], "Answer: 500"),
            ),
            rendered,
        )
    malformed_question = replace(
        question, condition=question.condition.replace("таблицу", "список"),
    )
    with pytest.raises(ValueError, match="presented data table"):
        oracle.validate_question(scenario, malformed_question, rendered)


def test_garden_heating_table_is_the_single_complete_visible_operand_source(monkeypatch) -> None:
    from unittest.mock import Mock

    from app.math.scenarios import mobile_photos

    snapshot = _plan(0).snapshot
    render = Mock(return_value=b"heating-table")
    monkeypatch.setattr(mobile_photos, "table", render)
    assert mobile_photos.garden_heating_table(snapshot) == b"heating-table"
    title, rows, _widths = render.call_args.args
    assert title == "Отопление: исходные данные"
    visible = " ".join(cell for row in rows for cell in row)
    for value in ("20 000", "15 370", "15 000", "14 000", "1.6", "4.9", "4.2"):
        assert value in visible
    assert all(value not in snapshot.shared_context for value in ("20000", "15370", "15000"))
    assert all(value not in snapshot.questions[4].condition for value in ("20000", "15370", "1.6"))


def test_garden_v1_6_shared_context_remains_byte_for_byte_compatible() -> None:
    scenario = _Generator().generate_scenario(0)
    previous = replace(scenario, generator_version="garden-sosnovka-1.6")
    context = _Renderer().render_scenario(previous).shared_context
    assert "Газ: котёл 20000 руб., монтаж 15370 руб.; 1.6 м³/ч, 4.9 руб./м³." in context
    assert "Электричество: котёл 15000 руб., монтаж 14000 руб.; 4.9 кВт" in context


@pytest.mark.parametrize("version", ["garden-sosnovka-1.5", "garden-sosnovka-1.6"])
def test_delivered_archived_heat_question_is_not_repeated_in_context_or_table(version: str) -> None:
    from app.bot.scenario_materials import scenario_context_for_question
    from app.math.scenarios.mobile_photos import scenario_photos_for_question

    current = _plan(0).snapshot
    archived_scenario = replace(
        _Generator().generate_scenario(0), generator_version="garden-sosnovka-1.6"
    )
    archived_question = QuestionSnapshot.from_draft(
        replace(_Builder().build_question(archived_scenario, 5), generator_version=version)
    )
    archived = replace(
        current,
        generator_version=version,
        shared_context=_Renderer().render_scenario(archived_scenario).shared_context,
        questions=(*current.questions[:4], archived_question),
    )
    before = archived.to_snapshot()

    assert "газовый котёл 20000 руб." in archived_question.condition
    assert "Отопление одного дома" not in scenario_context_for_question(archived, 5)
    assert scenario_photos_for_question(archived, 5) == ()
    assert archived.to_snapshot() == before


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


def test_legacy_v1_3_snapshot_restores_its_exact_original_svg() -> None:
    fixture = Path(__file__).parent / "fixtures" / "garden_v1_3_snapshot.json"
    snapshot_data = json.loads(fixture.read_text(encoding="utf-8"))
    snapshot = ScenarioSnapshot.from_snapshot(snapshot_data)
    asset = snapshot.assets[0]
    image = restore_asset_bytes(build_adapter().renderer, snapshot, asset)
    assert snapshot.generator_version == "garden-sosnovka-1.3"
    assert asset.sha256 == "a32fd13d36a8814e4b31e597e6e267eab612e12bfba34ac54b65481795a93fc1"
    assert sha256(image).hexdigest() == asset.sha256
    v1_4_context = {**_world(0), "world_version": "garden-sosnovka-1.4"}
    assert sha256(_svg(v1_4_context)).hexdigest() == asset.sha256


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
        (b'points="140,40 240,40', b'points="141,40 240,40'),
        (b'data-role="paving" x="60"', b'data-role="paving" x="61"'),
        (b'viewBox="0 0 400 300"', b'viewBox="0 0 800 600"'),
        (b'data-label="house"', b'data-label="shed"'),
    )
    assert image.assets
    oracle.validate_svg_bytes(scenario, svg)
    for old, new in mutations:
        with pytest.raises(ValueError):
            oracle.validate_svg_bytes(scenario, svg.replace(old, new, 1))


def test_sosnovka_source_grid_roles_areas_and_path_tile_total() -> None:
    scenario = _Generator().generate_scenario(0)
    # The independent oracle checks the actual rendered SVG; these fixed source
    # vectors keep the published grid coordinates and area assignments explicit.
    svg = _Renderer().restore_asset(_plan(0).snapshot, _plan(0).snapshot.assets[0])
    root = ElementTree.fromstring(svg)

    def rectangle(role: str) -> tuple[int, int, int, int]:
        node = root.find(f".//*[@data-role='{role}']")
        assert node is not None
        x, y, width, height = (int(node.attrib[key]) for key in ("x", "y", "width", "height"))
        return x, y, width, height

    assert rectangle("shed") == (260, 20, 60, 40)
    assert rectangle("garage") == (240, 160, 80, 60)
    assert rectangle("bath") == (20, 160, 60, 60)
    assert rectangle("garden") == (20, 20, 100, 120)
    assert rectangle("greenhouse") == (40, 40, 60, 20)
    assert rectangle("pad") == (280, 60, 40, 100)
    assert tuple(scenario.context["building_areas_m2"]) == (68, 36, 48, 24)
    path_rectangles = root.findall(".//*[@data-role='paving']")
    path_area = sum(
        int(node.attrib["width"]) * int(node.attrib["height"])
        for node in path_rectangles
    ) // 100
    assert path_area == 25
    pad = rectangle("pad")
    assert (pad[2] * pad[3]) // 100 == 40


@pytest.mark.mass
def test_quality_250_seeds_answers_unique_and_restorable() -> None:
    adapter = build_adapter(enabled_families=frozenset(FAMILIES))
    fingerprints: set[tuple[str, ...]] = set()
    for seed in range(250):
        plan = build_practice_plan(
            PracticeRequest(PracticeMode.FULL, seed, "GARDEN"), FamilyRegistry((adapter,))
        )
        conditions = tuple(q.condition for q in plan.snapshot.questions)
        fingerprints.add((*conditions, repr(plan.snapshot.context["heat"])))
        assert tuple(q.family_id for q in plan.snapshot.questions) == FAMILIES
        assert restore_asset_bytes(adapter.renderer, plan.snapshot, plan.snapshot.assets[0])
    assert len(fingerprints) >= 200
