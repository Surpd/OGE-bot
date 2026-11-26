"""Actual immutable snapshots from PR 115, before the geometry and paper expansion."""
import json
import sys
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

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
    # The JSON fixtures were captured on Windows. PNG compression varies by
    # Pillow wheel and the released FLAT renderer used Arial when available.
    # Encode the original pixels (captured separately with its Linux fallback
    # font) with this wheel; the current renderer must reproduce all bytes.
    for i, asset in enumerate(scene.assets):
        if story in {"PAPER", "FLAT"} and asset.content_type == "image/png":
            suffix = "-fallback" if story == "FLAT" and sys.platform != "win32" else ""
            raster = FIXTURES / f"{story}-{i}{suffix}.png"
            original = raster.read_bytes()
            if sys.platform != "win32":
                stream = BytesIO()
                with Image.open(BytesIO(original)) as image:
                    image.save(stream, "PNG", compress_level=9 if story == "PAPER" else 6)
                original = stream.getvalue()
            digest = sha256(original).hexdigest()
            if sys.platform == "win32":
                assert digest == asset.sha256
            native_ref = replace(asset, sha256=digest, storage_key=f"sha256/{digest}.png")
            native = replace(scene, assets=tuple(native_ref if a == asset else a
                                                 for a in scene.assets))
            assert restore_asset_bytes(adapter.renderer, native, native_ref) == original
        else:
            assert restore_asset_bytes(adapter.renderer, scene, asset)
    assert all(photo.startswith(b"\x89PNG") for photo in scenario_photos(scene))
    for q in scene.questions:
        assert scenario_variant(scene, q.position)
        policy = adapter.answer_policies[q.answer_policy_id, q.answer_policy_version]
        assert policy.accepts(q.canonical_answer, q.canonical_answer)
