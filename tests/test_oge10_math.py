import json
import random
from collections import Counter
from dataclasses import replace
from fractions import Fraction
from pathlib import Path

import pytest

from app.math.oge10_scheduler import build_task10_candidate_batch
from app.math.probability import (
    ANSWER_POLICY,
    ENABLED_FAMILIES,
    generate,
    solve_rendered_condition,
    validate_rendered_problem,
)


@pytest.mark.parametrize("family_id", ENABLED_FAMILIES)
def test_enabled_probability_families_are_exact_rendered_and_diverse(family_id: str) -> None:
    rng = random.Random(f"quality:{family_id}")
    problems = [generate(family_id, rng.randrange(2**63)) for _ in range(250)]
    assert all(validate_rendered_problem(problem) for problem in problems)
    assert all(solve_rendered_condition(problem) == problem.answer for problem in problems)
    assert all(
        problem.answer == ANSWER_POLICY.parse(problem.correct_answer) for problem in problems
    )
    seen = {problem.fingerprint for problem in problems}
    while len(seen) < 200 and len(problems) < 1200:
        problems.append(generate(family_id, rng.randrange(2**63)))
        seen.add(problems[-1].fingerprint)
    assert len(seen) >= 200 and len(problems) <= 1200


def test_probability_generation_is_deterministic_and_identity_is_seeded() -> None:
    first = generate(ENABLED_FAMILIES[0], 4401)
    second = generate(ENABLED_FAMILIES[0], 4401)
    assert first == second
    assert first.seed == 4401
    assert first.problem_id == second.problem_id


def test_scheduler_rotates_structural_families_and_avoids_recent_fingerprints() -> None:
    state: dict[str, object] = {}
    issued: list[dict[str, object]] = []
    for index in range(len(ENABLED_FAMILIES)):
        candidates = build_task10_candidate_batch(state, 7812 + index)
        assert candidates
        selected = candidates[0]
        issued.append(selected)
        state = {
            "family_queue": selected["_family_queue_after"],
            "recent_fingerprints": [item["fingerprint"] for item in issued],
            "last_family_id": selected["_last_family_after"],
        }
    families = [str(item["family_id"]) for item in issued]
    assert len(set(families)) == len(ENABLED_FAMILIES)
    assert all(left != right for left, right in zip(families, families[1:], strict=False))


def test_answer_distribution_is_bounded_exact_and_reportable() -> None:
    rng = random.Random("oge10-answer-distribution")
    generated = [
        generate(family, rng.randrange(2**63)) for family in ENABLED_FAMILIES for _ in range(250)
    ]
    values = [problem.answer for problem in generated]
    places = Counter(values)
    assert len(values) == 1500
    assert all(isinstance(value, Fraction) and 0 <= value <= 1 for value in places)
    assert all(
        ANSWER_POLICY.parse(problem.correct_answer) == problem.answer for problem in generated
    )


def test_unconfirmed_probability_families_remain_disabled() -> None:
    for family_id in ("OGE10-F003", "OGE10-F004", "OGE10-F005"):
        with pytest.raises(ValueError, match="not enabled"):
            generate(family_id, 1)


def test_known_task_311525_is_a_single_category_not_a_union() -> None:
    from app.math.probability import DISJOINT_UNION, DRAW_CATEGORY, SOURCE_IDS

    assert "311525" in SOURCE_IDS[DRAW_CATEGORY]
    assert "311525" not in SOURCE_IDS[DISJOINT_UNION]
    sample = next(generate(DRAW_CATEGORY, seed) for seed in range(250))
    assert sample.event["kind"] == "has"


def test_rendered_text_mutations_are_rejected_by_independent_oracle() -> None:
    problem = generate(ENABLED_FAMILIES[0], 8321)
    total = len(problem.sample_space)
    mutated_total = replace(
        problem, condition=problem.condition.replace(str(total), str(total + 1), 1)
    )
    assert not validate_rendered_problem(mutated_total)
    target_word = next(
        word for word in ("красную", "синюю", "зелёную") if word in problem.condition
    )
    wrong_target = next(word for word in ("красную", "синюю", "зелёную") if word != target_word)
    mutated_event = replace(
        problem,
        condition=problem.condition.replace(target_word, wrong_target, 1),
    )
    assert not validate_rendered_problem(mutated_event)


def test_source_registry_maps_every_enabled_family_to_concrete_examples() -> None:
    path = Path(__file__).resolve().parents[1] / "atlas" / "oge10_reference_structures.json"
    registry = json.loads(path.read_text(encoding="utf-8"))
    enabled = {item["family_id"]: item for item in registry["enabled"]}
    assert len(enabled) == len(ENABLED_FAMILIES)
    for family_id in ENABLED_FAMILIES:
        assert enabled[family_id]["examples"]
        assert enabled[family_id]["structure"]
        assert enabled[family_id]["generator"]
