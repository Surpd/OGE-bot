import base64
import hashlib
from copy import deepcopy
from io import BytesIO

import pytest
from PIL import Image, ImageDraw

from app.math.oge18 import (
    FAMILIES,
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
        snapshot = generate(vector["family_id"], vector["seed"]).to_snapshot()
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
