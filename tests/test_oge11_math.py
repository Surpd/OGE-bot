from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import replace
from fractions import Fraction
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from app.math.oge11 import (
    ENABLED_FAMILIES,
    FAMILIES,
    RENDERER_VERSION,
    _semantic_fingerprint,
    all_matching_codes,
    from_snapshot,
    generate,
    parse_answer,
    verify,
)
from app.math.oge11_render import (
    BACKGROUND,
    PLOT,
    ROW_HEIGHT,
    _decode_panel_label,
    _pixels,
    audit_png,
)

_TEST_GLYPHS = {
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11110", "00001", "00001", "01110", "00001", "00001", "11110"),
    "А": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "Б": ("11111", "10000", "10000", "11110", "10001", "10001", "11110"),
    "В": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
}


def _reintegrity(problem, image: Image.Image):
    output = BytesIO()
    image.save(output, format="PNG", optimize=False)
    png_bytes = output.getvalue()
    image_hash = hashlib.sha256(png_bytes).hexdigest()
    fingerprint = _semantic_fingerprint(
        problem.family_id,
        problem.graphs,
        problem.letter_graph_ids,
        problem.digit_graph_ids,
        problem.condition,
        image_hash,
        problem.viewport,
    )
    return replace(
        problem,
        png_bytes=png_bytes,
        image_sha256=image_hash,
        fingerprint=fingerprint,
    )


def _replace_panel_label(problem, panel: int, new_label: str):
    image = Image.open(BytesIO(problem.png_bytes)).convert("RGB")
    draw = ImageDraw.Draw(image)
    scale = 4
    draw.rectangle(
        (24, panel * ROW_HEIGHT + 18, 24 + 20 * scale, panel * ROW_HEIGHT + 18 + 7 * scale),
        fill=BACKGROUND,
    )
    for row, pattern in enumerate(_TEST_GLYPHS[new_label]):
        for column, pixel in enumerate(pattern):
            if pixel == "1":
                x = 24 + column * scale
                y = panel * ROW_HEIGHT + 18 + row * scale
                draw.rectangle((x, y, x + scale - 1, y + scale - 1), fill=(20, 20, 20))
    return _reintegrity(problem, image)


def _find_half_inverse_problem():
    for seed in range(300):
        problem = generate("OGE11-F08", seed)
        if any(graph.coefficients == (Fraction(1, 2),) for graph in problem.graphs):
            return problem
    raise AssertionError("F08 did not generate q=1/2 within 300 seeds")


@pytest.mark.parametrize("family_id", FAMILIES)
def test_generation_is_deterministic_and_independently_verified(family_id: str) -> None:
    first = generate(family_id, 20261102)
    second = generate(family_id, 20261102)

    assert first == second
    assert first.png_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    assert first.image_sha256
    assert first.renderer_version == RENDERER_VERSION
    assert verify(first) == (True, "ok")


@pytest.mark.parametrize("family_id", FAMILIES)
def test_each_family_produces_200_unique_candidates_within_budget(family_id: str) -> None:
    problems = [generate(family_id, seed) for seed in range(300)]
    assert len({problem.fingerprint for problem in problems}) >= 200
    assert {problem.correct_answer for problem in problems} == all_matching_codes()


@pytest.mark.parametrize("family_id", FAMILIES)
def test_panel_pixels_use_labels_required_by_visible_condition(family_id: str) -> None:
    problem = generate(family_id, 20261102)
    image = Image.open(BytesIO(problem.png_bytes)).convert("RGB")
    pixels = image.load()
    assert pixels is not None
    expected_labels = (
        ("А", "Б", "В")
        if family_id in {"OGE11-F02", "OGE11-F03", "OGE11-F07"}
        or (family_id == "OGE11-F06" and problem.answer_kind == "formula_options")
        else ("1", "2", "3")
    )
    assert (
        tuple(_decode_panel_label(pixels, panel, image.width, image.height) for panel in range(3))
        == expected_labels
    )
    assert problem.graph_labels == expected_labels
    audit_png(
        problem.png_bytes,
        problem.graphs,
        problem.graph_order,
        problem.viewport,
        family_id,
        problem.graph_labels,
    )


@pytest.mark.parametrize(
    ("family_id", "panel", "wrong_label"),
    [("OGE11-F03", 0, "1"), ("OGE11-F04", 1, "3")],
)
def test_label_mutations_are_rejected_even_with_recomputed_hash(
    family_id: str, panel: int, wrong_label: str
) -> None:
    problem = generate(family_id, 314)
    assert verify(_replace_panel_label(problem, panel, wrong_label)) == (
        False,
        "graph or formula audit failed",
    )


@pytest.mark.parametrize("family_id", ("OGE11-F01", "OGE11-F03"))
def test_swapped_panel_labels_are_rejected(family_id: str) -> None:
    problem = generate(family_id, 415)
    image = Image.open(BytesIO(problem.png_bytes)).convert("RGB")
    first = image.crop((24, 18, 44, 46))
    second = image.crop((24, ROW_HEIGHT + 18, 44, ROW_HEIGHT + 46))
    image.paste(second, (24, 18))
    image.paste(first, (24, ROW_HEIGHT + 18))
    assert verify(_reintegrity(problem, image)) == (False, "graph or formula audit failed")


def test_swapped_graph_panels_are_rejected_without_changing_model() -> None:
    problem = generate("OGE11-F03", 516)
    image = Image.open(BytesIO(problem.png_bytes)).convert("RGB")
    left, top, right, bottom = PLOT
    panel_a = image.crop((left, top, right + 1, bottom + 1))
    panel_b = image.crop((left, ROW_HEIGHT + top, right + 1, ROW_HEIGHT + bottom + 1))
    image.paste(panel_b, (left, top))
    image.paste(panel_a, (left, ROW_HEIGHT + top))
    assert verify(_reintegrity(problem, image)) == (False, "graph or formula audit failed")


def test_wrong_display_to_answer_order_is_rejected() -> None:
    problem = generate("OGE11-F02", 617)
    changed_digits = (
        problem.digit_graph_ids[1],
        problem.digit_graph_ids[0],
        problem.digit_graph_ids[2],
    )
    changed_fingerprint = _semantic_fingerprint(
        problem.family_id,
        problem.graphs,
        problem.letter_graph_ids,
        changed_digits,
        problem.condition,
        problem.image_sha256,
        problem.viewport,
    )
    mutated = replace(problem, digit_graph_ids=changed_digits, fingerprint=changed_fingerprint)
    assert verify(mutated) == (False, "visible formula differs from model")


def test_control_point_mutation_is_rejected_after_hash_and_fingerprint_update() -> None:
    problem = generate("OGE11-F06", 718)
    image = Image.open(BytesIO(problem.png_bytes)).convert("RGB")
    graph = problem.graphs[problem.graph_order[0]]
    x_value = next(
        Fraction(x)
        for x in (-4, -3, -2, -1, 1, 2, 3, 4)
        if problem.viewport[2] <= graph.value(Fraction(x)) <= problem.viewport[3]
    )
    fx, fy = _pixels(float(x_value), float(graph.value(x_value)), problem.viewport, 0)
    pixels = image.load()
    for x in range(fx - 8, fx + 9):
        for y in range(fy - 8, fy + 9):
            if 0 <= x < image.width and 0 <= y < image.height:
                red, green, blue = pixels[x, y]
                if blue > red + 30 and blue > green + 20:
                    pixels[x, y] = BACKGROUND
    assert verify(_reintegrity(problem, image)) == (False, "graph or formula audit failed")


def test_snapshot_restores_exact_png_and_rejects_bad_or_unsupported_images(monkeypatch) -> None:
    problem = generate("OGE11-F04", 819)

    import app.math.oge11 as oge11_module

    monkeypatch.setattr(
        oge11_module,
        "render_graphs",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected rerender")),
    )
    restored = from_snapshot(problem.to_snapshot())
    assert restored.png_bytes == problem.png_bytes
    assert restored.image_sha256 == problem.image_sha256
    assert restored.correct_answer == problem.correct_answer

    snapshot = problem.to_snapshot()
    snapshot["renderer_version"] = "0.1.0"
    with pytest.raises(ValueError, match="unsupported renderer version"):
        from_snapshot(snapshot)

    snapshot = problem.to_snapshot()
    snapshot["png_base64"] = base64.b64encode(problem.png_bytes[:-10] + b"badpayload").decode(
        "ascii"
    )
    with pytest.raises(ValueError, match="invalid task-11 snapshot"):
        from_snapshot(snapshot)


def test_audited_task11_families_are_enabled_for_learners() -> None:
    assert ENABLED_FAMILIES == FAMILIES


def test_family_specific_sign_and_intercept_rules() -> None:
    for seed in range(30):
        linear_signs = generate("OGE11-F03", seed)
        for graph in linear_signs.graphs:
            k, b = graph.coefficients
            assert graph.value(Fraction(0)) == b
            assert (k > 0) == (graph.value(Fraction(1)) > graph.value(Fraction(0)))
        assert verify(linear_signs) == (True, "ok")

        parabola_signs = generate("OGE11-F04", seed)
        for graph in parabola_signs.graphs:
            a, _, c = graph.coefficients
            assert graph.value(Fraction(0)) == c
            assert (a > 0) == (graph.value(Fraction(-1)) + graph.value(Fraction(1)) > 2 * c)
        assert verify(parabola_signs) == (True, "ok")


def test_family_specific_slopes_constant_function_and_hyperbola_quadrants() -> None:
    for seed in range(30):
        through_origin = generate("OGE11-F05", seed)
        for graph in through_origin.graphs:
            k, b = graph.coefficients
            assert b == 0
            assert graph.value(Fraction(1)) == k

        general_lines = generate("OGE11-F06", seed)
        for graph in general_lines.graphs:
            k, b = graph.coefficients
            assert graph.value(Fraction(0)) == b
            assert graph.value(Fraction(1)) - b == k

        mixed = generate("OGE11-F07", seed)
        constants = [graph for graph in mixed.graphs if graph.kind == "constant"]
        assert len(constants) == 1
        constant = constants[0]
        assert constant.value(Fraction(-3)) == constant.value(Fraction(3))

        inverse_problem = generate("OGE11-F08", seed)
        for graph in inverse_problem.graphs:
            q = graph.coefficients[0]
            for x in (Fraction(-2), Fraction(-1), Fraction(1), Fraction(2)):
                value = graph.value(x)
                assert value * x == q
                assert (value > 0) == (q > 0 and x > 0 or q < 0 and x < 0)
        assert verify(inverse_problem) == (True, "ok")


def test_confirmed_source_orientations_and_mappings_are_exact() -> None:
    source_contracts = {
        "348381": {
            "orientation": "coefficient_sign_rows_A_B_V_to_graphs_1_2_3",
            "coefficient_rows": ["a>0,c>0", "a<0,c>0", "a>0,c<0"],
            "graph_numbers_by_letter": [3, 2, 1],
            "independent_code": "321",
        },
        "350104": {
            "orientation": "graphs_A_B_V_to_formula_options_1_2_3",
            "formula_options": ["y=-3x+3", "y=3x", "y=3x-3"],
            "formula_numbers_by_letter": [2, 1, 3],
            "independent_code": "213",
        },
        "350202": {
            "orientation": "formula_rows_A_B_V_to_graphs_1_2_3",
            "formula_rows": ["y=x/2+3", "y=-x/2+3", "y=x/2-3"],
            "graph_numbers_by_letter": [1, 3, 2],
            "independent_code": "132",
        },
        "340835": {
            "orientation": "graphs_A_B_V_to_formula_options_1_2_3",
            "formula_options": ["y=-2", "y=x-2", "y=-2x"],
            "formula_numbers_by_letter": [1, 3, 2],
            "independent_code": "132",
        },
        "341668": {
            "orientation": "function_rows_A_B_V_to_graphs_1_2_3",
            "formula_rows": ["y=-2/x", "y=2/x", "y=1/(2x)"],
            "graph_numbers_by_letter": [1, 3, 2],
            "independent_code": "132",
            "minimum_abs_coefficient": "1/2",
        },
    }
    audit = json.loads(Path("atlas/oge11_release_audit.json").read_text(encoding="utf-8"))
    source_structures = audit["source_structures"]
    observed_contracts = {
        task_id: {
            key: value
            for key, value in source_structures[task_id].items()
            if key != "family_id"
        }
        for task_id in source_contracts
    }
    assert observed_contracts == source_contracts
    for mapping in audit["source_structures"].values():
        answer_mapping = mapping.get("graph_numbers_by_letter") or mapping.get(
            "formula_numbers_by_letter"
        )
        if answer_mapping:
            assert "".join(str(value) for value in answer_mapping) == mapping["independent_code"]

    f04 = generate("OGE11-F04", 220348381)
    assert f04.answer_kind == "signs_letters"
    assert f04.graph_labels == ("1", "2", "3")
    assert f04.condition.splitlines()[1].startswith("А) a ")
    assert "c " in f04.condition.splitlines()[1]

    f07 = generate("OGE11-F07", 220340835)
    assert f07.answer_kind == "formula_options"
    assert f07.graph_labels == ("А", "Б", "В")
    assert f07.condition.splitlines()[1].startswith("1) y=")

    f06_candidates = [generate("OGE11-F06", seed) for seed in range(50)]
    layouts = {problem.answer_kind for problem in f06_candidates}
    assert layouts == {"formula_letters", "formula_options"}
    for problem in f06_candidates:
        expected = (
            ("А", "Б", "В")
            if problem.answer_kind == "formula_options"
            else ("1", "2", "3")
        )
        assert problem.graph_labels == expected

    half = _find_half_inverse_problem()
    assert "1/(2x)" in half.condition
    assert verify(half) == (True, "ok")


def test_source_orientation_mutations_are_rejected() -> None:
    f04 = generate("OGE11-F04", 440)
    lines = f04.condition.splitlines()
    lines[1], lines[2] = lines[2].replace("Б)", "А)"), lines[1].replace("А)", "Б)")
    assert verify(replace(f04, condition="\n".join(lines))) == (
        False,
        "visible coefficient-sign rows differ from graph models",
    )

    f07 = generate("OGE11-F07", 441)
    lines = f07.condition.splitlines()
    lines[1], lines[2] = lines[2].replace("2)", "1)"), lines[1].replace("1)", "2)")
    assert verify(replace(f07, condition="\n".join(lines))) == (
        False,
        "visible formula differs from model",
    )

    f06_candidates = [generate("OGE11-F06", seed) for seed in range(100)]
    f06_letters = next(
        problem for problem in f06_candidates if problem.answer_kind == "formula_letters"
    )
    lines = f06_letters.condition.splitlines()
    lines[1], lines[2] = lines[2].replace("Б)", "А)"), lines[1].replace("А)", "Б)")
    assert verify(replace(f06_letters, condition="\n".join(lines))) == (
        False,
        "visible formula differs from model",
    )

    f06_options = next(
        problem for problem in f06_candidates if problem.answer_kind == "formula_options"
    )
    lines = f06_options.condition.splitlines()
    lines[1], lines[2] = lines[2].replace("2)", "1)"), lines[1].replace("1)", "2)")
    assert verify(replace(f06_options, condition="\n".join(lines))) == (
        False,
        "visible formula differs from model",
    )

    half = _find_half_inverse_problem()
    changed = half.condition.replace("1/(2x)", "1/x")
    assert verify(replace(half, condition=changed)) == (False, "visible formula differs from model")


def test_snapshot_preserves_both_f06_orientations_and_panel_labels() -> None:
    examples = {}
    for seed in range(100):
        problem = generate("OGE11-F06", seed)
        examples.setdefault(problem.answer_kind, problem)
        if len(examples) == 2:
            break
    assert set(examples) == {"formula_letters", "formula_options"}
    for problem in examples.values():
        snapshot = problem.to_snapshot()
        assert snapshot["graph_labels"] == list(problem.graph_labels)
        assert from_snapshot(snapshot) == problem

        snapshot["graph_labels"] = (
            ["1", "2", "3"]
            if problem.graph_labels[0] == "А"
            else ["А", "Б", "В"]
        )
        with pytest.raises(ValueError, match="invalid task-11 snapshot"):
            from_snapshot(snapshot)


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
