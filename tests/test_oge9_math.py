import re
from fractions import Fraction
from itertools import groupby

import pytest

from app.math.equations import (
    ENABLED_FAMILIES,
    generate_equation,
    k6_parameter_domain,
    solve_rendered_equation,
    validate_rendered_problem,
)
from app.math.oge9_scheduler import _deck


@pytest.mark.parametrize("family_id", ENABLED_FAMILIES)
def test_equation_generator_is_deterministic_and_rendered_equation_has_exact_roots(
    family_id: str,
) -> None:
    for seed in range(300):
        problem = generate_equation(family_id, seed)
        assert problem.to_snapshot() == generate_equation(family_id, seed).to_snapshot()
        assert solve_rendered_equation(problem.equation_text) == problem.roots
        expected = max(problem.roots) if problem.answer_target == "greater" else min(problem.roots)
        assert problem.target_root == expected
        validate_rendered_problem(problem)


@pytest.mark.parametrize("family_id", ENABLED_FAMILIES)
def test_each_enabled_template_reaches_200_distinct_equations_within_budget(
    family_id: str,
) -> None:
    fingerprints: set[str] = set()
    for seed in range(1200):
        problem = generate_equation(family_id, seed)
        validate_rendered_problem(problem)
        fingerprints.add(problem.fingerprint)
    assert len(fingerprints) >= 200


def test_zero_negative_fractional_and_equal_quadratic_roots_are_handled() -> None:
    # The enabled quadratic structures use all roots internally, even when the
    # visible answer policy asks for the smaller one.
    zero_root = generate_equation("OGE09-K6", 3)
    assert zero_root.roots[0] < 0 < zero_root.roots[-1]
    assert solve_rendered_equation(zero_root.equation_text) == zero_root.roots

    linear_zero = next(
        problem
        for problem in (generate_equation("OGE09-L1", seed) for seed in range(200))
        if problem.target_root == 0
    )
    assert solve_rendered_equation(linear_zero.equation_text) == (Fraction(0),)

    fractional = next(
        problem
        for problem in (generate_equation("OGE09-L1", seed) for seed in range(100))
        if problem.target_root.denominator != 1
    )
    assert fractional.correct_answer.replace(",", ".")
    assert solve_rendered_equation(fractional.equation_text) == (fractional.target_root,)

    quadratic_fraction = next(
        problem
        for problem in (generate_equation("OGE09-K3", seed) for seed in range(200))
        if any(root.denominator > 1 for root in problem.roots)
    )
    assert solve_rendered_equation(quadratic_fraction.equation_text) == quadratic_fraction.roots
    assert quadratic_fraction.answer_target == "lesser"


def test_greater_root_hint_matches_the_displayed_answer_target() -> None:
    problem = generate_equation("OGE09-K2", 2)
    assert problem.answer_target == "greater"
    assert "больший" in problem.hints[1]


def test_task9_solutions_choose_a_method_that_matches_the_equation() -> None:
    vieta = generate_equation("OGE09-K2", 2)
    assert any("Виета" in step for step in vieta.solution)
    assert not any("Дискриминант" in step for step in vieta.solution)

    quadratic = generate_equation("OGE09-K3", 2)
    assert any("Коэффициенты: a =" in step for step in quadratic.solution)
    assert any("D = b² − 4ac" in step for step in quadratic.solution)
    assert any("x₁,₂ =" in step for step in quadratic.solution)

    incomplete = generate_equation("OGE09-K6", 3)
    assert any("x² =" in step for step in incomplete.solution)
    assert any("x = ±" in step for step in incomplete.solution)
    assert not any("D =" in step for step in incomplete.solution)

    grouped = generate_equation("OGE09-L4A", 4)
    assert any("Раскроем скобки" in step for step in grouped.solution)
    linear = generate_equation("OGE09-L1", 4)
    assert any("Запишем уравнение" in step for step in linear.solution)


@pytest.mark.parametrize("family_id", ENABLED_FAMILIES)
def test_task9_solution_has_no_malformed_coefficient_terms(family_id: str) -> None:
    for seed in range(20):
        solution = " ".join(generate_equation(family_id, seed).solution)
        assert re.search(r"\b0x(?:²)?\b", solution) is None
        assert re.search(r"\b1x(?:²)?\b", solution) is None
        assert re.search(r"\+\s+-", solution) is None
        assert "\\frac" not in solution


def test_catalog_grouping_prototypes_have_separate_visible_generators() -> None:
    from app.math.equations import solve_rendered_equation

    assert solve_rendered_equation("2 - 3(2x + 2) = 5 - 4x") == (Fraction(-9, 2),)
    assert solve_rendered_equation("-x - 2 + 3(x - 3) = 3(4 - x) - 3") == (Fraction(4),)
    one_group = generate_equation("OGE09-L4A", 123)
    two_groups = generate_equation("OGE09-L4B", 123)
    assert one_group.reference_ids == ("85",)
    assert two_groups.reference_ids == ("338495",)
    assert one_group.equation_text.count("(") == 1
    assert two_groups.equation_text.count("(") == 2
    validate_rendered_problem(one_group)
    validate_rendered_problem(two_groups)


def test_degenerate_and_unapproved_historical_types_stay_disabled() -> None:
    with pytest.raises(KeyError):
        generate_equation("OGE09-K1", 1)
    with pytest.raises(KeyError):
        generate_equation("OGE09-K4", 1)
    with pytest.raises(ValueError, match="degenerate"):
        from app.math.equations import Equation, Number, solve_equation

        equation = Equation(Number(Fraction(0)), Number(Fraction(0)))
        solve_equation(equation)
    with pytest.raises(ValueError, match="no exact real"):
        solve_rendered_equation("x² + 1 = 0")


def test_task9_schedule_balances_groups_without_strict_alternation_or_long_runs() -> None:
    for seed in range(100):
        deck = _deck(seed)
        linear = [family for family in deck if family.startswith("OGE09-L")]
        quadratic = [family for family in deck if family.startswith("OGE09-K")]
        assert len(linear) == len(quadratic) == 4
        groups = ["linear" if family.startswith("OGE09-L") else "quadratic" for family in deck]
        assert any(left == right for left, right in zip(groups, groups[1:], strict=False))
        assert max(len(list(run)) for _, run in groupby(groups)) <= 3
        assert all(left != right for left, right in zip(deck, deck[1:], strict=False))


def test_task9_schedule_respects_saved_group_run_at_deck_boundary() -> None:
    for seed in range(100):
        deck = _deck(seed, last_group="linear", group_run_length=2)
        groups = ["linear" if family.startswith("OGE09-L") else "quadratic" for family in deck]
        whole = ["linear", "linear", *groups]
        run_length = 0
        previous = None
        for group in whole:
            run_length = run_length + 1 if group == previous else 1
            previous = group
            assert run_length <= 3


def test_k6_exact_fingerprint_domain_is_limited_but_exceeds_acceptance_floor() -> None:
    domain = k6_parameter_domain()
    assert len(set(domain)) == 212
    assert len(domain) >= len(set(domain))
    for value, coefficient in domain:
        constant = coefficient * value * value
        assert value in range(1, 13)
        assert coefficient > 0
        assert constant.denominator == 1 and constant <= 196
