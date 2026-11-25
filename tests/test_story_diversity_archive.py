"""Actual immutable snapshots from PR 115, before the geometry and paper expansion."""
import json
from pathlib import Path

import pytest

from app.adaptive.sources import scenario_variant
from app.bot.scenario_training import public_registry
from app.math.scenario_engine import ScenarioSnapshot, restore_asset_bytes
from app.math.scenarios.mobile_photos import scenario_photos

FIXTURES = Path(__file__).parent / "fixtures" / "story_diversity"


@pytest.mark.parametrize("story", ["FLAT", "GARDEN", "PAPER", "TARIFF"])
def test_pr115_archived_scenario(story):
    payload = json.loads((FIXTURES / f"{story}.json").read_text(encoding="utf-8"))
    scene = ScenarioSnapshot.from_snapshot(payload)
    assert scene.to_snapshot() == payload
    adapter = public_registry().adapter(story)
    for asset in scene.assets:
        assert restore_asset_bytes(adapter.renderer, scene, asset)
    assert all(photo.startswith(b"\x89PNG") for photo in scenario_photos(scene))
    for q in scene.questions:
        assert scenario_variant(scene, q.position)
        policy = adapter.answer_policies[q.answer_policy_id, q.answer_policy_version]
        assert policy.accepts(q.canonical_answer, q.canonical_answer)
