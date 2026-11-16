"""Source controls, coordinate counterexamples, immutable replay and finite queues."""

import base64
import copy
import hashlib
import json
from fractions import Fraction
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image, ImageDraw

from app.math.oge16_circles import (
    ENABLED_FAMILIES,
    FAMILIES,
    POLICY,
    content,
    from_snapshot,
    generate,
    parameters,
)
from app.math.oge16_oracle import audit, solve_visible
from app.math.oge16_scheduler import build_task16_candidate_batch


@pytest.mark.parametrize("family", FAMILIES)
def test_randomized_text_geometry_png_and_saved_replay(family):
    for seed in range(40):
        original = generate(family, seed)
        s = original.to_snapshot()
        assert audit(s) == POLICY.parse(s["correct_answer"])
        with patch(
            "app.math.oge16_render.render", side_effect=AssertionError("must use saved PNG")
        ):
            restored = from_snapshot(json.loads(json.dumps(s)))
        assert restored == original
        assert restored.png == original.png
        assert original == generate(family, seed)
        s["correct_answer"] = "-999"
        assert original.to_snapshot()["correct_answer"] != "-999"


@pytest.mark.parametrize("family", FAMILIES)
def test_main_sample_independent_visible_oracle(family):
    for seed in range(300):
        p = parameters(family, seed)
        text, hints, steps, result, geometry = content(family, p)
        assert solve_visible(family, text, geometry.to_dict()) == result
        assert len(hints) >= 1 and len(steps) >= 2


def test_source_vectors_and_stable_versioned_snapshots():
    data = json.loads(Path("atlas/oge16_regression_vectors.json").read_text())
    for case in data["source_cases"]:
        f = case["family_id"]
        p = tuple(Fraction(v) for v in case["parameters"])
        text, _, _, result, scene = content(f, p)
        assert result == Fraction(case["answer"])
        assert solve_visible(f, text, scene.to_dict()) == result
    for case in data["snapshots"]:
        s = generate(case["family_id"], case["seed"]).to_snapshot()
        assert s["fingerprint"] == case["fingerprint"]
        assert s["geometry"] == case["geometry"]
        assert s["correct_answer"] == case["correct_answer"]
        assert s["figure"]["sha256"] == case["png_sha256"]


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize(
    "field",
    [
        "condition",
        "hints",
        "solution",
        "correct_answer",
        "parameters",
        "answer_policy_id",
        "answer_policy_version",
    ],
)
def test_independent_audit_rejects_every_visible_or_policy_mutation(family, field):
    s = generate(family, 42).to_snapshot()
    s[field] = ["corrupt"] if isinstance(s[field], list) else "corrupt"
    with pytest.raises(ValueError):
        audit(s, pixels=False)


@pytest.mark.parametrize("family", FAMILIES)
def test_target_vertex_and_visible_number_are_checked(family):
    s = generate(family, 42).to_snapshot()
    original = s["condition"]
    # A plausible, different task with the old answer is still invalid.
    replacements = {
        "OGE16-A02": ("ACB", "ABC"),
        "OGE16-A05": ("угол C", "угол B"),
        "OGE16-B01": ("Найдите BT", "Найдите AB"),
        "OGE16-B03": ("Найдите AB", "Найдите AM"),
        "OGE16-C01": ("площадь", "периметр"),
        "OGE16-D01": ("угол C", "угол B"),
    }
    before, after = replacements[family]
    s["condition"] = original.replace(before, after)
    with pytest.raises(ValueError):
        audit(s, pixels=False)
    import re

    s["condition"] = re.sub(r"\d+", lambda m: str(int(m.group()) + 1), original, count=1)
    with pytest.raises(ValueError):
        audit(s, pixels=False)


@pytest.mark.parametrize(
    "kind",
    [
        "major_arc",
        "reversed_arc",
        "secant",
        "not_diameter",
        "off_circle",
        "not_midpoint",
        "not_tangent_square",
        "bow_tie",
    ],
)
def test_geometric_counterexamples_do_not_pass_with_same_text_and_answer(kind):
    family = {
        "major_arc": FAMILIES[0],
        "reversed_arc": FAMILIES[0],
        "secant": FAMILIES[2],
        "not_diameter": FAMILIES[1],
        "off_circle": FAMILIES[5],
        "not_midpoint": FAMILIES[3],
        "not_tangent_square": FAMILIES[4],
        "bow_tie": FAMILIES[5],
    }[kind]
    s = generate(family, 42).to_snapshot()
    g = s["geometry"]
    if kind == "major_arc":
        g["points"]["C"] = [0.0, -1.0]  # still on the circle, wrong intercepted arc
    elif kind == "reversed_arc":
        g["arc"] = ["B", "A", "ccw_minor"]
    elif kind == "secant":
        g["points"]["T"] = [0.0, -g["radius"]]  # still on circle, BT no longer tangent
    elif kind == "not_diameter":
        g["points"]["C"] = [0.0, -1.0]  # on circle, AC is a chord
    elif kind == "off_circle":
        g["points"]["B"][0] += 0.15
    elif kind == "not_midpoint":
        g["points"]["M"][0] += 0.1
    elif kind == "not_tangent_square":
        g["radius"] *= 0.9  # circle inside the square is insufficient
    elif kind == "bow_tie":
        g["points"]["B"], g["points"]["C"] = g["points"]["C"], g["points"]["B"]
    with pytest.raises(ValueError):
        audit(s, pixels=False)


@pytest.mark.parametrize("kind", ["blank", "shift", "extra", "swap_labels", "crop", "hash"])
def test_pixel_mutations_fail_even_after_recomputing_checksum(kind):
    s = generate(FAMILIES[0], 42).to_snapshot()
    f = s["figure"]
    im = Image.open(BytesIO(base64.b64decode(f["png_base64"]))).convert("RGB")
    if kind == "blank":
        im = Image.new("RGB", im.size, "white")
    elif kind == "shift":
        shifted = Image.new("RGB", im.size, "white")
        shifted.paste(im, (7, 7))
        im = shifted
    elif kind == "extra":
        ImageDraw.Draw(im).line((10, 10, 100, 100), fill="black", width=3)
    elif kind == "swap_labels":
        labels = f["layout"]["labels"]
        labels["A"], labels["B"] = labels["B"], labels["A"]
    elif kind == "crop":
        f["layout"]["labels"]["C"] = [0, 0, 20, 30]
    elif kind == "hash":
        f["sha256"] = "0" * 64
    if kind in ("blank", "shift", "extra"):
        buf = BytesIO()
        im.save(buf, format="PNG")
        raw = buf.getvalue()
        f["png_base64"] = base64.b64encode(raw).decode()
        f["sha256"] = hashlib.sha256(raw).hexdigest()
    with pytest.raises(ValueError):
        audit(s)


@pytest.mark.parametrize(
    "field,value",
    [
        ("generator_version", "future"),
        ("seed", True),
        ("seed", -1),
        ("seed", 2**63),
        ("problem_id", "wrong"),
        ("fingerprint", "wrong"),
        ("provenance", {}),
        ("attempt_index", 3),
    ],
)
def test_restore_identity_versions_and_state_fail_closed(field, value):
    s = generate(FAMILIES[0], 42).to_snapshot()
    s[field] = value
    with pytest.raises(ValueError):
        from_snapshot(s)


def test_saved_attempts_and_queue_metadata_are_transport_only():
    s = generate(FAMILIES[0], 42).to_snapshot()
    s.update(attempt_index=1, _family_queue_after=[FAMILIES[1]])
    restored = from_snapshot(s).to_snapshot()
    assert restored == s
    assert POLICY.accepts("69,0", restored["correct_answer"])


def test_zero_distance_chord_and_irrational_cases():
    text, _, _, result, g = content(FAMILIES[3], (Fraction(5), Fraction(0)))
    assert solve_visible(FAMILIES[3], text, g.to_dict()) == result == 10
    g2 = copy.deepcopy(g.to_dict())
    g2["radius"] = 4
    with pytest.raises(ValueError):
        solve_visible(FAMILIES[3], text, g2)
    s = generate(FAMILIES[3], 42).to_snapshot()
    s["geometry"]["points"]["A"][0] = float("nan")
    with pytest.raises(ValueError):
        audit(s, pixels=False)


def test_closed_numeric_training_adapter_and_bounded_exhaustion():
    from app.bot.oge16_adapter import numeric_training_adapter
    from app.bot.training_engine import NUMERIC_TRAININGS

    assert ENABLED_FAMILIES == ()
    adapter = numeric_training_adapter()
    assert adapter.number == 16 and adapter.mode == "task16" and adapter.families == ()
    assert 16 not in NUMERIC_TRAININGS
    assert adapter.candidates({}, 42) == []
    # Exhaust every central-angle variant, without counting cosmetic rearrangements.
    recent = []
    for seed in range(1200):
        p = parameters(FAMILIES[0], seed)
        identity = json.dumps([FAMILIES[0], [str(v) for v in p]])
        recent.append(hashlib.sha256(identity.encode()).hexdigest())
    assert len(set(recent)) == 61
    state = {"recent_fingerprints": recent, "family_queue": [FAMILIES[0], FAMILIES[4]]}
    batch = build_task16_candidate_batch(state, 42, enabled_families=(FAMILIES[0], FAMILIES[4]))
    assert len(batch) == 1 and batch[0]["family_id"] == FAMILIES[4]
    assert batch[0]["selection_attempts"] == 13
    state["selected_family_id"] = FAMILIES[0]
    assert build_task16_candidate_batch(state, 42, enabled_families=FAMILIES) == []
    with pytest.raises(ValueError):
        build_task16_candidate_batch({}, 1, enabled_families=("OGE16-C06",))
