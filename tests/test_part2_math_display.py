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
