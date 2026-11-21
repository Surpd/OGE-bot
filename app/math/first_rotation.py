"""Prefer another mathematical topic when the current deck still offers one."""

import json
from functools import lru_cache
from pathlib import Path
from typing import cast


@lru_cache(maxsize=1)
def topics() -> dict[str, str]:
    return cast(
        dict[str, str],
        json.loads(Path(__file__).with_name("first_rotation_groups.json").read_text()),
    )


# Each unlisted family has its own mathematical construction. Aliases here share
# the same core operation despite different prompts, assets or answer fields.
_SHARED = (
    ("OGE06-F001-SUB", "OGE06-F008-REDUCED-NUMERATOR", "OGE06-F009-PRESCRIBED-NUMERATOR"),
    ("OGE07-C01", "OGE07-C06"),
    ("OGE07-C03", "OGE07-N01", "OGE07-N04"),
    ("OGE09-K2", "OGE09-K3"),
    ("OGE11-F01", "OGE11-F02"),
    ("OGE11-F03", "OGE11-F06"),
    ("OGE13-L01", "OGE13-L02"),
    ("OGE13-Q01", "OGE13-Q02", "OGE13-Q04"),
    ("OGE13-S01", "OGE13-S03"),
    ("OGE14-A03", "OGE14-A07", "OGE14-A08"),
    ("OGE14-G01", "OGE14-G02"),
    ("OGE16-A01", "OGE16-A03"),
    ("OGE17-E03", "OGE17-P07"),
    ("OGE17-T07", "OGE17-T08"),
)
_CONSTRUCTION = {family: group[0] for group in _SHARED for family in group}


def construction(family: str) -> str:
    return _CONSTRUCTION.get(family, family)


def rank_families(
    families: list[str],
    history: list[str],
    revisit: set[str],
) -> list[str]:
    """Stable tie breaks preserve shuffled order. All windows are newest first."""
    narrow = [construction(f) for f in history[:5]]
    broad = [topics().get(f, f) for f in history[:2]]

    def priority(family: str) -> tuple[int, bool, bool, bool, int]:
        operation = construction(family)
        topic = topics().get(family, family)
        age = history.index(family) if family in history else len(history)
        return (
            5 - narrow.index(operation) if operation in narrow else 0,
            broad == [topic, topic],
            broad[:1] == [topic],
            family not in revisit,
            -age,
        )

    return sorted(families, key=priority)


def rotate_tail(
    number: int,
    state: dict[str, object],
    other_family: str | None,
    revisit: set[str] | None = None,
) -> None:
    queue = state.get("family_queue")
    if number != 9 and isinstance(queue, list) and queue:
        history = [f for f in (other_family, state.get("last_family_id")) if isinstance(f, str)]
        state["family_queue"] = rank_families(queue, history, revisit or set())
