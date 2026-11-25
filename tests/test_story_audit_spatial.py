from __future__ import annotations

from dataclasses import replace

from app.bot.scenario_materials import scenario_context_for_question
from app.bot.scenario_training import public_registry
from app.math.scenario_engine import PracticeMode, PracticeRequest, build_practice_plan
from app.math.scenarios.mobile_photos import garden_plan
from app.math.scenarios.stories import FLAT, GARDEN, STOVE


def _bundle(adapter, seed: int = 17):
    scenario = adapter.generator.generate_scenario(seed)
    rendered = adapter.renderer.render_scenario(scenario)
    questions = tuple(adapter.question_builder.build_question(scenario, n) for n in range(1, 6))
    adapter.independent_oracle.validate_bundle(scenario, questions, rendered)
    return scenario, rendered, questions


def test_garden_shared_story_makes_single_geometry_questions_determinate() -> None:
    scenario, rendered, questions = _bundle(GARDEN.build_adapter())
    assert scenario.generator_version == "garden-sosnovka-1.6"
    assert "Единственные ворота" in rendered.shared_context
    assert "слева находится гараж" in rendered.shared_context
    assert "теплица расположена внутри огорода" in rendered.shared_context
    assert "единственных ворот" not in questions[0].condition
    assert questions[0].math_model["answer_grid"] == {
        "columns": ("Жилой дом", "Баня", "Гараж", "Теплица"),
        "header": "Объект",
        "row": "Цифра на плане",
    }
    assert "внешнего контура" in questions[2].condition


def test_released_garden_snapshot_keeps_its_geometry_and_can_reopen_perimeter() -> None:
    current = build_practice_plan(
        PracticeRequest(PracticeMode.FULL, 27, "GARDEN"), public_registry(),
    ).snapshot
    old_version = "garden-sosnovka-1.5"
    archived = replace(
        current, generator_version=old_version,
        context={**current.context, "world_version": old_version},
        shared_context="План участка: клетка 2 м; дорожки шириной 1 м. Плитка 1×1 м.",
    )
    before = archived.to_snapshot()
    assert GARDEN._svg(current.context) == GARDEN._svg(archived.context)
    assert garden_plan(current) == garden_plan(archived)
    assert "здание с выступом" in scenario_context_for_question(archived, 3)
    assert archived.to_snapshot() == before


def test_flat_narrative_is_shared_once_and_matching_grid_is_blank() -> None:
    scenario, rendered, questions = _bundle(FLAT.build_adapter())
    assert scenario.generator_version == "flat-grid-2.2.0"
    q1 = questions[0]
    assert "Слева от входа" not in q1.condition
    assert "санузел слева от входа" in rendered.shared_context.casefold()
    assert q1.math_model["answer_grid"] == {
        "columns": ("Санузел", "Кладовая", "Спальня", "Гостиная"),
        "header": "Помещение",
        "row": "Цифра на плане",
    }
    assert q1.canonical_answer not in str(q1.math_model["answer_grid"])


def test_stove_shared_material_states_purpose_inclusive_ranges_and_catalog() -> None:
    scenario, rendered, questions = _bundle(STOVE.build_adapter())
    assert scenario.generator_version == "stove-v1.5"
    assert "когда объём равен одной из границ диапазона" in rendered.shared_context
    assert "цена каждой модели без дополнительных услуг" in rendered.shared_context
    assert rendered.shared_context.count("Печь | Тип") == 1
    assert "Размеры парной" not in questions[1].condition
    assert questions[4].math_model["width_cm"] > 0
    assert questions[4].math_model["height_cm"] > 0
