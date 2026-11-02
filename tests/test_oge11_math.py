from __future__ import annotations

from dataclasses import replace
from io import BytesIO

import pytest
from PIL import Image

from app.math.oge11 import FAMILIES, all_matching_codes, generate, parse_answer, verify


@pytest.mark.parametrize("family_id", FAMILIES)
def test_generation_is_deterministic_and_independently_verified(family_id: str) -> None:
    first = generate(family_id, 20261102)
    second = generate(family_id, 20261102)

    assert first == second
    assert first.png_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    assert first.image_sha256
    assert verify(first) == (True, "ok")


@pytest.mark.parametrize("family_id", FAMILIES)
def test_each_family_produces_200_unique_candidates_within_budget(family_id: str) -> None:
    problems = [generate(family_id, seed) for seed in range(300)]
    assert len({problem.fingerprint for problem in problems}) >= 200
    assert {problem.correct_answer for problem in problems} == all_matching_codes()


@pytest.mark.parametrize("raw", ["", "12", "1234", "112", "１２３", " 123", "123 ", "120"])
def test_answer_parser_rejects_non_permutations(raw: str) -> None:
    assert parse_answer(raw) is None


def test_answer_parser_preserves_exact_three_digit_string() -> None:
    assert parse_answer("132") == "132"


def test_oracle_rejects_visible_formula_mutation() -> None:
    problem = generate("OGE11-F02", 53)
    lines = problem.condition.splitlines()
    formula_line = next(index for index, line in enumerate(lines) if line.startswith("1) y="))
    lines[formula_line] = "1) y=777"

    assert verify(replace(problem, condition="\n".join(lines))) == (
        False,
        "visible formula differs from model",
    )


def test_oracle_rejects_sign_option_mutation() -> None:
    problem = generate("OGE11-F03", 61)
    lines = problem.condition.splitlines()
    lines[1] = lines[1].replace("+", "−") if "+" in lines[1] else lines[1].replace("−", "+")

    assert verify(replace(problem, condition="\n".join(lines))) == (
        False,
        "visible sign options differ from model",
    )


def test_oracle_rejects_stale_code_and_corrupted_solution() -> None:
    problem = generate("OGE11-F01", 71)
    other_code = next(code for code in all_matching_codes() if code != problem.correct_answer)
    assert verify(replace(problem, correct_answer=other_code)) == (False, "wrong matching code")
    assert verify(replace(problem, solution=("incorrect step",))) == (
        False,
        "invalid reasoning step",
    )


def test_oracle_rejects_changed_png_bytes_and_viewport() -> None:
    problem = generate("OGE11-F02", 83)
    assert verify(replace(problem, png_bytes=problem.png_bytes[:-1] + b"X")) == (
        False,
        "snapshot integrity violation",
    )
    assert verify(replace(problem, viewport=(-problem.viewport[0], *problem.viewport[1:]))) != (
        True,
        "ok",
    )


def test_inverse_graph_is_defined_on_separate_branches() -> None:
    problem = generate("OGE11-F08", 101)
    inverse = next(graph for graph in problem.graphs if graph.kind == "inverse")
    with pytest.raises(ValueError, match="x=0"):
        inverse.value(0)


def test_all_six_matching_codes_are_represented() -> None:
    assert all_matching_codes() == {"123", "132", "213", "231", "312", "321"}


def test_mobile_sized_png_keeps_three_visible_panels() -> None:
    problem = generate("OGE11-F02", 107)
    image = Image.open(BytesIO(problem.png_bytes)).convert("RGB")
    image.thumbnail((360, 2048), Image.Resampling.LANCZOS)
    assert image.width == 360
    assert image.height >= 700
    pixels = image.load()
    for top in (0, 260, 520):
        panel = [
            pixels[x, y]
            for x in range(image.width)
            for y in range(top, min(top + 250, image.height))
        ]
        assert any(blue > red + 25 and blue > green + 15 for red, green, blue in panel)
