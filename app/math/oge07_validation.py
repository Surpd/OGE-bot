"""Fail-closed validation for persisted OGE-7 problem snapshots."""

from __future__ import annotations

import base64
from typing import cast

from app.math.numbers import (
    FAMILIES as TEXT_FAMILIES,
)
from app.math.numbers import (
    GENERATOR_VERSION as TEXT_GENERATOR_VERSION,
)
from app.math.numbers import (
    POLICY,
    audit_condition,
    generate,
)
from app.math.oge07_graph import (
    GENERATOR_VERSION as GRAPH_GENERATOR_VERSION,
)
from app.math.oge07_graph import (
    GRAPH_SOURCES,
    GraphModel,
    GraphProblem,
    audit_graph_problem,
    generate_graph_problem,
)


def _json_shape(value: object) -> object:
    if isinstance(value, dict):
        return {key: _json_shape(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_json_shape(item) for item in value]
    return value


def _matches_expected(snapshot: dict[str, object], expected: dict[str, object]) -> bool:
    return all(
        _json_shape(snapshot.get(key)) == _json_shape(value) for key, value in expected.items()
    )


def validate_task7_snapshot(value: object) -> bool:
    """Validate stored task content, answer policy, solution and graph pixels."""
    if not isinstance(value, dict):
        return False
    snapshot = cast(dict[str, object], value)
    family = snapshot.get("family_id")
    seed = snapshot.get("seed")
    if not isinstance(family, str) or type(seed) is not int:
        return False
    if (
        snapshot.get("content_provenance") != "generated_analogue"
        or snapshot.get("answer_policy_id") != POLICY.policy_id
        or snapshot.get("answer_policy_version") != POLICY.version
    ):
        return False
    options = snapshot.get("options")
    answer_index = snapshot.get("correct_option_index")
    if (
        not isinstance(options, list)
        or len(options) != 4
        or any(not isinstance(option, str) or not option.strip() for option in options)
        or len(set(options)) != 4
        or type(answer_index) is not int
        or answer_index not in range(1, 5)
        or snapshot.get("correct_answer") != str(answer_index)
    ):
        return False
    try:
        if family in TEXT_FAMILIES:
            if snapshot.get("generator_version") != TEXT_GENERATOR_VERSION:
                return False
            expected = generate(family, seed, TEXT_GENERATOR_VERSION).to_snapshot()
            return audit_condition(
                family, str(snapshot.get("condition", "")), options, answer_index
            ) and _matches_expected(snapshot, expected)
        if family not in GRAPH_SOURCES:
            return False
        if snapshot.get("generator_version") != GRAPH_GENERATOR_VERSION:
            return False
        png_value = snapshot.get("graph_png_base64")
        model_value = snapshot.get("graph_model")
        if not isinstance(png_value, str) or not isinstance(model_value, dict):
            return False
        png = base64.b64decode(png_value, validate=True)
        graph = GraphProblem(
            problem_id=str(snapshot.get("problem_id", "")),
            family_id=family,
            seed=seed,
            reference_ids=tuple(cast(list[str], snapshot.get("reference_ids", []))),
            condition=str(snapshot.get("condition", "")),
            options=cast(tuple[str, str, str, str], tuple(cast(list[str], options))),
            correct_option_index=answer_index,
            graph_model=cast(GraphModel, model_value),
            png=png,
            png_sha256=str(snapshot.get("graph_png_sha256", "")),
            hints=tuple(cast(list[str], snapshot.get("hints", []))),
            solution=tuple(cast(list[str], snapshot.get("solution", []))),
        )
        expected = generate_graph_problem(family, seed).to_snapshot()
        return audit_graph_problem(graph) and _matches_expected(snapshot, expected)
    except Exception:
        return False
