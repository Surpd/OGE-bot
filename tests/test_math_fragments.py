from html import unescape

import pytest

from app.bot.math_fragments import (
    Comparison,
    Fraction,
    Interval,
    MathToken,
    Operation,
    Power,
    Progression,
    Root,
    System,
)
from app.bot.presentation import render_math_fragment


def token(text):
    return MathToken(text)


def test_nested_fraction_groups_denominator_and_negative_operands():
    expression = Fraction(token("−3,5"), Fraction(token("1"), token("2")))
    assert expression.unicode() == "(−3,5)/((1)/(2))"
    assert expression.latex() == r"\frac{\text{−3,5}}{\frac{\text{1}}{\text{2}}}"
    assert expression.numerator.text == "−3,5"
    assert expression.denominator.numerator.text == "1"


def test_powers_distinguish_negative_base_and_power_of_a_power():
    assert Power(token("−3"), token("2")).unicode() == "(−3)²"
    nested = Power(Power(token("x"), token("2")), token("3"))
    assert nested.unicode() == "((x)²)³"
    assert nested.latex() == r"\left(\left(\text{x}\right)^{\text{2}}\right)^{\text{3}}"
    assert Power(token("x + 1"), Fraction(token("1"), token("2"))).unicode() == (
        "(x + 1)^((1)/(2))"
    )


def test_root_retains_entire_radicand_and_index():
    assert Root(Operation(token("x"), "+", token("1"))).unicode() == "√((x) + (1))"
    cube = Root(Fraction(token("8"), token("27")), token("3"))
    assert cube.unicode() == "³√((8)/(27))"
    assert cube.latex() == r"\sqrt[\text{3}]{\frac{\text{8}}{\text{27}}}"
    assert Root(token("x"), token("n")).unicode() == "√[n](x)"


def test_comparison_system_and_interval_keep_open_closed_endpoints():
    lower = Comparison(token("x"), ">", token("−2"))
    upper = Comparison(token("x"), "≤", token("3"))
    system = System((lower, upper))
    assert system.unicode() == "{ x > −2\n  x ≤ 3"
    assert system.latex() == (
        r"\begin{cases}\text{x} > \text{−2} \\ \text{x} \le \text{3}\end{cases}"
    )
    interval = Interval(token("−2"), token("3"), upper_closed=True)
    assert interval.unicode() == "(−2; 3]"
    assert interval.latex() == r"(\text{−2}; \text{3}]"
    assert unescape(render_math_fragment(lower)) == lower.unicode()
    assert "&gt;" in render_math_fragment(lower)


def test_arithmetic_progression_groups_negative_difference_without_evaluation():
    progression = Progression(token("1,5"), token("−2"), token("n"))
    assert progression.unicode() == "aₙ = (1,5) + ((n) − 1) × (−2)"
    assert progression.latex() == (
        r"a_{\text{n}} = \left(\text{1,5}\right) + "
        r"\left((\text{n}) - 1\right) \cdot \left(\text{−2}\right)"
    )
    assert Progression(token("2"), token("3"), token("4")).unicode().startswith("a[4] =")


@pytest.mark.parametrize("text", ["−0,50", "a_1", "x^2", r"\frac{a}{b}", "1 < 2 & 3", "α β"])
def test_literal_tokens_are_exact_and_latex_is_not_executed(text):
    original = token(text)
    assert original.unicode() == text
    assert unescape(render_math_fragment(original)) == text
    assert original.latex().startswith(r"\text{")
    if "\\" in text:
        assert r"\textbackslash{}" in original.latex()
        assert r"\frac" not in original.latex()


def test_unsupported_operators_and_empty_system_fail_closed():
    with pytest.raises(ValueError):
        Comparison(token("x"), "==", token("1"))
    with pytest.raises(ValueError):
        Operation(token("x"), "eval", token("1"))
    with pytest.raises(ValueError):
        System(())


@pytest.mark.asyncio
async def test_explicit_math_node_can_be_sent_without_latex_transport():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from app.bot.presentation import send_text

    message = SimpleNamespace(from_user=None, answer=AsyncMock())
    expression = Comparison(Fraction(token("1"), token("2")), "<", token("1"))
    await send_text(message, AsyncMock(), expression)
    message.answer.assert_awaited_once_with("(1)/(2) &lt; 1", parse_mode="HTML")
