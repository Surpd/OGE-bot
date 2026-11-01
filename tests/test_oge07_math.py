from __future__ import annotations

import base64
import re
from dataclasses import replace

import pytest

from app.math.numbers import FAMILIES, POLICY, audit_condition, generate
from app.math.oge07_graph import (
    GRAPH_SOURCES,
    audit_graph_problem,
    audit_png,
    generate_graph_problem,
    projection,
)
from app.math.oge07_scheduler import ENABLED_FAMILIES, build_task7_candidate_batch


@pytest.mark.parametrize("family", FAMILIES)
def test_generation_is_deterministic_and_has_four_options(family: str) -> None:
    one = generate(family, 713)
    assert one == generate(family, 713)
    assert len(one.options) == 4
    assert len(set(one.options)) == 4
    assert one.correct_option_index in range(1, 5)
    assert one.to_snapshot()["answer_policy_id"] == POLICY.policy_id
    assert one.to_snapshot()["content_provenance"] == "generated_analogue"


@pytest.mark.parametrize("family", FAMILIES)
def test_generation_has_diverse_fingerprints(family: str) -> None:
    assert len({generate(family, seed).fingerprint for seed in range(250)}) >= 200


@pytest.mark.parametrize("family", FAMILIES)
def test_independent_visible_condition_oracle(family: str) -> None:
    for seed in range(250):
        problem = generate(family, seed)
        assert audit_condition(
            family, problem.condition, problem.options, problem.correct_option_index
        )
        assert not audit_condition(
            family, problem.condition + "?", problem.options, problem.correct_option_index
        )
        wrong = problem.correct_option_index % 4 + 1
        assert not audit_condition(family, problem.condition, problem.options, wrong)
        mutated_options = list(problem.options)
        correct_slot = problem.correct_option_index - 1
        mutated_options[correct_slot] = re.sub(
            r"-?\d+", "9999999", mutated_options[correct_slot], count=1
        )
        assert not audit_condition(
            family, problem.condition, mutated_options, problem.correct_option_index
        )
        assert not audit_condition(
            family,
            problem.condition.replace("?", "!"),
            problem.options,
            problem.correct_option_index,
        )


def test_historical_families_are_not_generator_targets() -> None:
    with pytest.raises(ValueError):
        generate("OGE07-H03", 1)


def test_all_families_are_closed_until_acceptance_and_scheduler_fails_closed() -> None:
    assert ENABLED_FAMILIES == ()
    assert build_task7_candidate_batch({}, 1) == []


def test_graph_snapshot_restores_identical_png_and_answer() -> None:
    problem = generate_graph_problem("OGE07-N01", 104)
    snapshot = problem.to_snapshot()
    restored_png = base64.b64decode(str(snapshot["graph_png_base64"]))
    assert restored_png == problem.png
    assert snapshot["graph_model"] == problem.graph_model
    assert snapshot["correct_answer"] == str(problem.correct_option_index)


@pytest.mark.parametrize("family", tuple(GRAPH_SOURCES))
def test_graph_problem_semantics_png_and_determinism(family: str) -> None:
    first = generate_graph_problem(family, 104)
    assert first == generate_graph_problem(family, 104)
    assert audit_graph_problem(first)
    assert audit_png(first.graph_model, first.png)
    assert set(first.reference_ids) == set(GRAPH_SOURCES[family])
    positions = projection(first.graph_model)
    assert all(72 <= x < first.graph_model["width"] - 72 for x in positions.values())
    assert len(set(positions.values())) == len(positions)


@pytest.mark.parametrize("family", tuple(GRAPH_SOURCES))
def test_graph_mutations_are_rejected(family: str) -> None:
    problem = generate_graph_problem(family, 288)
    mutated_model = dict(problem.graph_model)
    mutated_model["correct_option_index"] = problem.correct_option_index % 4 + 1
    assert not audit_graph_problem(replace(problem, graph_model=mutated_model))
    mutated_model = dict(problem.graph_model)
    mutated_points = [dict(point) for point in problem.graph_model["points"]]
    mutated_points[0]["label"] = "Z"
    mutated_model["points"] = mutated_points
    assert not audit_png(mutated_model, problem.png)
