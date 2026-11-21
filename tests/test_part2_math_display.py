import io
import json
from pathlib import Path

import pytest
from PIL import Image

from app.bot.explicit_math import formulas, plain_text
from app.bot.math_image import _explicit_formula, render_math_image
from app.bot.math_notation import math_spans, rich_needs_png_fallback
from app.bot.part2 import solution_text, statement_text
from app.bot.presentation import format_math_message, format_rich_message

BANK = Path("atlas/part2/tasks.jsonl")


@pytest.mark.parametrize(
    "source_id",
    ["311619", "438301", "338408", "340341", "311249", "341367", "338951", "340359"],
)
def test_real_card_math_rich_or_png_never_displays_delimiters(source_id):
    cards = (json.loads(line) for line in BANK.read_text().splitlines())
    card = next(row for row in cards if row["source_id"] == source_id)
    for message in (statement_text(card), solution_text(card)):
        rich = format_rich_message(message)
        plain = format_math_message(message)
        spans = math_spans(message)
        assert "".join(s.source for s in spans) == message
        assert r"\(" not in rich and r"\)" not in rich
        assert r"\frac" not in plain and r"\begin" not in plain
        for _, _, latex in formulas(message):
            assert _explicit_formula(latex).width > 0
        with Image.open(io.BytesIO(render_math_image(message))) as rendered:
            assert rendered.width == 1200 and rendered.height < 6000
    if source_id == "311619":
        assert rich_needs_png_fallback(statement_text(card))


def test_formula_fallback_preserves_denominators_and_interval_endpoints():
    math = r"\(\frac{1}{2x}, (-\infty;1]\cup(2;3)\)"
    assert plain_text(math) == "(1)/(2x), (−∞;1]∪(2;3)"
    assert rich_needs_png_fallback(math)
    assert "<tg-math>" in format_rich_message(r"Найдите корни \(x^4=(2x-8)^2\).")


def test_multiline_feedback_uses_math_layout_instead_of_literal_environment():
    message = (
        "Что правильно: "
        r"\[\begin{aligned} x^2-4 &= 0 \\ "
        "\n"
        r"(x-2)(x+2) &= 0 \end{aligned}\]"
    )
    assert rich_needs_png_fallback(message)
    assert r"\[" not in format_rich_message(message)
    assert r"\begin" not in plain_text(message)
    with Image.open(io.BytesIO(render_math_image(message))) as rendered:
        assert rendered.height > 200


@pytest.mark.parametrize("width", [360, 390])
def test_relation_glyphs_and_fraction_rule_have_clearance_at_phone_width(width):
    from itertools import groupby

    def mask(latex):
        alpha = _explicit_formula(latex).getchannel("A")
        size = tuple(round(v * width / 1200) for v in alpha.size)
        return alpha.resize(size, Image.Resampling.LANCZOS).point(lambda p: 255 if p > 72 else 0)

    for latex in (r"a\ne x", r"x\le y", r"y\ge a", r"x\in A", r"x\notin B", r"x\pm y"):
        ink = mask(latex)
        columns = (bool(ink.crop((x, 0, x + 1, ink.height)).getbbox()) for x in range(ink.width))
        runs = [(dark, len(list(bits))) for dark, bits in groupby(columns)]
        assert [dark for dark, _ in runs] == [False, True, False, True, False, True, False]
        assert min(runs[2][1], runs[4][1]) >= 2

    ink = mask(r"\frac{x+1}{2a}")
    rows = [sum(bool(ink.getpixel((x, y))) for x in range(ink.width)) for y in range(ink.height)]
    bar = rows.index(max(rows))
    assert rows[bar] >= 0.85 * ink.width
    bar_rows = [i for i, count in enumerate(rows) if count >= 0.85 * ink.width]
    assert len(bar_rows) <= 2 and max(bar_rows) - min(bar_rows) == len(bar_rows) - 1
    assert rows[min(bar_rows) - 1] == rows[max(bar_rows) + 1] == 0
    assert min(sum(rows[:bar]), sum(rows[bar + 1 :])) > 25


def test_greek_product_and_geometric_notation_reach_both_transports():
    from app.bot.math_notation import parse_formula

    for source, tex in (
        ("πD", r"\pi D"),
        ("x∉A", r"x \notin A"),
        ("|x|", r"\left|x\right|"),
        ("∠ABC", r"\angle ABC"),
        ("AB⊥CD", r"AB \perp CD"),
    ):
        assert parse_formula(source) == tex
        assert "<tg-math-block>" in format_rich_message(source)
        assert _explicit_formula(tex).getbbox()


def test_feedback_length_budget_keeps_formulas_whole():
    from app.bot.explicit_math import display_feedback

    source = r"Проверим \(\frac{1}{x+2}=3\) при допустимом x."
    assert display_feedback(source, 16) == "Проверим…"
    assert display_feedback(source, 32).startswith(r"Проверим \(\frac{1}{x+2}=3\)")


def test_nested_numerator_and_scalable_parentheses_use_denominator_policy():
    assert rich_needs_png_fallback(r"\(\frac{\sqrt{x+1}}{\left(2x\right)}\)")
    assert not rich_needs_png_fallback(r"\(\left(x+1\right)^2\)")


def test_unrepresentable_provider_operator_is_not_replaced_by_its_argument():
    # This checks the terminal PNG fallback after a definite Rich rejection.
    notice = render_math_image("Формула недоступна")
    assert render_math_image(r"\(\unsupportedoperator{x}\)") == notice


def test_numeric_degree_sign_keeps_unit_spacing_in_png_and_text():
    from app.bot.explicit_math import local_display_tex

    assert local_display_tex(r"60^\circ+30^{\circ}") == "60°+30°"
    assert local_display_tex(r"f\circ g") == r"f\circ g"
    assert plain_text(r"\(60^\circ\)") == "60°"
    assert _explicit_formula(r"60^\circ.").tobytes() == _explicit_formula("60°.").tobytes()
