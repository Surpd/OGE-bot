from __future__ import annotations

from dataclasses import replace
from hashlib import sha256

import pytest

from app.math.scenario_engine import (
    FamilyRegistry,
    PracticeMode,
    PracticeRequest,
    ScenarioSnapshot,
    ScenarioUnavailable,
    build_practice_plan,
    restore_asset_bytes,
)
from app.math.scenarios.stories.ROUTE import (
    F01,
    F03,
    F05,
    F06,
    F09,
    SOURCES_BY_POSITION,
    _svg,
    _validate_svg_manifest,
    build_adapter,
)
from scripts.oge15_route_quality_report import _question_fingerprint

FAMILIES = (F01, F03, F05, F06, F09)
EXPECTED_SOURCE_ANSWERS = ("213", "56", "40", "168", "1134")


def _fixture(seed: int = 0):
    adapter = build_adapter()
    scenario = adapter.generator.generate_scenario(seed)
    rendered = adapter.renderer.render_scenario(scenario)
    questions = tuple(adapter.question_builder.build_question(scenario, p) for p in range(1, 6))
    return adapter, scenario, rendered, questions


def _test_enabled(adapter):
    # Exercise the shared planner without enabling the production registry.
    adapter.family_registry = tuple(replace(item, enabled=True) for item in adapter.family_registry)
    return adapter


def test_reference_vectors_form_one_grid4_five_question_bundle() -> None:
    adapter, scenario, rendered, questions = _fixture()
    assert tuple(question.family_id for question in questions) == FAMILIES
    assert tuple(question.canonical_answer for question in questions) == EXPECTED_SOURCE_ANSWERS
    assert tuple(question.scenario_seed for question in questions) == (0,) * 5
    assert set(scenario.provenance) == {
        f"https://math-oge.sdamgia.ru/problem?id={source}"
        for sources in SOURCES_BY_POSITION.values()
        for source in sources
    }
    adapter.independent_oracle.validate_bundle(scenario, questions, rendered)


def test_route_diversity_ignores_scene_data_irrelevant_to_the_question() -> None:
    adapter, scenario, _, _ = _fixture(31)
    original = adapter.question_builder.build_question(scenario, 1)
    changed_context = dict(scenario.context)
    changed_context["shopping"] = {"irrelevant": "different market data"}
    unrelated_scene = replace(scenario, context=changed_context)
    changed = adapter.question_builder.build_question(unrelated_scene, 1)
    assert _question_fingerprint(original) == _question_fingerprint(changed)


@pytest.mark.parametrize("position", range(1, 6))
def test_single_mode_keeps_all_five_same_world_questions(position: int) -> None:
    adapter = _test_enabled(build_adapter())
    plan = build_practice_plan(
        PracticeRequest(PracticeMode.SINGLE, seed=0, story_code="ROUTE", position=position),
        FamilyRegistry((adapter,)),
    )
    assert plan.selected_positions == (position,)
    assert tuple(question.family_id for question in plan.snapshot.questions) == FAMILIES
    assert {question.scenario_seed for question in plan.snapshot.questions} == {0}
    assert (
        plan.snapshot.questions[position - 1].canonical_answer
        == EXPECTED_SOURCE_ANSWERS[position - 1]
    )


def test_full_mode_creates_exactly_one_shared_context() -> None:
    adapter = _test_enabled(build_adapter())
    plan = build_practice_plan(
        PracticeRequest(PracticeMode.FULL, seed=0, story_code="ROUTE"), FamilyRegistry((adapter,))
    )
    assert plan.selected_positions == (1, 2, 3, 4, 5)
    assert len(plan.snapshot.questions) == 5
    assert plan.snapshot.context["topology_id"] == "GRID4_RECTANGLE_ROADS_V1"
    assert not any(
        total in plan.snapshot.questions[4].condition for total in ("1134", "1256", "1346", "1272")
    )
    assert "Пересечение диагоналей" in plan.snapshot.shared_context


def test_production_registration_stays_fail_closed_until_visual_audit() -> None:
    adapter = build_adapter()
    assert all(not item.enabled for item in adapter.family_registry)
    assert FamilyRegistry((adapter,)).available_stories(PracticeMode.FULL) == ()
    with pytest.raises(ScenarioUnavailable):
        build_practice_plan(
            PracticeRequest(PracticeMode.FULL, seed=0, story_code="ROUTE"),
            FamilyRegistry((adapter,)),
        )


def test_seed_generation_and_render_are_deterministic() -> None:
    first = _fixture(41)
    second = _fixture(41)
    assert first[1] == second[1]
    assert first[2] == second[2]
    assert first[3] == second[3]


def test_asset_restore_reproduces_svg_and_png_hashes() -> None:
    adapter, _, _, _ = _fixture()
    plan = build_practice_plan(
        PracticeRequest(PracticeMode.FULL, seed=0, story_code="ROUTE"),
        FamilyRegistry((_test_enabled(adapter),)),
    )
    assert {asset.content_type for asset in plan.snapshot.assets} == {"image/svg+xml", "image/png"}
    for asset in plan.snapshot.assets:
        data = restore_asset_bytes(adapter.renderer, plan.snapshot, asset)
        assert sha256(data).hexdigest() == asset.sha256
        if asset.content_type == "image/png":
            assert data.startswith(b"\x89PNG\r\n\x1a\n")
        else:
            assert b'data-edge-id="AB"' in data


def test_250_seed_qa_and_question_fingerprints() -> None:
    adapter = build_adapter()
    oracle = adapter.independent_oracle
    fingerprints: list[set[tuple[str, str]]] = [set() for _ in range(5)]
    for seed in range(250):
        scenario = adapter.generator.generate_scenario(seed + 1)
        oracle.validate_scenario(scenario)
        rendered = adapter.renderer.render_scenario(scenario)
        questions = tuple(adapter.question_builder.build_question(scenario, p) for p in range(1, 6))
        oracle.validate_bundle(scenario, questions, rendered)
        for position, question in enumerate(questions):
            fingerprints[position].add(
                (str(scenario.context), question.condition, question.canonical_answer)
            )
    assert all(len(group) >= 200 for group in fingerprints)


def _expect_question_rejected(position: int, mutate, match: str) -> None:
    adapter, scenario, rendered, questions = _fixture()
    question = mutate(questions[position - 1])
    with pytest.raises(ValueError, match=match):
        adapter.independent_oracle.validate_question(scenario, question, rendered)


@pytest.mark.parametrize(
    ("position", "mutation", "message"),
    [
        (1, lambda q: replace(q, canonical_answer="123"), "answer differs"),  # RM01
        (1, lambda q: replace(q, canonical_answer="222"), "answer differs"),  # RM03
        (2, lambda q: replace(q, solution_steps=("32 + 24 = 57", "длина 56")), "solution"),  # RM10
        (
            3,
            lambda q: replace(q, solution_steps=("Катеты 32,24", "√(32² - 24²) = 40")),
            "solution",
        ),  # RM13
        (
            4,
            lambda q: replace(q, solution_steps=("Длина 56 км", "56/20 = 168 мин")),
            "conversion error",
        ),  # RM14
        (
            4,
            lambda q: replace(q, condition=q.condition.replace("20 км/ч", "15 км/ч")),
            "speed differs",
        ),  # RM15
        (5, lambda q: replace(q, canonical_answer="1"), "answer differs"),  # RM22
    ],
)
def test_question_mutations_are_rejected(position: int, mutation, message: str) -> None:
    _expect_question_rejected(position, mutation, message)


def test_name_mutation_is_rejected() -> None:
    # RM02
    _expect_question_rejected(
        1,
        lambda q: replace(q, condition=q.condition.replace("Камышевка", "Подменная")),
        "name sequence",
    )


def test_route_path_name_mutation_is_rejected() -> None:
    # RM08
    _expect_question_rejected(
        2, lambda q: replace(q, condition=q.condition.replace("Ясная", "Подменная")), "settlement"
    )


def test_table_mutation_is_rejected() -> None:
    # RM20
    adapter, scenario, rendered, questions = _fixture()
    mutated_svg = _svg(scenario.context).replace(b'data-price="417"', b'data-price="418"', 1)
    with pytest.raises(ValueError, match="shopping table"):
        _validate_svg_manifest(mutated_svg, scenario)
    svg_asset = next(asset for asset in rendered.assets if asset.content_type == "image/svg+xml")
    digest = sha256(mutated_svg).hexdigest()
    mutated_asset = replace(svg_asset, sha256=digest, storage_key=f"sha256/{digest}.svg")
    mutated_render = replace(
        rendered,
        assets=tuple(mutated_asset if asset == svg_asset else asset for asset in rendered.assets),
    )
    with pytest.raises(ValueError, match="asset hashes"):
        adapter.independent_oracle.validate_bundle(scenario, questions, mutated_render)


def test_map_description_distance_mutation_is_rejected() -> None:
    # RM07
    adapter, scenario, rendered, questions = _fixture()
    altered = replace(rendered, shared_context=rendered.shared_context.replace("32 км", "23 км"))
    with pytest.raises(ValueError, match="edge lengths"):
        adapter.independent_oracle.validate_question(scenario, questions[1], altered)


def test_topology_road_type_missing_edge_and_scale_mutations_are_rejected() -> None:
    adapter, scenario, _, _ = _fixture()
    edges = [dict(edge) for edge in scenario.context["edges"]]
    broken_edges = [edge for edge in edges if edge["id"] != "AB"]
    with pytest.raises(ValueError, match="topology or type"):
        adapter.independent_oracle.validate_scenario(
            replace(scenario, context={**scenario.context, "edges": broken_edges})
        )
    changed_style = [dict(edge) for edge in edges]
    changed_style[2]["type"] = "highway"
    with pytest.raises(ValueError, match="topology or type"):
        adapter.independent_oracle.validate_scenario(
            replace(scenario, context={**scenario.context, "edges": changed_style})
        )
    with pytest.raises(ValueError, match="scale"):
        adapter.independent_oracle.validate_scenario(
            replace(scenario, context={**scenario.context, "scale_km_per_cell": 9})
        )
    duplicate_labels = [dict(node) for node in scenario.context["nodes"]]
    duplicate_labels[1]["number"] = duplicate_labels[0]["number"]
    with pytest.raises(ValueError, match="bijection"):
        adapter.independent_oracle.validate_scenario(
            replace(scenario, context={**scenario.context, "nodes": duplicate_labels})
        )


def test_svg_label_shift_and_length_scale_mutations_are_rejected() -> None:
    _, scenario, _, _ = _fixture()
    data = _svg(scenario.context)
    # RM11
    moved = data.replace(b'cx="90.00" cy="340.00"', b'cx="91.00" cy="340.00"', 1)
    with pytest.raises(ValueError, match="position"):
        _validate_svg_manifest(moved, scenario)
    changed_scale = data.replace("1 клетка = 1 км".encode(), "1 клетка = 3 км".encode())
    # RM12
    with pytest.raises(ValueError, match="scale caption"):
        _validate_svg_manifest(changed_scale, scenario)
    changed_edge_length = data.replace(b'data-distance-km="32"', b'data-distance-km="23"', 1)
    with pytest.raises(ValueError, match="visible length"):
        _validate_svg_manifest(changed_edge_length, scenario)


def test_shopping_tie_is_rejected() -> None:
    # RM21
    adapter, scenario, _, _ = _fixture()
    shopping = {
        "products": ["P1", "P2", "P3", "P4", "P5"],
        "quantities": [2, 3, 0, 0, 0],
        "stores": [
            {"id": "S1", "prices": [417, 100, 180, 200, 220]},
            {"id": "S2", "prices": [417, 100, 180, 200, 220]},
            {"id": "S3", "prices": [523, 100, 180, 200, 220]},
            {"id": "S4", "prices": [486, 100, 180, 200, 220]},
        ],
    }
    with pytest.raises(ValueError, match="strict minimum"):
        adapter.independent_oracle.validate_scenario(
            replace(scenario, context={**scenario.context, "shopping": shopping})
        )


def test_bundle_seed_and_family_mixing_are_rejected() -> None:
    adapter, scenario, rendered, questions = _fixture()
    mixed_seed = replace(questions[1], scenario_seed=1)
    # RM27
    with pytest.raises(ValueError, match="mix scenario seeds"):
        adapter.independent_oracle.validate_bundle(
            scenario, (questions[0], mixed_seed, *questions[2:]), rendered
        )
    mixed_family = replace(questions[1], family_id="ROUTE-F04-ROAD-DIFF")
    with pytest.raises(ValueError, match="single GRID-4 bundle"):
        adapter.independent_oracle.validate_question(scenario, mixed_family, rendered)


def test_incompatible_candidate_families_remain_unregistered() -> None:
    adapter = build_adapter()
    assert {item.family_id for item in adapter.family_registry} == set(FAMILIES)
    assert {item.family_id for item in adapter.family_registry}.isdisjoint(
        {
            "ROUTE-F02-VILLAGE-MATCH",
            "ROUTE-F04-ROAD-DIFF",
            "ROUTE-F07-DIRECT-TIME",
            "ROUTE-F08-MIXED-TIME",
            "ROUTE-F10-FUEL-BALANCE",
        }
    )


@pytest.mark.parametrize(
    ("family_id", "position"),
    [
        ("ROUTE-F02-VILLAGE-MATCH", 1),  # RM04–RM06
        ("ROUTE-F04-ROAD-DIFF", 2),  # RM09
        ("ROUTE-F07-DIRECT-TIME", 4),  # RM16
        ("ROUTE-F08-MIXED-TIME", 4),  # RM17–RM19
        ("ROUTE-F10-FUEL-BALANCE", 5),  # RM23–RM26
    ],
)
def test_unverified_or_incompatible_mutations_fail_closed(family_id: str, position: int) -> None:
    adapter, scenario, rendered, questions = _fixture()
    assert family_id not in {item.family_id for item in adapter.family_registry}
    altered = replace(questions[position - 1], family_id=family_id)
    with pytest.raises(ValueError, match="single GRID-4 bundle"):
        adapter.independent_oracle.validate_question(scenario, altered, rendered)


def test_map_label_and_unavailable_path_mutations_are_rejected() -> None:
    # RM01 changes the rendered label while leaving the answer key unchanged.
    adapter, scenario, rendered, questions = _fixture()
    nodes = [dict(node) for node in scenario.context["nodes"]]
    nodes[0]["number"], nodes[1]["number"] = nodes[1]["number"], nodes[0]["number"]
    relabeled = replace(scenario, context={**scenario.context, "nodes": nodes})
    with pytest.raises(ValueError, match="answer differs"):
        adapter.independent_oracle.validate_question(relabeled, questions[0], rendered)

    # A route through an unnamed or absent intermediate point fails the text oracle.
    changed_route = replace(
        questions[1], condition=questions[1].condition.replace("Ясная", "Луговая")
    )
    with pytest.raises(ValueError, match="settlement"):
        adapter.independent_oracle.validate_question(scenario, changed_route, rendered)


def test_visible_road_type_and_rendered_asset_mutations_are_rejected() -> None:
    adapter, scenario, rendered, _ = _fixture()
    wrong_style = _svg(scenario.context).replace(
        b'data-edge-id="AC" data-road-type="dirt"',
        b'data-edge-id="AC" data-road-type="highway"',
        1,
    )
    with pytest.raises(ValueError, match="road style"):
        _validate_svg_manifest(wrong_style, scenario)

    altered = replace(
        rendered,
        assets=(
            replace(rendered.assets[0], sha256="0" * 64, storage_key=f"sha256/{'0' * 64}.svg"),
            rendered.assets[1],
        ),
    )
    adapter.independent_oracle.validate_scenario(scenario)
    with pytest.raises(ValueError, match="asset hashes"):
        adapter.independent_oracle.validate_bundle(
            scenario,
            tuple(adapter.question_builder.build_question(scenario, p) for p in range(1, 6)),
            altered,
        )


def test_wrong_restored_asset_bytes_are_rejected() -> None:
    adapter, _, _, _ = _fixture()
    plan = build_practice_plan(
        PracticeRequest(PracticeMode.FULL, seed=0, story_code="ROUTE"),
        FamilyRegistry((_test_enabled(adapter),)),
    )

    class WrongRenderer:
        def restore_asset(self, snapshot, asset):
            return b"altered bytes"

    with pytest.raises(ValueError, match="digest does not match"):
        restore_asset_bytes(WrongRenderer(), plan.snapshot, plan.snapshot.assets[0])


def test_vector_reference_full_block_can_be_restored() -> None:
    adapter = _test_enabled(build_adapter())
    plan = build_practice_plan(
        PracticeRequest(PracticeMode.FULL, seed=0, story_code="ROUTE"), FamilyRegistry((adapter,))
    )
    snapshot = ScenarioSnapshot.from_snapshot(plan.snapshot.to_snapshot())
    assert snapshot == plan.snapshot
    for asset in snapshot.assets:
        assert restore_asset_bytes(adapter.renderer, snapshot, asset)
