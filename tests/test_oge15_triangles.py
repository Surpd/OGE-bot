"""Source fixtures, independent invariants and immutable replay."""

import json
from fractions import Fraction
from pathlib import Path

import pytest

from app.math.oge15_oracle import answer
from app.math.oge15_triangles import FAMILIES, POLICY, content, from_snapshot, generate

VECTORS = [
    ((54, 58), 68),
    ((133,), 47),
    ((66, 37, 74), 37),
    ((12, 16), 20),
    ((4, 9), 18),
    ((10, 5), 25),
]


@pytest.mark.parametrize("family,case", zip(FAMILIES, VECTORS, strict=True))
def test_source_control_and_independent_oracle(family, case):
    parameters, expected = case
    assert answer(family, parameters) == expected
    assert content(family, parameters)[3] == expected


@pytest.mark.parametrize("family", FAMILIES)
def test_mass_oracle_and_replay(family):
    for seed in range(300):
        problem = generate(family, seed)
        s = problem.to_snapshot()
        assert answer(family, tuple(s["parameters"])) == POLICY.parse(s["correct_answer"])
        assert from_snapshot(s) == problem == generate(family, seed)
        assert s["hints"] and s["solution"]
        assert POLICY.accepts(s["correct_answer"].replace(".", ","), s["correct_answer"])


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize(
    "field", ["parameters", "condition", "solution", "correct_answer", "seed", "generator_version"]
)
def test_mutations_fail_closed(family, field):
    s = generate(family, 42).to_snapshot()
    s[field] = {"parameters": [0], "seed": 2, "generator_version": "bad"}.get(field, "bad")
    with pytest.raises(ValueError):
        from_snapshot(s)


@pytest.mark.parametrize("family", FAMILIES)
def test_other_seed_cannot_keep_identity(family):
    original = generate(family, 42).to_snapshot()
    forged = generate(family, 123).to_snapshot()
    forged.update(seed=original["seed"], problem_id=original["problem_id"])
    with pytest.raises(ValueError):
        from_snapshot(forged)


@pytest.mark.parametrize(
    "family,p",
    [
        (FAMILIES[0], (90, 90)),
        (FAMILIES[1], (180,)),
        (FAMILIES[2], (2, 2, 4)),
        (FAMILIES[3], (3, 5)),
        (FAMILIES[4], (0, 4)),
        (FAMILIES[5], (-2, 4)),
    ],
)
def test_degenerate_models_rejected(family, p):
    with pytest.raises(ValueError):
        answer(family, p)


def test_fraction_and_regression_vectors():
    assert answer(FAMILIES[4], (3, 5)) == Fraction(15, 2)
    assert POLICY.accepts("7,5", "7.5")
    for vector in json.loads(Path("atlas/oge15_regression_vectors.json").read_text()):
        assert generate(vector["family_id"], vector["seed"]).to_snapshot() == vector["snapshot"]


@pytest.mark.parametrize("seed", [-1, True, "42", 2**63])
def test_invalid_seed(seed):
    with pytest.raises(ValueError):
        generate(FAMILIES[0], seed)
