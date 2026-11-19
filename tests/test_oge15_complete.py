"""Source controls, independent coordinate mutations, versioned raster replay."""

import base64
import hashlib
from fractions import Fraction
from io import BytesIO

import pytest
from PIL import Image, ImageDraw

from app.math.oge15_complete import ALL_FAMILIES, VERSION, content
from app.math.oge15_coordinate_oracle import validate
from app.math.oge15_geometry import construct
from app.math.oge15_render import audit
from app.math.oge15_triangles import from_snapshot, generate

CONTROLS = (
    ((54, 58), 68),
    ((48, 60), 24),
    ((133,), 47),
    ((37,), 53),
    ((123,), 66),
    ((11,), 22),
    ((65,), 25),
    ((21, 30), 63),
    ((54, 40), 140),
    ((25,), 105),
    ((66, 37, 74), 37),
    ((97,), 388),
    ((18, 8, 81), 16),
    ((12, 16, 0), 20),
    ((6, 8, 0), Fraction(4, 5)),
    ((20, 8), 20),
    ((18, 3, 1), 54),
    ((68,), 22),
    ((4, 9), 18),
    ((10, 5), 25),
    ((6, 10, 1, 3), 10),
    ((13, 2, 5), Fraction(2, 5)),
)


@pytest.mark.parametrize("n,control", enumerate(CONTROLS, 1))
def test_source_answers_and_independent_coordinates(n, control):
    p, expected = control
    _, hints, solution, value = content(n, p)
    assert value == expected
    validate(n, p, construct(n, p), value)
    assert hints and solution


@pytest.mark.parametrize(
    "n,p,expected",
    [(14, (40, 9, 1), 9), (15, (6, 8, 1), Fraction(3, 5)), (15, (2, 5, 2), Fraction(2, 5))],
)
def test_additional_confirmed_question_variants(n, p, expected):
    value = content(n, p)[3]
    assert value == expected
    validate(n, p, construct(n, p), value)


@pytest.mark.parametrize("family", ALL_FAMILIES)
def test_complete_seed_smoke_and_replay(family):
    for seed in range(10):
        problem = generate(family, seed, VERSION)
        assert from_snapshot(problem.to_snapshot()) == problem


@pytest.mark.parametrize("family", ALL_FAMILIES)
def test_consistent_other_seed_replacement_rejected(family):
    original = generate(family, 42, VERSION).to_snapshot()
    other_seed = 43
    forged = generate(family, other_seed, VERSION).to_snapshot()
    while forged["parameters"] == original["parameters"]:
        other_seed += 1
        forged = generate(family, other_seed, VERSION).to_snapshot()
    forged.update(seed=original["seed"], problem_id=original["problem_id"])
    with pytest.raises(ValueError):
        from_snapshot(forged)


@pytest.mark.parametrize(
    "n,key",
    [
        (2, "D"),
        (4, "H"),
        (5, "B"),
        (6, "H"),
        (7, "M"),
        (8, "M"),
        (9, "H"),
        (10, "K"),
        (11, "N"),
        (12, "D"),
        (13, "M"),
        (14, "C"),
        (15, "C"),
        (16, "C"),
        (17, "C"),
        (18, "C"),
        (19, "C"),
        (20, "H"),
        (21, "B"),
        (22, "H"),
    ],
)
def test_coordinate_mutations_fail_independent_oracle(n, key):
    p = CONTROLS[n - 1][0]
    scene = construct(n, p)
    x, y = scene["points"][key]
    scene["points"][key] = (x + 1, y + 0.5)
    with pytest.raises(ValueError):
        validate(n, p, scene, content(n, p)[3])


@pytest.mark.parametrize("mutation", ["extra_line", "missing_edge", "label", "hash", "version"])
def test_snapshot_and_final_pixels_fail_closed(mutation):
    snapshot = generate("OGE15-F10", 42, VERSION).to_snapshot()
    if mutation == "hash":
        snapshot["image_sha256"] = "0" * 64
    elif mutation == "version":
        snapshot["renderer_version"] = "unknown"
    else:
        image = Image.open(BytesIO(base64.b64decode(snapshot["png_base64"])))
        if mutation == "extra_line":
            ImageDraw.Draw(image).line((40, 40, 680, 480), fill="black", width=3)
        elif mutation == "missing_edge":
            ImageDraw.Draw(image).rectangle((0, 230, 720, 290), fill="white")
        else:
            ImageDraw.Draw(image).text((40, 40), "X", fill="black")
        out = BytesIO()
        image.save(out, format="PNG")
        png = out.getvalue()
        snapshot.update(
            png_base64=base64.b64encode(png).decode(), image_sha256=hashlib.sha256(png).hexdigest()
        )
        with pytest.raises(ValueError):
            audit(png, snapshot["geometry"])
    with pytest.raises(ValueError):
        from_snapshot(snapshot)
    with pytest.raises(ValueError):
        from_snapshot(snapshot, audit_pixels=False)


def test_pixel_oracle_catches_a_renderer_that_repeats_extra_line(monkeypatch):
    from app.math import oge15_render

    s = generate("OGE15-F10", 42, VERSION).to_snapshot()
    image = Image.open(BytesIO(base64.b64decode(s["png_base64"])))
    ImageDraw.Draw(image).line((40, 40, 680, 480), fill="black", width=3)
    out = BytesIO()
    image.save(out, format="PNG")
    png = out.getvalue()
    monkeypatch.setattr(oge15_render, "render", lambda *args: png)
    with pytest.raises(ValueError, match="Unexpected triangle construction"):
        audit(png, s["geometry"])


def test_legacy_snapshot_cannot_attach_unversioned_png():
    old = generate("OGE15-F03", 42).to_snapshot()
    old["png_base64"] = generate("OGE15-F03", 42, VERSION).to_snapshot()["png_base64"]
    with pytest.raises(ValueError, match="unversioned geometry"):
        from_snapshot(old)


def test_complete_regression_vectors_remain_exact():
    import json
    from pathlib import Path

    for vector in json.loads(Path("atlas/oge15_complete_regression_vectors.json").read_text()):
        snapshot = generate(
            vector["family_id"], vector["seed"], VERSION,
            renderer_version=vector.get("renderer_version")
        ).to_snapshot()
        snapshot.pop("png_base64", None)
        assert snapshot == vector


@pytest.mark.parametrize("n,control", enumerate(CONTROLS, 1))
def test_coordinate_tolerance_cannot_accept_a_nearly_correct_answer(n, control):
    p, expected = control
    with pytest.raises(ValueError, match="Exact triangle answer invariant"):
        validate(n, p, construct(n, p), Fraction(expected) + Fraction(1, 10**10))


@pytest.mark.parametrize("family,seed", [("OGE15-F03", 7), ("OGE15-F05", 0), ("OGE15-F09", 6)])
def test_new_baseline_labels_leave_the_edge_clear_and_replay_both_rasters(family, seed):
    from app.math.oge15_render import VERSION as OLD_RENDERER
    from app.math.oge15_render import layout
    from app.persistence.image_retention import compact_snapshot, restore_graphic_snapshot

    old = generate(family, seed, VERSION, renderer_version=OLD_RENDERER).to_snapshot()
    current = generate(family, seed, VERSION).to_snapshot()
    assert old["image_sha256"] != current["image_sha256"]
    assert {key for key in old if old[key] != current[key]} == {
        "renderer_version", "image_sha256", "png_base64"
    }
    for saved in (old, current):
        assert from_snapshot(saved).to_snapshot() == saved
        assert restore_graphic_snapshot(compact_snapshot(saved)) == saved
    name = "H" if family.endswith("09") else "C"
    x, y = map(round, layout(current["geometry"])[name])
    with Image.open(BytesIO(base64.b64decode(current["png_base64"]))) as image:
        # White space between the horizontal baseline and the full glyph below it.
        assert image.crop((x - 12, y + 6, x + 12, y + 14)).convert("L").getextrema() == (255, 255)
        assert image.crop((x - 14, y + 15, x + 14, y + 47)).convert("L").getextrema()[0] < 64
