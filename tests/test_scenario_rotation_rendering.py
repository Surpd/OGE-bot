from dataclasses import replace
from random import Random

import pytest

from app.math.scenario_engine import (
    FamilyRegistry,
    PracticeMode,
    PracticeRequest,
    build_practice_plan,
)
from app.math.scenarios.recent_questions import question_signature, rotated_plan
from app.math.scenarios.stories.GARDEN import FAMILIES, build_adapter


@pytest.mark.parametrize("mode", [PracticeMode.FULL, PracticeMode.SINGLE])
@pytest.mark.parametrize("all_seen", [False, True])
def test_rotation_renders_only_the_selected_world(monkeypatch, mode, all_seen):
    adapter = build_adapter(enabled_families=frozenset(FAMILIES))
    registry = FamilyRegistry((adapter,))
    request = PracticeRequest(mode, 3)
    rng = Random(request.seed)
    candidates = [
        build_practice_plan(replace(request, seed=seed), registry)
        for seed in [request.seed, *(rng.getrandbits(63) for _ in range(4))]
    ]
    recent = frozenset(
        question_signature(plan.snapshot, plan.snapshot.questions[position - 1])
        for plan in (candidates if all_seen else candidates[:1])
        for position in plan.selected_positions
    )
    expected = min(
        candidates,
        key=lambda plan: sum(
            question_signature(plan.snapshot, plan.snapshot.questions[pos - 1]) in recent
            for pos in plan.selected_positions
        ),
    )
    rendered_seeds = []
    validated_seeds = []
    render = adapter.renderer.render_scenario
    validate = adapter.independent_oracle.validate_bundle

    def render_selected(scenario):
        rendered_seeds.append(scenario.seed)
        return render(scenario)

    def validate_selected(scenario, questions, rendered):
        validate(scenario, questions, rendered)
        validated_seeds.append(scenario.seed)

    monkeypatch.setattr(adapter.renderer, "render_scenario", render_selected)
    monkeypatch.setattr(adapter.independent_oracle, "validate_bundle", validate_selected)
    assert rotated_plan(request, registry, [], recent) == expected
    assert rendered_seeds == validated_seeds == [expected.snapshot.seed]
