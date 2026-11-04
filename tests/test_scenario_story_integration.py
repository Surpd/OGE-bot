from __future__ import annotations

import json
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from typing import cast

from app.math.scenario_engine import (
    FamilyRegistry,
    PracticeMode,
    PracticeRequest,
    StoryAdapter,
    build_practice_plan,
    discover_story_registry,
    restore_asset_bytes,
)

_TEST_ACTIVATION = {
    "TYRES": {
        "TYRES-TABLE-EXTREME", "TYRES-SIDEWALL", "TYRES-DIAMETER",
        "TYRES-RADIUS-DELTA", "TYRES-PERCENT-ROTATION",
    },
    "PAPER": {
        "PAPER-F01", "PAPER-F02", "PAPER-F03", "PAPER-F04", "PAPER-F06", "PAPER-F07",
    },
    "TARIFF": {
        "TARIFF-F01-MONTHS-MINUTES", "TARIFF-F04-MONTHLY-BILL", "TARIFF-F05-EXTREMUM",
        "TARIFF-F09-PERCENT-FEE", "TARIFF-F12-HOME-ISP",
    },
    "GARDEN": {
        "GARDEN-01-IDENTIFY", "GARDEN-02-TILES-PACKS", "GARDEN-04-PERIMETER-POLYGON",
        "GARDEN-07-PERCENT-BUILDINGS", "GARDEN-09-HEAT-BREAKEVEN",
    },
    "ROUTE": {
        "ROUTE-F01-GRID-MATCH", "ROUTE-F03-ROAD-SUM", "ROUTE-F05-PYTHAGORAS",
        "ROUTE-F06-HIGHWAY-TIME", "ROUTE-F09-SHOPPING-MIN",
    },
    "STOVE": {
        "STOVE-F01-CAPACITY-LIMITS", "STOVE-F02-ATTRIBUTE-MATCH", "STOVE-F03-VOLUME",
        "STOVE-F04-FLOOR-AREA", "STOVE-F05-WALL-AREA-NET", "STOVE-F06-PURCHASE-EXTRA-COSTS",
        "STOVE-F07-FIT-WOOD-DELIVERY", "STOVE-F08-COST-COMPARISON", "STOVE-F09-DIRECT-DISCOUNT",
        "STOVE-F10-REVERSE-DISCOUNT", "STOVE-F11-CONDITIONAL-TWO-DISCOUNTS",
        "STOVE-F12-ARCH-RADIUS",
    },
    "FLAT": {
        "FLAT-01-ROOM-MATCH", "FLAT-02-TILE-PACK", "FLAT-02-PARQUET-PACK", "FLAT-03-RECT-AREA",
        "FLAT-04-RECT-PERCENT", "FLAT-05-WASHER-MIN", "FLAT-05-INTERNET-MIN",
    },
}


def _explicit_test_adapter(adapter: StoryAdapter, family_ids: set[str]) -> StoryAdapter:
    families = tuple(
        replace(
            family,
            enabled=family.family_id in family_ids
            and family.status.value == "enabled_candidate",
        )
        for family in adapter.family_registry
    )
    return cast(StoryAdapter, SimpleNamespace(
        story_code=adapter.story_code,
        generator=adapter.generator,
        question_builder=adapter.question_builder,
        independent_oracle=adapter.independent_oracle,
        renderer=adapter.renderer,
        answer_policies=adapter.answer_policies,
        family_registry=families,
    ))


def test_all_story_adapters_support_single_and_full_with_one_restorable_snapshot() -> None:
    production_registry = discover_story_registry()
    assert set(production_registry.story_codes) == set(_TEST_ACTIVATION)

    for story_code, enabled_ids in _TEST_ACTIVATION.items():
        adapter = _explicit_test_adapter(production_registry.adapter(story_code), enabled_ids)
        registry = FamilyRegistry((adapter,))
        full = build_practice_plan(
            PracticeRequest(PracticeMode.FULL, seed=20261104, story_code=story_code), registry
        )
        assert full.selected_positions == (1, 2, 3, 4, 5)
        assert tuple(q.position for q in full.snapshot.questions) == (1, 2, 3, 4, 5)
        assert {q.scenario_seed for q in full.snapshot.questions} == {20261104}
        assert all(q.family_id in enabled_ids for q in full.snapshot.questions)

        for position in range(1, 6):
            single = build_practice_plan(
                PracticeRequest(
                    PracticeMode.SINGLE, seed=20261104, story_code=story_code, position=position
                ),
                registry,
            )
            assert single.snapshot == full.snapshot
            assert single.selected_positions == (position,)

        for asset in full.snapshot.assets:
            restored = restore_asset_bytes(adapter.renderer, full.snapshot, asset)
            assert sha256(restored).hexdigest() == asset.sha256


def test_family_backlog_covers_all_research_families_and_preserves_distinct_states() -> None:
    backlog = json.loads(
        (Path(__file__).resolve().parents[1] / "atlas" / "family_backlog.json").read_text(
            encoding="utf-8"
        )
    )
    families = backlog["families"]
    assert backlog["family_count"] == len(families) == 77
    assert len({item["family_id"] for item in families}) == len(families)
    required = {
        "story", "family_id", "original_status", "implemented_in_code",
        "available_to_students", "reason", "source_ids", "next_action",
    }
    assert all(required <= item.keys() for item in families)
    assert all(item["available_to_students"] is False for item in families)
    states = {item["implementation_status"] for item in families}
    assert {
        "implemented_but_disabled", "not_implemented", "research_only",
        "source_not_confirmed", "blocked_math", "blocked_source",
    } <= states
