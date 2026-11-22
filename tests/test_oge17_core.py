from __future__ import annotations

import base64
import copy
import hashlib
import json
from fractions import Fraction
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from app.math.oge17_generator import build, from_snapshot, generate, parameters
from app.math.oge17_models import ENABLED_FAMILIES, FAMILIES, GENERATOR_VERSION, POLICY
from app.math.oge17_oracle import audit_math
from app.math.oge17_render import audit_png, render

VECTORS = json.loads(Path("atlas/oge17_regression_vectors.json").read_text())["vectors"]


@pytest.fixture(scope="module")
def snapshots():
    return {family: generate(family, 42).to_snapshot() for family in FAMILIES}


@pytest.mark.parametrize("vector", VECTORS, ids=lambda v: v["source_id"])
def test_individually_checked_source_control(vector):
    data = build(vector["family_id"], vector["parameters"])
    data["family_id"] = vector["family_id"]
    assert audit_math(data) == Fraction(vector["answer"].replace(",", "."))
    audit_png(render(data), data)


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.mass
def test_50_smoke_math_determinism_and_policy(family):
    # The 300-image acceptance run is the separate quality-report command.
    for seed in range(50):
        p = parameters(family, seed)
        data = build(family, p)
        data["family_id"] = family
        answer = audit_math(data)
        assert POLICY.format(answer) == data["correct_answer"]
        assert p == parameters(family, seed)
    problem = generate(family, 42)
    assert problem == generate(family, 42)
    snap = problem.to_snapshot()
    assert from_snapshot(snap, expected_problem_id=snap["problem_id"]) == problem
    assert snap["generator_version"] == GENERATOR_VERSION
    assert snap["answer_policy_id"] == POLICY.policy_id


@pytest.mark.parametrize("family", FAMILIES)
def test_coordinates_false_answer_text_and_solution_fail_closed(family, snapshots):
    original = snapshots[family]
    mutations = []
    s = copy.deepcopy(original)
    s["points"]["B"][0] += 0.7
    mutations.append(s)
    s = copy.deepcopy(original)
    s["correct_answer"] = "9999"
    mutations.append(s)
    s = copy.deepcopy(original)
    s["condition"] = s["condition"].replace("Найдите", "Вычислите", 1)
    mutations.append(s)
    s = copy.deepcopy(original)
    s["solution"][0] += " неверно"
    mutations.append(s)
    s = copy.deepcopy(original)
    s["segments"].append("AC")
    mutations.append(s)
    for s in mutations:
        with pytest.raises(ValueError):
            audit_math(s)


@pytest.mark.parametrize("family", FAMILIES)
def test_midpoints_and_false_markers(family, snapshots):
    s = copy.deepcopy(snapshots[family])
    key = "O" if "O" in s["points"] else "K" if "K" in s["points"] else "H"
    if key in s["points"]:
        s["points"][key][0] += 0.75
        with pytest.raises(ValueError):
            audit_math(s)
    s = copy.deepcopy(snapshots[family])
    s["right_angles"].append(["A", "B", "C"])
    with pytest.raises(ValueError):
        audit_math(s)


@pytest.mark.parametrize("family", FAMILIES)
def test_snapshot_corruptions_and_coherent_other_seed(family, snapshots):
    original = snapshots[family]
    for key, value in (
        ("seed", 43),
        ("generator_version", "unknown"),
        ("oracle_version", "unknown"),
        ("renderer_version", "unknown"),
        ("fingerprint", "a" * 64),
        ("answer_policy_version", "unknown"),
        ("sources", []),
        ("hints", ["bad hint"]),
        ("png_sha256", "b" * 64),
        ("png_base64", "!invalid!"),
    ):
        s = copy.deepcopy(original)
        s[key] = value
        with pytest.raises(ValueError):
            from_snapshot(s, expected_problem_id=original["problem_id"])
    other = generate(family, 43).to_snapshot()
    with pytest.raises(ValueError, match="identity"):
        from_snapshot(other, expected_problem_id=original["problem_id"])
    # Even a coherent new seed/model/image cannot be bound to the old issuance ID.
    other["problem_id"] = original["problem_id"]
    with pytest.raises(ValueError):
        from_snapshot(other, expected_problem_id=original["problem_id"])


@pytest.mark.parametrize("family", FAMILIES)
def test_independent_pixel_audit_rejects_blank_added_or_missing_ink(family, snapshots, monkeypatch):
    s = snapshots[family]
    raw = base64.b64decode(s["png_base64"])
    # Prove that the pixel auditor does not validate by re-calling render.
    monkeypatch.setattr("app.math.oge17_render.render", lambda _: pytest.fail("render called"))
    audit_png(raw, s)
    blank = Image.new("RGB", (720, 540), "white")
    stray = Image.open(BytesIO(raw)).copy()
    ImageDraw.Draw(stray).line((10, 10, 200, 10), fill="black", width=4)
    erased = Image.open(BytesIO(raw)).copy()
    ImageDraw.Draw(erased).rectangle((0, 200, 720, 340), fill="white")
    for im in (blank, stray, erased):
        out = BytesIO()
        im.save(out, format="PNG")
        with pytest.raises(ValueError):
            audit_png(out.getvalue(), s)


@pytest.mark.parametrize("family", FAMILIES)
def test_foreign_png_with_valid_answer_and_recomputed_digest(family, snapshots):
    original = snapshots[family]
    s = copy.deepcopy(original)
    other = snapshots[FAMILIES[(FAMILIES.index(family) + 1) % len(FAMILIES)]]
    s["png_base64"] = other["png_base64"]
    s["png_sha256"] = hashlib.sha256(base64.b64decode(s["png_base64"])).hexdigest()
    with pytest.raises(ValueError):
        from_snapshot(s, expected_problem_id=original["problem_id"])


def test_json_key_order_does_not_move_dimension_labels(snapshots):
    original = snapshots["OGE17-P01"]
    scrambled = json.loads(json.dumps(original, sort_keys=True))
    assert render(original) == render(scrambled)
    audit_png(render(original), scrambled)


def test_essential_diversity_ignores_trapezoid_layout():
    # T04 height/offset change the picture, not the mathematical question.
    from app.math.oge17_generator import _pack

    first = _pack("OGE17-T04", 0, {"lower": 20, "upper": 9, "h": 10, "offset": 3})
    second = _pack("OGE17-T04", 1, {"lower": 20, "upper": 9, "h": 12, "offset": 4})
    assert first.fingerprint == second.fingerprint


def test_atlas_schema_minimum_backlog_and_source_evidence():
    atlas = json.loads(Path("atlas/oge17_reference_structures.json").read_text())
    schema = json.loads(Path("specs/family.schema.json").read_text())
    assert len(atlas["families"]) == len(FAMILIES)
    assert len(atlas["backlog"]) == 27 - len(FAMILIES)
    ids = [f["family_id"] for f in atlas["families"] + atlas["backlog"]]
    assert len(set(ids)) == 27
    for family in atlas["families"]:
        assert set(schema["required"]) <= family.keys()
        assert family["status"] == "enabled_candidate"
        for source in family["sources"]:
            assert (
                source["verification_status"]
                == "text_original_diagram_published_answer_individually_checked"
            )
            assert all(
                asset["visual_checked"] and len(asset["sha256"]) == 64
                for asset in source["original_assets"]
            )
    assert ENABLED_FAMILIES == FAMILIES
    assert set(FAMILIES) == {f["family_id"] for f in atlas["families"]}


@pytest.mark.parametrize("seed", [-1, True, 2**63, "42", 0.5])
def test_invalid_seed_rejected(seed):
    with pytest.raises(ValueError):
        generate(FAMILIES[0], seed)


@pytest.mark.parametrize("alpha", [20, 44, 46, 70])
def test_rectangle_acute_diagonal_angle_boundary_branches(alpha):
    from app.math.oge17_generator import _pack

    item = _pack("OGE17-E01", 0, {"angle": alpha})
    snapshot = item.to_snapshot()
    assert snapshot["correct_answer"] == str(min(2 * alpha, 180 - 2 * alpha))
    assert audit_math(snapshot) < 90


@pytest.mark.parametrize("base,height", [(4, 8), (30, 8), (30, 48)])
def test_partition_extreme_proportions_render_and_replay(base, height):
    from app.math.oge17_generator import _pack

    item = _pack("OGE17-P03", 0, {"base": base, "height": height})
    assert audit_math(item.to_snapshot()) == Fraction(3 * base * height, 4)


def test_p07_readable_geometry_in_the_entire_parameter_range_and_formerly_failing_seed():
    import math

    from app.math.oge17_generator import _p07_parameters

    changed = []
    for bd in range(12, 71):
        for ac in range(max(10, bd * 17 // 20), bd * 23 // 20 + 1):
            lower = max(abs(ac - bd) // 2 + 2, min(ac, bd) // 3)
            for ab in range(lower, min(ac, bd) // 2 + 1):
                params = _p07_parameters(ac, bd, ab)
                if params["ab"] != ab:
                    changed.append((ac, bd, ab))
                points = build("OGE17-P07", params)["points"]
                a, b, c, d = (points[key] for key in "ABCD")
                assert math.dist(a, c) == pytest.approx(ac)
                assert math.dist(b, d) == pytest.approx(bd)
                assert math.dist(a, b) == pytest.approx(params["ab"])
                width = max(x for x, _ in (a, b, c, d)) - min(x for x, _ in (a, b, c, d))
                assert abs(b[1] - a[1]) >= width / 5
    assert changed == [(11, 14, 3)]
    saved = generate("OGE17-P07", 926507482832593720).to_snapshot()
    assert saved["correct_answer"] == "7"
    assert saved["exact_model"]["parameters"] == {"ac": 11, "bd": 14, "ab": 4}
    assert from_snapshot(saved, expected_problem_id=saved["problem_id"]).to_snapshot() == saved
