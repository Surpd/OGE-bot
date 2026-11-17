"""Finite mathematical coverage, source controls and bounded PNG/replay budget."""

from __future__ import annotations

import base64
import copy
import hashlib
from fractions import Fraction
from io import BytesIO
from unittest.mock import patch

import pytest
from PIL import Image

from app.math.answer_policy import format_decimal
from app.math.oge16_circles import FAMILIES, from_snapshot, generate
from app.math.oge16_complete import SOURCE_VARIANTS, content, parameters, source
from app.math.oge16_complete_oracle import solve
from app.math.oge16_oracle import audit

SOURCE_ANSWERS = {
    "A01": (70, 30, 70),
    "A02": (24, 42),
    "A03": (35, 108),
    "A04": (52,),
    "A05": (15, 60, 15, 46),
    "A06": (5,),
    "B01": (40,),
    "B02": (36,),
    "B03": (24,),
    "B04": (4,),
    "B05": (36,),
    "C01": (27556, 196, 8, 3),
    "C02": (32, 24),
    "C03": (100,),
    "C04": (1, 15, 12, 3),
    "C05": (11, 14, 14),
    "C06": (Fraction(168, 25),),
    "D01": (98, 99),
    "D02": (6,),
    "D03": (32,),
    "D04": (6,),
    "D05": (20,),
    "D06": (48,),
}


def mathematical_snapshot(family, seed):
    values = parameters(family, seed)
    text, hints, solution, answer, geometry = content(family, values)
    return {
        "family_id": family,
        "parameters": [str(v) for v in values],
        "condition": text,
        "hints": hints,
        "solution": solution,
        "correct_answer": format_decimal(answer),
        "geometry": geometry.to_dict(),
        "provenance": {"task_id": source(family, values)},
    }, answer


@pytest.mark.parametrize("family", FAMILIES)
def test_finite_mathematical_pool_exhaustively_without_rasterization(family):
    # Each family has 10–40 source/parameter slots. Exhaust it once in memory.
    # Duplicate source IDs representing the same mathematics need no novelty quota.
    period = len(SOURCE_VARIANTS[family[6:]]) * 10
    for seed in range(period):
        snapshot, expected = mathematical_snapshot(family, seed)
        with patch("app.math.oge16_complete.content", side_effect=AssertionError("independent")):
            assert solve(snapshot) == expected
        assert parameters(family, seed + period) == parameters(family, seed)


@pytest.mark.parametrize("key", SOURCE_VARIANTS)
def test_every_confirmed_source_has_its_original_control_answer(key):
    for variant, expected in enumerate(SOURCE_ANSWERS[key]):
        snapshot, result = mathematical_snapshot("OGE16-" + key, variant)
        assert snapshot["provenance"]["task_id"] == SOURCE_VARIANTS[key][variant]
        assert solve(snapshot) == result == expected


@pytest.mark.parametrize("family", FAMILIES)
def test_five_png_samples_ten_saved_replays_and_sha(family):
    period = len(SOURCE_VARIANTS[family[6:]]) * 10
    # Five distinct seed slots cover every textual variant and the largest scale.
    slots = sorted(set([0, 1, 2, 3, period - 1]))
    for seed in slots:
        original = generate(family, seed)
        snapshot = original.to_snapshot()
        assert hashlib.sha256(original.png).hexdigest() == snapshot["figure"]["sha256"]
        for _ in range(2):
            with patch("app.math.oge16_render.render", side_effect=AssertionError("saved PNG")):
                assert from_snapshot(copy.deepcopy(snapshot)).png == original.png
        assert audit(snapshot, pixels=False) == Fraction(
            snapshot["correct_answer"].replace(",", ".")
        )


@pytest.mark.parametrize("family", FAMILIES)
def test_independent_oracle_rejects_wrong_geometry_and_visible_target(family):
    original, _ = mathematical_snapshot(family, 0)
    broken = copy.deepcopy(original)
    # A changed vertex must not pass because the answer happens to remain equal.
    name = next(n for n in broken["geometry"]["points"] if n != "O")
    broken["geometry"]["points"][name][0] += 0.23
    with pytest.raises(ValueError):
        solve(broken)
    broken = copy.deepcopy(original)
    broken["condition"] = broken["condition"].replace("Найдите", "Вычислите периметр", 1)
    with pytest.raises(ValueError):
        solve(broken)


@pytest.mark.parametrize("family", ("OGE16-C06", "OGE16-D05", "OGE16-D06", "OGE16-C05"))
def test_compound_figure_pixel_corruption_fails_with_recomputed_sha(family):
    snapshot = generate(family, 0).to_snapshot()
    figure = snapshot["figure"]
    original = Image.open(BytesIO(base64.b64decode(figure["png_base64"]))).convert("RGB")
    changed = Image.new("RGB", original.size, "white")
    changed.paste(original, (7, 0))
    output = BytesIO()
    changed.save(output, format="PNG")
    raw = output.getvalue()
    figure["png_base64"] = base64.b64encode(raw).decode()
    figure["sha256"] = hashlib.sha256(raw).hexdigest()
    with pytest.raises(ValueError):
        from_snapshot(snapshot)


def test_same_model_sources_share_fingerprint_and_excluded_id_is_absent():
    assert generate("OGE16-A01", 0).fingerprint == generate("OGE16-A01", 2).fingerprint
    assert generate("OGE16-C05", 1).fingerprint == generate("OGE16-C05", 2).fingerprint
    assert "323356" not in {v for ids in SOURCE_VARIANTS.values() for v in ids}


@pytest.mark.parametrize("family", FAMILIES)
def test_visible_calculation_is_checked_even_when_final_answer_is_unchanged(family):
    snapshot, _ = mathematical_snapshot(family, 0)
    correct = snapshot["correct_answer"]
    label = snapshot["solution"][-1].split(" = ")[0]
    snapshot["solution"][-1] = f"{label} = 1 + 1 = {correct}."
    with pytest.raises(ValueError):
        solve(snapshot)


@pytest.mark.parametrize("family", ("OGE16-D01", "OGE16-C02"))
def test_v2_snapshot_and_renderer_v1_bytes_remain_resumable(family):
    snapshot = generate(family, 1, "oge16-circles-2").to_snapshot()
    snapshot["figure"]["renderer_version"] = "oge16-pillow-1"
    original = base64.b64decode(snapshot["figure"]["png_base64"])
    with patch("app.math.oge16_render.render", side_effect=AssertionError("saved v1 renderer")):
        assert from_snapshot(snapshot).png == original
