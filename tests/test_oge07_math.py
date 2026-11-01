from __future__ import annotations

import base64
import re
import struct
import zlib
from dataclasses import replace
from fractions import Fraction

import pytest

from app.math.numbers import FAMILIES, POLICY, _decimal, audit_condition, generate
from app.math.oge07_graph import (
    GRAPH_SOURCES,
    audit_graph_problem,
    audit_png,
    generate_graph_problem,
    projection,
)
from app.math.oge07_scheduler import ENABLED_FAMILIES, build_task7_candidate_batch
from app.math.oge07_validation import validate_task7_snapshot


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Fraction(1, 2), "0,5"),
        (Fraction(1, 4), "0,25"),
        (Fraction(3, 5), "0,6"),
        (Fraction(1), "1"),
        (Fraction(1, 20), "0,05"),
        (Fraction(-3, 20), "−0,15"),
        (Fraction(1, 3), "1/3"),
    ],
)
def test_decimal_format_is_exact_and_terminates(value: Fraction, expected: str) -> None:
    assert _decimal(value) == expected


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


@pytest.mark.parametrize("family", (*FAMILIES, *GRAPH_SOURCES))
def test_task7_snapshot_validator_accepts_generated_snapshots(family: str) -> None:
    snapshot = (
        generate(family, 713).to_snapshot()
        if family in FAMILIES
        else generate_graph_problem(family, 713).to_snapshot()
    )
    assert validate_task7_snapshot(snapshot)


@pytest.mark.parametrize("family", (*FAMILIES, *GRAPH_SOURCES))
def test_task7_snapshot_validator_rejects_content_mutations(family: str) -> None:
    snapshot = (
        generate(family, 713).to_snapshot()
        if family in FAMILIES
        else generate_graph_problem(family, 713).to_snapshot()
    )
    assert validate_task7_snapshot(snapshot)
    mutations: list[tuple[str, object]] = [
        ("generator_version", "999.0.0"),
        ("condition", str(snapshot["condition"]) + "!"),
        ("correct_answer", "99"),
        ("correct_option_index", 0),
        ("hints", ["изменённая подсказка"]),
        ("solution", ["изменённое решение"]),
    ]
    for field, value in mutations:
        changed = dict(snapshot)
        changed[field] = value
        assert not validate_task7_snapshot(changed), (family, field)
    changed_options = list(snapshot["options"])
    changed_options[0] = "мутация"
    changed = dict(snapshot)
    changed["options"] = changed_options
    assert not validate_task7_snapshot(changed)
    if family in GRAPH_SOURCES:
        changed_model = dict(snapshot["graph_model"])
        changed_model["axis_max"] = [999, 1]
        changed = dict(snapshot)
        changed["graph_model"] = changed_model
        assert not validate_task7_snapshot(changed)
        changed = dict(snapshot)
        changed["graph_png_sha256"] = "0" * 64
        assert not validate_task7_snapshot(changed)
        changed = dict(snapshot)
        changed["graph_png_base64"] = "not-base64"
        assert not validate_task7_snapshot(changed)


@pytest.mark.parametrize("family", ("OGE07-N04", "OGE07-N05"))
def test_graph_audit_checks_exact_visible_point_condition(family: str) -> None:
    problem = generate_graph_problem(family, 91)
    changed = replace(problem, condition="Какая точка отмечена на рисунке?")
    assert not audit_graph_problem(changed)


@pytest.mark.parametrize("family", tuple(GRAPH_SOURCES))
def test_graph_problem_semantics_png_and_diversity_across_250_seeds(family: str) -> None:
    first = generate_graph_problem(family, 104)
    assert first == generate_graph_problem(family, 104)
    assert set(first.reference_ids) == set(GRAPH_SOURCES[family])
    fingerprints: set[str] = set()
    for seed in range(250):
        problem = generate_graph_problem(family, seed)
        assert audit_graph_problem(problem)
        snapshot = problem.to_snapshot()
        fingerprint = snapshot["fingerprint"]
        assert isinstance(fingerprint, str)
        fingerprints.add(fingerprint)
        positions = projection(problem.graph_model)
        assert all(72 <= x < problem.graph_model["width"] - 72 for x in positions.values())
        assert len(set(positions.values())) == len(positions)
    assert len(fingerprints) >= 200


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
    mutated_model = dict(problem.graph_model)
    mutated_ticks = [dict(tick) for tick in problem.graph_model["ticks"]]
    mutated_ticks[0]["label"] = "999"
    mutated_model["ticks"] = mutated_ticks
    assert not audit_png(mutated_model, problem.png)


def _replace_png_pixels(png: bytes, pixels: bytearray, width: int, height: int) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        checksum = struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        return struct.pack(">I", len(data)) + body + checksum

    rows = b"".join(b"\x00" + pixels[y * width * 3 : (y + 1) * width * 3] for y in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">2I5B", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows, 9))
        + chunk(b"IEND", b"")
    )


@pytest.mark.parametrize("family", tuple(GRAPH_SOURCES))
def test_png_pixel_oracle_rejects_shifted_point_with_unchanged_model(family: str) -> None:
    problem = generate_graph_problem(family, 366)
    data = problem.png
    cursor = 8
    compressed = bytearray()
    while cursor < len(data):
        length = struct.unpack(">I", data[cursor : cursor + 4])[0]
        kind = data[cursor + 4 : cursor + 8]
        body = data[cursor + 8 : cursor + 8 + length]
        if kind == b"IHDR":
            width, height = struct.unpack(">2I", body[:8])
        elif kind == b"IDAT":
            compressed.extend(body)
        cursor += length + 12
    raw = zlib.decompress(compressed)
    pixels = bytearray()
    stride = width * 3
    for y in range(height):
        row = y * (stride + 1)
        assert raw[row] == 0
        pixels.extend(raw[row + 1 : row + stride + 1])
    center = projection(problem.graph_model)[str(problem.graph_model["points"][0]["id"])]
    point_y, radius = 121, 8
    white, blue = (255, 255, 255), (35, 105, 190)
    for y in range(point_y - radius, point_y + radius + 1):
        for x in range(center - radius, center + radius + 1):
            if (x - center) ** 2 + (y - point_y) ** 2 <= radius**2:
                offset = (y * width + x) * 3
                pixels[offset : offset + 3] = bytes(white)
    shifted = center + 7
    for y in range(point_y - radius, point_y + radius + 1):
        for x in range(shifted - radius, shifted + radius + 1):
            if (x - shifted) ** 2 + (y - point_y) ** 2 <= radius**2:
                offset = (y * width + x) * 3
                pixels[offset : offset + 3] = bytes(blue)
    mutated_png = _replace_png_pixels(data, pixels, width, height)
    assert not audit_png(problem.graph_model, mutated_png)
