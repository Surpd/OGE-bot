"""Safe compaction and deterministic restoration of old task image payloads."""

from __future__ import annotations

import json
from copy import deepcopy
from functools import cache
from pathlib import Path
from typing import cast

_IMAGE_PAYLOAD_KEY_SUFFIXES = ("_base64",)
_IMAGE_PAYLOAD_KEYS = frozenset({"option_svgs"})
_SCHEDULER_METADATA_KEYS = frozenset(
    {"selection_attempts", "_family_queue_after", "_last_family_after"}
)


def image_payload_keys(value: object) -> frozenset[str]:
    """Return names of image payload fields without treating metadata as payload."""
    found: set[str] = set()

    def visit(node: object) -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                if isinstance(key, str) and (
                    key.endswith(_IMAGE_PAYLOAD_KEY_SUFFIXES) or key in _IMAGE_PAYLOAD_KEYS
                ):
                    found.add(key)
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(value)
    return frozenset(found)


def compact_snapshot(snapshot: dict[str, object]) -> dict[str, object]:
    """Strip image byte strings recursively while retaining all other snapshot data."""
    def strip(node: object) -> object:
        if isinstance(node, dict):
            return {
                key: strip(value)
                for key, value in node.items()
                if not (
                    isinstance(key, str)
                    and (key.endswith(_IMAGE_PAYLOAD_KEY_SUFFIXES) or key in _IMAGE_PAYLOAD_KEYS)
                )
            }
        if isinstance(node, list):
            return [strip(value) for value in node]
        return node

    result = strip(snapshot)
    return cast(dict[str, object], result)


def is_graphic_snapshot(snapshot: dict[str, object]) -> bool:
    """Recognize the currently stored PNG-backed families, including compacted rows."""
    if image_payload_keys(snapshot):
        return True
    family_id = snapshot.get("family_id")
    if not isinstance(family_id, str):
        return False
    if (family_id.startswith("OGE07-N") and "graph_png_sha256" in snapshot) or (
        family_id.startswith("OGE11-") and "image_sha256" in snapshot
    ):
        return True
    return family_id in oge13_graphic_families() and "rendering_version" in snapshot


@cache
def oge13_graphic_families() -> frozenset[str]:
    atlas_path = Path(__file__).resolve().parents[2] / "atlas/oge13_reference_structures.json"
    try:
        atlas = json.loads(atlas_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return frozenset()
    families = atlas.get("families")
    if not isinstance(families, list):
        return frozenset()
    return frozenset(
        str(item["family_id"])
        for item in families
        if isinstance(item, dict)
        and isinstance(item.get("answer_layout"), str)
        and item["answer_layout"].startswith("four_graphs")
    )


def restore_graphic_snapshot(snapshot: dict[str, object]) -> dict[str, object] | None:
    """Restore payload only after the compact snapshot matches its versioned generator."""
    family_id = snapshot.get("family_id")
    seed = snapshot.get("seed")
    if not isinstance(family_id, str) or type(seed) is not int:
        return None
    compacted = compact_snapshot(snapshot)

    try:
        if family_id.startswith("OGE07-N"):
            from app.math.oge07_graph import generate_graph_problem as generate_task7_graph

            expected = generate_task7_graph(family_id, seed).to_snapshot()
            if _generator_content(compacted) != _generator_content(expected):
                return None
            restored = deepcopy(snapshot)
            restored["graph_png_base64"] = expected["graph_png_base64"]
            return restored

        if family_id.startswith("OGE11-"):
            from app.math.oge11 import GENERATOR_VERSION
            from app.math.oge11 import generate as generate_task11

            version = snapshot.get("generator_version")
            if not isinstance(version, str) or version != GENERATOR_VERSION:
                return None
            expected = generate_task11(family_id, seed, version).to_snapshot()
            if _generator_content(compacted) != _generator_content(expected):
                return None
            restored = deepcopy(snapshot)
            restored["png_base64"] = expected["png_base64"]
            return restored

        if family_id in oge13_graphic_families():
            from app.math.inequalities import (
                GENERATOR_VERSION,
                validate_snapshot,
            )
            from app.math.inequalities import (
                generate as generate_task13,
            )

            version = snapshot.get("generator_version")
            if not isinstance(version, str) or version != GENERATOR_VERSION:
                return None
            expected = generate_task13(family_id, seed, version).to_snapshot()
            if _generator_content(compacted) != _generator_content(expected):
                return None
            restored = deepcopy(snapshot)
            restored["option_svgs"] = expected["option_svgs"]
            if not validate_snapshot(restored):
                return None
            return restored
    except (KeyError, TypeError, ValueError, RuntimeError):
        return None
    return None


def _generator_content(snapshot: dict[str, object]) -> dict[str, object]:
    return {
        key: _json_shape(value)
        for key, value in compact_snapshot(snapshot).items()
        if key not in _SCHEDULER_METADATA_KEYS
    }


def _json_shape(value: object) -> object:
    if isinstance(value, dict):
        return {key: _json_shape(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_json_shape(item) for item in value]
    return value


def can_compact_snapshot(snapshot: dict[str, object]) -> bool:
    """Check that a full PNG snapshot can be reconstructed byte-for-byte later."""
    if not is_graphic_snapshot(snapshot) or not image_payload_keys(snapshot):
        return False
    restored = restore_graphic_snapshot(compact_snapshot(snapshot))
    if restored is None:
        return False
    return restored == snapshot
