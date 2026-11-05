from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from aiogram.types import Message
from PIL import Image, ImageDraw

from app.bot.scenario_training import public_registry, render_session
from app.math.scenario_engine import (
    PracticeMode,
    PracticeRequest,
    build_practice_plan,
    restore_asset_bytes,
)
from app.math.scenarios.mobile_photos import scenario_photos, stove_arc
from app.persistence.scenario_repository import ScenarioPostgresRepository, ScenarioSession


@pytest.mark.parametrize(
    ("story", "count"),
    [("TYRES", 2), ("PAPER", 2), ("STOVE", 2), ("TARIFF", 2), ("GARDEN", 1), ("FLAT", 1)],
)
@pytest.mark.parametrize("seed", [0, 42, 90126])
def test_mobile_photos_are_deterministic_and_preserve_snapshot(story, count, seed):
    registry = public_registry()
    snapshot = build_practice_plan(
        PracticeRequest(PracticeMode.FULL, seed, story), registry
    ).snapshot
    before = snapshot.to_snapshot()
    photos = scenario_photos(snapshot)
    assert len(set(photos)) == count
    assert photos == scenario_photos(snapshot)
    assert snapshot.to_snapshot() == before
    for ref in snapshot.assets:
        assert restore_asset_bytes(registry.adapter(story).renderer, snapshot, ref)
    for photo in photos:
        with Image.open(BytesIO(photo)) as image:
            assert image.format == "PNG"
            assert image.width >= 780
            image.verify()


def test_arc_photo_labels_only_known_dimensions(monkeypatch):
    labels = []
    original = ImageDraw.ImageDraw.text

    def capture(draw, xy, text, *args, **kwargs):
        labels.append(text)
        return original(draw, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", capture)
    stove_arc({"arc_width_cm": 60, "arc_height_cm": 40})
    assert labels == ["Арка кожуха печи", "O", "60 см", "40 см"]

@pytest.mark.asyncio
@pytest.mark.parametrize(("story", "count"), [
    ("TYRES", 2), ("PAPER", 2), ("STOVE", 2), ("TARIFF", 2), ("GARDEN", 1), ("FLAT", 1),
])
async def test_public_card_sends_only_photos_for_graphics(story, count):
    registry = public_registry()
    snapshot = build_practice_plan(
        PracticeRequest(PracticeMode.FULL, 42, story), registry
    ).snapshot
    session = ScenarioSession(
        uuid4(), uuid4(), PracticeMode.FULL, "active", 1, 0, "active", 0, 0, None, None, snapshot,
    )
    message = AsyncMock(spec=Message)
    message.answer = AsyncMock(return_value=SimpleNamespace(message_id=10))
    message.answer_photo = AsyncMock()
    message.answer_document = AsyncMock()
    store = AsyncMock(spec=ScenarioPostgresRepository)
    await render_session(message, store, session, show_assets=True, user_id_override=1)
    assert message.answer_photo.await_count == count
    message.answer_document.assert_not_awaited()
    for call in message.answer_photo.await_args_list:
        upload = call.args[0]
        assert upload.filename.endswith(".png")
        assert upload.data.startswith(b"\x89PNG\r\n\x1a\n")
