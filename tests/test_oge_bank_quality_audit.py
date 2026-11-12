from __future__ import annotations

from app.bot.scenario_training import PUBLIC_FAMILIES
from app.bot.trainings import TRAININGS
from scripts.oge_bank_quality_audit import (
    COMPLEXITY,
    SCENARIO_COMPLEXITY,
    _disabled_inventory,
    _ordinary_generator,
    _seed_sequence,
)


def test_fixed_seed_samples_are_reproducible_and_c04_keeps_regression_seed() -> None:
    assert _seed_sequence(7, "OGE07-C04", 300) == _seed_sequence(7, "OGE07-C04", 300)
    assert _seed_sequence(7, "OGE07-C04", 300)[0] == 6
    assert len(set(_seed_sequence(7, "OGE07-C04", 300))) == 300


def test_complexity_rubric_covers_every_runtime_enabled_family() -> None:
    scenario_families = {family for values in PUBLIC_FAMILIES.values() for family in values}
    assert scenario_families == set(SCENARIO_COMPLEXITY)
    assert all(1 <= score <= 5 for score in SCENARIO_COMPLEXITY.values())
    for training in TRAININGS:
        if training.available and training.number >= 6:
            runtime_families, _ = _ordinary_generator(training.number)
            assert set(runtime_families) == set(COMPLEXITY[training.number])
            assert all(1 <= score <= 5 for score in COMPLEXITY[training.number].values())


def test_disabled_inventory_has_a_reason_or_explicit_reference_gap() -> None:
    rows = _disabled_inventory()
    assert rows
    assert all(row["family_id"] and row["runtime_status"] for row in rows)
    assert all(row.get("reason") for row in rows)
