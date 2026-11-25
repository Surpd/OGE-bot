from __future__ import annotations

import pytest

from app.math.scenarios.stories import PAPER, ROUTE, TARIFF, TYRES


@pytest.mark.parametrize(
    ("module", "enabled"),
    [
        (TYRES, frozenset(f.family_id for f in TYRES._FAMILIES if f.position <= 5)),
        (PAPER, frozenset(PAPER._SOURCE_IDS)),
        (TARIFF, frozenset(TARIFF.IMPLEMENTED_FAMILIES)),
    ],
)
def test_public_story_questions_keep_family_provenance_and_complete_worked_help(
    module, enabled: frozenset[str]
) -> None:
    adapter = module.build_adapter(enabled_families=enabled)
    registrations = {item.family_id: item for item in adapter.family_registry}
    scenario = adapter.generator.generate_scenario(37)
    rendered = adapter.renderer.render_scenario(scenario)

    assert rendered.shared_context.strip()
    assert scenario.provenance
    for position in range(1, 6):
        question = adapter.question_builder.build_question(scenario, position)
        registration = registrations[question.family_id]
        assert tuple(question.math_model["source_ids"]) == registration.source_ids
        assert question.math_model["content_kind"] == "generated_analogue"
        assert len(question.hints) >= 2
        assert question.solution_steps
        assert question.canonical_answer in question.solution_steps[-1]
        adapter.independent_oracle.validate_question(scenario, question, rendered)


@pytest.mark.parametrize(
    ("module", "enabled", "expected"),
    [
        (
            PAPER,
            frozenset(PAPER._SOURCE_IDS),
            {"header": "Формат", "row": "Номер строки"},
        ),
        (
            TARIFF,
            frozenset(TARIFF.IMPLEMENTED_FAMILIES),
            {"header": "Расход", "row": "Номер месяца"},
        ),
    ],
)
def test_public_matching_answer_grid_has_labels_but_never_the_answer(
    module, enabled: frozenset[str], expected: dict[str, str]
) -> None:
    adapter = module.build_adapter(enabled_families=enabled)
    question = adapter.question_builder.build_question(adapter.generator.generate_scenario(19), 1)
    grid = question.math_model["answer_grid"]

    assert grid["header"] == expected["header"]
    assert grid["row"] == expected["row"]
    assert len(grid["columns"]) >= 3
    assert set(grid) == {"columns", "header", "row"}
    assert "без" in question.condition.lower() or "код" in question.condition.lower()


def test_route_matching_grid_is_complete_but_story_remains_publicly_excluded() -> None:
    adapter = ROUTE.build_adapter()
    assert not any(item.available for item in adapter.family_registry)
    scenario = adapter.generator.generate_scenario(0)
    question = adapter.question_builder.build_question(scenario, 1)
    grid = question.math_model["answer_grid"]

    assert grid["header"] == "Посёлок"
    assert grid["row"] == "Цифра на схеме"
    assert tuple(grid["columns"]) == tuple(question.math_model["ordered_names"])
    assert set(grid) == {"columns", "header", "row"}
    assert question.math_model["visual_audit"] == "source_mismatch_publicly_excluded"


def test_materials_are_shared_context_and_question_wording_stays_separate() -> None:
    tariff = TARIFF.build_adapter(enabled_families=frozenset(TARIFF.IMPLEMENTED_FAMILIES))
    scenario = tariff.generator.generate_scenario(11)
    rendered = tariff.renderer.render_scenario(scenario)
    conditions = tuple(
        tariff.question_builder.build_question(scenario, position).condition
        for position in range(1, 6)
    )

    assert "отдельной приложенной таблице" in rendered.shared_context
    assert "задании №5" not in rendered.shared_context
    assert all(condition not in rendered.shared_context for condition in conditions)
    assert len(rendered.assets) == 2
