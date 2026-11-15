import base64
import hashlib
from copy import deepcopy
from io import BytesIO

import pytest
from PIL import Image, ImageDraw

from app.math.oge18 import (
    FAMILIES,
    GENERATOR_VERSION_V2,
    NEW_FAMILIES,
    POLICY,
    fingerprint,
    from_snapshot,
    generate,
)
from app.math.oge18_oracle import answer
from app.math.oge18_scheduler import build_task18_candidate_batch


@pytest.mark.parametrize("family", FAMILIES)
def test_smoke_50_with_exact_oracle_and_snapshot(family):
    for seed in range(50):
        problem = generate(family, seed)
        snapshot = problem.to_snapshot()
        points = tuple(tuple(p) for p in snapshot["points"])
        assert POLICY.parse(snapshot["correct_answer"]) == answer(points)
        assert from_snapshot(snapshot).png_bytes == problem.png_bytes
        assert snapshot["image_sha256"] == hashlib.sha256(problem.png_bytes).hexdigest()
        assert not any(str(n) in snapshot["condition"] for n in range(2, 15))


@pytest.mark.parametrize("seed", (0, 1, 42, 2027, 90126))
@pytest.mark.parametrize("family", FAMILIES)
def test_fixed_seed_determinism_and_immutable_snapshot(seed, family):
    first, second = generate(family, seed), generate(family, seed)
    assert first == second
    snapshot = first.to_snapshot()
    snapshot["points"][0][0] += 1
    assert first == second


@pytest.mark.parametrize("seed", (-1, 2**63, True, 1.5, "1"))
def test_invalid_seed_rejected(seed):
    with pytest.raises(ValueError):
        generate(FAMILIES[0], seed)


def test_source_vectors_and_half_answer_and_reflection():
    triangle = ((2, 2), (5, 8), (10, 2))
    trapezoid = ((2, 2), (4, 7), (7, 7), (11, 2))
    assert answer(triangle) == 4  # Catalog 348480: AC=8.
    assert answer(trapezoid) == 6  # Catalog 348638: bases 9 and 3.
    assert answer(((2, 2), (4, 7), (8, 7), (11, 2))) == POLICY.parse("6,50")
    for family, points in zip(FAMILIES, (triangle, trapezoid), strict=True):
        moved = tuple((x + 1, y + 1) for x, y in points)
        reflected = (points[0],)  # Keep semantic vertex order after reflection.
        if len(points) == 3:
            reflected = (points[0], (12 - points[1][0], points[1][1]), points[2])
        else:
            reflected = (
                points[0],
                (13 - points[2][0], points[2][1]),
                (13 - points[1][0], points[1][1]),
                points[3],
            )
        assert fingerprint(family, points) == fingerprint(family, moved)
        assert fingerprint(family, points) == fingerprint(family, reflected)
        assert answer(points) == answer(moved) == answer(reflected)


@pytest.mark.parametrize(
    "points",
    (
        ((2, 2), (2, 3), (6, 2)),
        ((2, 2), (3, 14), (6, 2)),
        ((2, 2), (3.5, 5), (6, 2)),
        ((2, 2), (5, 2), (6, 2)),
        ((2, 2), (6, 7), (4, 7), (11, 2)),
    ),
)
def test_unsafe_geometry_fails_closed(points):
    with pytest.raises(ValueError):
        answer(points)


@pytest.mark.parametrize(
    "field,value",
    (
        ("renderer_version", "oge18-pillow-0"),
        ("generator_version", "old"),
        ("correct_answer", "999"),
        ("image_sha256", "0" * 64),
        ("condition", "AC=8"),
        ("solution", ["Ответ 4"]),
        ("png_base64", "broken"),
        ("answer_policy_version", "2"),
        ("points", [[2, 2], [3, 5], [14, 2]]),
    ),
)
def test_corrupted_snapshot_rejected(field, value):
    snapshot = generate(FAMILIES[0], 42).to_snapshot()
    snapshot[field] = value
    with pytest.raises(ValueError):
        from_snapshot(snapshot)


@pytest.mark.parametrize("mutation", ("midline", "grid", "unequal_step", "label", "edge"))
def test_final_pixel_mutations_rejected_even_with_updated_hash(mutation):
    snapshot = generate(FAMILIES[0], 42).to_snapshot()
    image = Image.open(BytesIO(base64.b64decode(snapshot["png_base64"]))).convert("RGB")
    draw = ImageDraw.Draw(image)
    if mutation == "midline":
        a, b, c = snapshot["points"]
        draw.line(
            (
                40 + 16 * (a[0] + b[0]),
                584 - 16 * (a[1] + b[1]),
                40 + 16 * (b[0] + c[0]),
                584 - 16 * (b[1] + c[1]),
            ),
            fill="black",
            width=3,
        )
    elif mutation == "grid":
        draw.rectangle((70, 35, 74, 585), fill="white")
    elif mutation == "unequal_step":
        draw.line((78, 40, 78, 584), fill="grey", width=2)
    elif mutation == "edge":
        draw.rectangle((100, 100, 650, 500), fill="white")
    else:
        draw.text((50, 40), "A", fill="black")
    out = BytesIO()
    image.save(out, format="PNG")
    snapshot["png_base64"] = base64.b64encode(out.getvalue()).decode()
    snapshot["image_sha256"] = hashlib.sha256(out.getvalue()).hexdigest()
    with pytest.raises(ValueError):
        from_snapshot(snapshot)


def test_answer_policy_and_queue_no_repeats_or_silent_fallback():
    for raw in ("6.5", "6,5", "6,50"):
        assert POLICY.accepts(raw, "6.5")
    for raw in ("6.49", "13/2", "6,5 см", "ответ 6,5"):
        assert not POLICY.accepts(raw, "6.5")
    assert build_task18_candidate_batch({}, 0) == []
    state = {}
    seen = set()
    for seed in range(35):
        candidates = build_task18_candidate_batch(state, seed, enabled_families=FAMILIES)
        assert len(candidates) == 1
        snapshot = deepcopy(candidates[0])
        assert snapshot["fingerprint"] not in seen
        seen.add(snapshot["fingerprint"])
        state = {
            "recent_fingerprints": list(seen),
            "family_queue": snapshot["_family_queue_after"],
            "last_family_id": snapshot["_last_family_after"],
        }


def test_mixed_legacy_and_grid_families_follow_injected_queue():
    from app.math.oge18 import from_snapshot

    sequence = ("OGE18-M01", "OGE18-A03", "OGE18-M02", "OGE18-L02")
    state: dict[str, object] = {"family_queue": list(sequence)}
    issued = []
    for seed, expected in enumerate(sequence, start=800):
        candidates = build_task18_candidate_batch(state, seed, enabled_families=sequence)
        assert len(candidates) == 1
        candidate = candidates[0]
        assert candidate["family_id"] == expected
        assert from_snapshot(candidate).png_bytes
        issued.append(candidate)
        state = {
            "family_queue": candidate["_family_queue_after"],
            "last_family_id": candidate["_last_family_after"],
            "recent_fingerprints": [item["fingerprint"] for item in issued],
        }
    assert [item["generator_version"] for item in issued] == [
        "oge18-grid-1",
        "oge18-grid-2",
        "oge18-grid-1",
        "oge18-grid-2",
    ]


@pytest.mark.parametrize("family", FAMILIES)
def test_seed_cannot_be_kept_while_all_model_fields_and_png_come_from_other_seed(family):
    original = generate(family, 42).to_snapshot()
    forgery = generate(family, 43).to_snapshot()
    original_identity = original["problem_id"]
    forgery["seed"] = original["seed"]
    forgery["problem_id"] = original_identity
    with pytest.raises(ValueError, match="Coordinates do not match"):
        from_snapshot(forgery)


def test_fixed_seed_versioned_regression_vectors():
    import json
    from pathlib import Path

    vectors = json.loads(Path("atlas/oge18_regression_vectors.json").read_text())
    for vector in vectors:
        snapshot = generate(
            vector["family_id"], vector["seed"], vector["generator_version"]
        ).to_snapshot()
        assert {key: snapshot[key] for key in vector} == vector


def test_pixel_oracle_rejects_a_renderer_that_repeats_its_own_auxiliary_line(monkeypatch):
    from app.math import oge18_render

    snapshot = generate(FAMILIES[1], 42).to_snapshot()
    points = tuple(tuple(p) for p in snapshot["points"])
    image = Image.open(BytesIO(base64.b64decode(snapshot["png_base64"]))).convert("RGB")
    a, b, c, d = points
    ImageDraw.Draw(image).line(
        (
            40 + 16 * (a[0] + b[0]),
            584 - 16 * (a[1] + b[1]),
            40 + 16 * (c[0] + d[0]),
            584 - 16 * (c[1] + d[1]),
        ),
        fill="black",
        width=3,
    )
    out = BytesIO()
    image.save(out, format="PNG")
    wrong_png = out.getvalue()
    monkeypatch.setattr(oge18_render, "render", lambda *args: wrong_png)
    with pytest.raises(ValueError, match="Unexpected dark ink"):
        oge18_render.audit(wrong_png, points, False)


def test_triangle_area_pixel_oracle_rejects_an_added_height():
    from app.math.oge18_render import audit_family

    snapshot = generate("OGE18-A03", 11, GENERATOR_VERSION_V2).to_snapshot()
    points = tuple(tuple(point) for point in snapshot["points"])
    image = Image.open(BytesIO(base64.b64decode(snapshot["png_base64"]))).convert("RGB")
    a, b = points[0], points[1]
    ImageDraw.Draw(image).line(
        (40 + 32 * b[0], 584 - 32 * b[1], 40 + 32 * b[0], 584 - 32 * a[1]),
        fill=(22, 22, 22),
        width=3,
    )
    out = BytesIO()
    image.save(out, format="PNG")
    with pytest.raises(ValueError, match="Unexpected dark construction"):
        audit_family(out.getvalue(), "OGE18-A03", points)


def test_repeat_snapshot_validation_keeps_hash_and_renderer_fail_closed():
    snapshot = generate(FAMILIES[0], 42).to_snapshot()
    bad_hash = deepcopy(snapshot)
    bad_hash["image_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="hash"):
        from_snapshot(bad_hash, audit_pixels=False)
    altered_png = deepcopy(snapshot)
    image = Image.open(BytesIO(base64.b64decode(altered_png["png_base64"]))).convert("RGB")
    ImageDraw.Draw(image).point((0, 0), fill="black")
    out = BytesIO()
    image.save(out, format="PNG")
    altered_png["png_base64"] = base64.b64encode(out.getvalue()).decode()
    altered_png["image_sha256"] = hashlib.sha256(out.getvalue()).hexdigest()
    with pytest.raises(ValueError, match="versioned renderer"):
        from_snapshot(altered_png, audit_pixels=False)


@pytest.mark.parametrize("family", NEW_FAMILIES)
def test_new_family_source_geometry_and_seed_snapshot_roundtrip(family):
    from app.math.oge18_oracle import answer_family

    for seed in range(50):
        problem = generate(family, seed, GENERATOR_VERSION_V2)
        snapshot = problem.to_snapshot()
        points = tuple(tuple(point) for point in snapshot["points"])
        assert answer_family(family, points) == POLICY.parse(snapshot["correct_answer"])
        assert from_snapshot(snapshot).png_bytes == problem.png_bytes
        assert snapshot["renderer_version"] == "oge18-pillow-2"
        assert snapshot["geometry_model"] == "oge18-grid-model-2"


@pytest.mark.parametrize("family", NEW_FAMILIES)
def test_new_family_rejects_consistent_other_seed_model_and_png(family):
    snapshot = generate(family, 42, GENERATOR_VERSION_V2).to_snapshot()
    forged = generate(family, 43, GENERATOR_VERSION_V2).to_snapshot()
    forged["seed"] = snapshot["seed"]
    forged["problem_id"] = snapshot["problem_id"]
    with pytest.raises(ValueError, match="Coordinates do not match"):
        from_snapshot(forged)


@pytest.mark.parametrize("family", NEW_FAMILIES)
@pytest.mark.parametrize("field", ("coordinate", "png", "hash", "condition", "version", "seed"))
def test_new_family_snapshot_mutations_fail_closed(family, field):
    snapshot = generate(family, 73, GENERATOR_VERSION_V2).to_snapshot()
    damaged = deepcopy(snapshot)
    if field == "coordinate":
        damaged["points"][0][0] += 1
    elif field == "png":
        image = Image.open(BytesIO(base64.b64decode(damaged["png_base64"]))).convert("RGB")
        ImageDraw.Draw(image).point((0, 0), fill="black")
        out = BytesIO()
        image.save(out, format="PNG")
        damaged["png_base64"] = base64.b64encode(out.getvalue()).decode()
        damaged["image_sha256"] = hashlib.sha256(out.getvalue()).hexdigest()
    elif field == "hash":
        damaged["image_sha256"] = "0" * 64
    elif field == "condition":
        damaged["condition"] += " "
    elif field == "version":
        damaged["generator_version"] = "oge18-grid-1"
    else:
        damaged["seed"] += 1
    with pytest.raises(ValueError):
        from_snapshot(damaged)


@pytest.mark.parametrize(
    "family,points",
    [
        ("OGE18-D05", ((2, 2), (6, 5))),
        ("OGE18-L02", ((2, 2), (2, 7), (9, 7))),
        ("OGE18-A01", ((2, 2), (2, 6), (5, 6), (4, 2))),
        ("OGE18-A03", ((2, 2), (4, 6), (9, 2))),
        ("OGE18-A04", ((3, 3), (9, 3), (11, 6), (5, 6))),
        ("OGE18-A05", ((7, 10), (8, 14), (9, 10), (8, 6))),
    ],
)
def test_new_family_original_coordinate_fixtures(family, points):
    from app.math.oge18_oracle import answer_family

    expected = {
        "OGE18-D05": 5,
        "OGE18-L02": 7,
        "OGE18-A01": 10,
        "OGE18-A03": 14,
        "OGE18-A04": 18,
        "OGE18-A05": 8,
    }
    assert answer_family(family, points) == expected[family]


def test_rhombus_oracle_rejects_nonrhombus_and_distance_oracle_rejects_irrational():
    from app.math.oge18_oracle import answer_family

    with pytest.raises(ValueError, match="Not a rhombus"):
        answer_family("OGE18-A05", ((2, 2), (8, 3), (9, 8), (3, 7)))
    with pytest.raises(ValueError, match="not an exact integer"):
        answer_family("OGE18-D05", ((2, 2), (3, 4)))


def test_new_family_edge_cases_use_exact_coordinate_math_and_answer_policy():
    from app.math.oge18_oracle import answer_family

    for point_a, point_b, distance in (
        ((2, 2), (5, 2), 3),
        ((2, 2), (2, 5), 3),
        ((2, 2), (5, 6), 5),
        ((2, 2), (7, 14), 13),
        ((2, 2), (10, 17), 17),
    ):
        assert answer_family("OGE18-D05", (point_a, point_b)) == distance
    with pytest.raises(ValueError, match="distinct"):
        answer_family("OGE18-D05", ((3, 3), (3, 3)))
    assert answer_family("OGE18-L02", ((2, 2), (2, 7), (9, 7))) == 7
    with pytest.raises(ValueError, match="unique larger"):
        answer_family("OGE18-L02", ((2, 2), (2, 7), (7, 7)))
    assert answer_family("OGE18-A03", ((2, 2), (4, 5), (7, 2))) == POLICY.parse("7,5")
    assert answer_family("OGE18-A01", ((2, 2), (3, 5), (6, 5), (4, 2))) == POLICY.parse("7,5")
    # Reflection and cyclic vertex order preserve exact polygon area.
    slanted = ((3, 3), (9, 3), (11, 6), (5, 6))
    assert answer_family("OGE18-A04", slanted) == 18
    assert answer_family("OGE18-A04", tuple(reversed(slanted))) == 18
    assert answer_family("OGE18-A05", ((7, 10), (8, 14), (9, 10), (8, 6))) == 8
    for raw in ("4.5", "4,50"):
        assert POLICY.accepts(raw, "4.5")
    for raw in ("9/2", "4,6", "4,5 см²"):
        assert not POLICY.accepts(raw, "4.5")


def test_finite_distance_and_axis_leg_models_have_expected_shape_capacity():
    distance_shapes = {tuple(sorted(pair)) for pair in ((3, 4), (5, 12), (8, 15))}
    leg_shapes = {
        tuple(sorted((horizontal, vertical)))
        for horizontal in range(3, 10)
        for vertical in range(3, 10)
        if horizontal != vertical
    }
    assert len(distance_shapes) == 3
    assert len(leg_shapes) == 21
    leg_fingerprints = {
        fingerprint("OGE18-L02", ((2, 2), (2, 2 + vertical), (2 + horizontal, 2 + vertical)))
        for horizontal in range(3, 10)
        for vertical in range(3, 10)
        if horizontal != vertical
    }
    assert len(leg_fingerprints) == 21
    triangle_fingerprints = {
        fingerprint("OGE18-A03", ((2, 2), (2 + offset, 2 + height), (2 + base, 2)))
        for base in range(5, 13)
        for height in range(2, 9)
        for offset in range(1, base)
        if 2 * min(offset, base - offset) >= height
    }
    assert len(triangle_fingerprints) == 130
    assert fingerprint("OGE18-D05", ((2, 2), (5, 6))) == fingerprint("OGE18-D05", ((2, 2), (6, 5)))
