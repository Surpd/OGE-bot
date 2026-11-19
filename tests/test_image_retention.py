from __future__ import annotations

import pytest

from app.math.inequalities import generate as generate_task13
from app.math.oge07_graph import generate_graph_problem
from app.math.oge11 import generate as generate_task11
from app.persistence.image_retention import (
    can_compact_snapshot,
    compact_snapshot,
    image_payload_keys,
    restore_graphic_snapshot,
)


def test_task7_png_snapshot_compacts_and_restores_exact_payload() -> None:
    original = generate_graph_problem("OGE07-N01", 700_001).to_snapshot()
    compacted = compact_snapshot(original)

    assert image_payload_keys(compacted) == frozenset()
    assert compacted["condition"] == original["condition"]
    assert compacted["graph_png_sha256"] == original["graph_png_sha256"]
    assert can_compact_snapshot(original)
    assert restore_graphic_snapshot(compacted) == original


def test_task11_png_snapshot_compacts_and_restores_exact_payload() -> None:
    original = generate_task11("OGE11-F01", 1_100_001).to_snapshot()
    compacted = compact_snapshot(original)

    assert image_payload_keys(compacted) == frozenset()
    assert compacted["condition"] == original["condition"]
    assert compacted["image_sha256"] == original["image_sha256"]
    assert can_compact_snapshot(original)
    assert restore_graphic_snapshot(compacted) == original


def test_task13_graph_svg_payload_compacts_and_restores_exact_content() -> None:
    original = generate_task13("OGE13-S02", 1_300_001).to_snapshot()
    original.update(
        {
            "selection_attempts": 3,
            "_family_queue_after": ["OGE13-S03"],
            "_last_family_after": "OGE13-S02",
        }
    )
    compacted = compact_snapshot(original)

    assert image_payload_keys(compacted) == frozenset()
    assert compacted["condition"] == original["condition"]
    assert can_compact_snapshot(original)
    assert restore_graphic_snapshot(compacted) == original


def test_compaction_fails_closed_for_changed_semantics_and_unknown_versions() -> None:
    task7 = compact_snapshot(generate_graph_problem("OGE07-N01", 700_002).to_snapshot())
    task7["condition"] = "подменённое условие"
    assert restore_graphic_snapshot(task7) is None

    task11 = compact_snapshot(generate_task11("OGE11-F01", 1_100_002).to_snapshot())
    task11["generator_version"] = "unknown-version"
    assert restore_graphic_snapshot(task11) is None


@pytest.mark.parametrize("family,seed", [
    ("OGE15-F03", 1_500_301),
    ("OGE17-R03", 1_700_301),
    ("OGE18-D05", 1_800_301),
])
def test_new_versioned_graphic_families_compact_and_restore_exact_snapshot(family, seed):
    if family.startswith("OGE15-"):
        from app.math.oge15_complete import VERSION
        from app.math.oge15_triangles import generate

        generator_version = VERSION
    elif family.startswith("OGE17-"):
        from app.math.oge17_generator import generate

        generator_version = None
    else:
        from app.math.oge18 import GENERATOR_VERSION_V2, generate

        generator_version = GENERATOR_VERSION_V2

    original = (
        generate(family, seed, generator_version).to_snapshot()
        if generator_version is not None
        else generate(family, seed).to_snapshot()
    )
    compacted = compact_snapshot(original)
    assert image_payload_keys(compacted) == frozenset()
    assert can_compact_snapshot(original)
    restored = restore_graphic_snapshot(compacted)
    assert restored == original


def test_graphic_compaction_refuses_to_strip_shared_mixed_scenario_context():
    original = generate_task13("OGE13-S02", 1_300_302).to_snapshot()
    original["_original_scenario_snapshot"] = {"images": {"png_base64": "aW1hZ2U="}}
    original["_original_scenario_snapshot_sha256"] = "retained-with-context"
    assert not can_compact_snapshot(original)
