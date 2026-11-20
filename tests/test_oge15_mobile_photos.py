from dataclasses import replace
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
from app.math.scenarios import mobile_photos
from app.math.scenarios.mobile_photos import (
    scenario_photos,
    scenario_photos_for_question,
    stove_arc,
)
from app.persistence.scenario_repository import ScenarioPostgresRepository, ScenarioSession


@pytest.mark.parametrize(
    ("story", "count"),
    [("TYRES", 2), ("PAPER", 2), ("STOVE", 2), ("TARIFF", 2), ("GARDEN", 2), ("FLAT", 1)],
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


def test_paper_telegram_table_uses_unlabeled_rows(monkeypatch):
    snapshot = build_practice_plan(
        PracticeRequest(PracticeMode.FULL, 42, "PAPER"), public_registry()
    ).snapshot
    captured: dict[str, object] = {}

    def capture_table(title, rows, widths):
        captured.update(title=title, rows=rows, widths=widths)
        return b"png-fixture"

    monkeypatch.setattr(mobile_photos, "table", capture_table)
    assert mobile_photos.table_photos(snapshot) == (b"png-fixture",)
    rows = captured["rows"]
    assert isinstance(rows, list)
    assert rows[0] == ["Строка", "Длина, мм", "Ширина, мм"]
    assert rows[1:] == [
        [str(index), str(length), str(width)]
        for index, (_, length, width) in enumerate(
            mobile_photos.PAPER._get_rows(snapshot.context), 1
        )
    ]
    assert all(row[0] not in {"A0", "A1", "A2", "A3", "A4", "A5"} for row in rows[1:])


def test_arc_photo_labels_only_known_dimensions(monkeypatch):
    labels = []
    original = ImageDraw.ImageDraw.text

    def capture(draw, xy, text, *args, **kwargs):
        labels.append(text)
        return original(draw, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", capture)
    stove_arc({"arc_width_cm": 60, "arc_height_cm": 40})
    assert labels == ["Арка кожуха печи", "O", "60 см", "40 см"]


def test_legacy_garden_snapshot_without_raw_heating_operands_keeps_plan_only():
    registry = public_registry()
    snapshot = build_practice_plan(
        PracticeRequest(PracticeMode.FULL, 0, "GARDEN"), registry
    ).snapshot
    legacy_context = {
        **snapshot.context,
        "world_version": "garden-sosnovka-1.3",
        "heat": {
            "gas_upfront": 35_370,
            "electric_upfront": 29_000,
            "gas_hourly_cents": 784,
            "electric_hourly_cents": 2058,
            "break_even_hours": 500,
        },
    }
    legacy_snapshot = replace(
        snapshot,
        generator_version="garden-sosnovka-1.3",
        context=legacy_context,
    )
    assert len(scenario_photos(legacy_snapshot)) == 1

@pytest.mark.asyncio
@pytest.mark.parametrize("story", ("TYRES", "PAPER", "STOVE", "TARIFF", "GARDEN", "FLAT"))
async def test_public_card_sends_only_materials_needed_for_current_question(story):
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
    store.close_legacy_with_exposed_answer.return_value = False
    await render_session(message, store, session, show_assets=True, user_id_override=1)
    expected = scenario_photos_for_question(snapshot, session.current_position)
    assert message.answer_photo.await_count == len(expected)
    assert [call.args[0].data for call in message.answer_photo.await_args_list] == list(expected)
    card = message.answer.await_args.args[0]
    assert "попыток" not in card
    assert "подсказок" not in card
    if story == "STOVE":
        assert all("Печь | Тип |" not in call.args[0] for call in message.answer.await_args_list)
    if (
        story == "GARDEN"
        and session.snapshot.questions[0].family_id != "GARDEN-09-HEAT-BREAKEVEN"
    ):
        assert all(
            "Отопление одного дома" not in call.args[0]
            for call in message.answer.await_args_list
        )
    message.answer_document.assert_not_awaited()
    for call in message.answer_photo.await_args_list:
        upload = call.args[0]
        assert upload.filename.endswith(".png")
        assert upload.data.startswith(b"\x89PNG\r\n\x1a\n")


def test_paper_photo_bisects_the_remaining_sheet_along_its_long_side():
    with Image.open(BytesIO(mobile_photos.paper_diagram())) as image:
        # A1 occupies the whole right half. The A2 cut ends at the first fold.
        assert image.getpixel((450, 600)) != (255, 255, 255)
        assert image.getpixel((360, 384)) != (255, 255, 255)
        assert image.getpixel((570, 384)) == (255, 255, 255)
        # The A3 cut ends at A2 and never divides the right half.
        assert image.getpixel((242, 352)) != (255, 255, 255)
        assert image.getpixel((242, 415)) == (255, 255, 255)


def test_tariff_png_uses_shared_months_and_both_axes_at_the_saved_scale():
    # Include 0, 400 min / 4 GB, quarter units and a pair of coincident points.
    minutes = (400, 0, 25, 225) * 3
    quarters = (0, 16, 1, 15) * 3
    payload = mobile_photos.tariff_chart({"minutes": minutes, "gb_quarters": quarters})
    orange, blue = (173, 67, 14), (20, 86, 138)
    with Image.open(BytesIO(payload)) as image:
        for month, (duration, traffic) in enumerate(zip(minutes, quarters, strict=True)):
            x = 128 + 64 * month
            assert image.getpixel((x, 564 - duration * 480 // 400)) == orange
            assert image.getpixel((x, 564 - traffic * 480 // 16 - 11)) == blue

    payload = mobile_photos.tariff_chart({"minutes": (200,) * 12, "gb_quarters": (8,) * 12})
    with Image.open(BytesIO(payload)) as image:
        assert image.getpixel((128, 324)) == orange
        assert image.getpixel((128, 313)) == blue
        assert image.getpixel((144, 324)) == blue  # Dash over the coincident solid line.
        assert image.getpixel((151, 324)) == orange  # Gap in the dashed series.


def test_garden_cells_continue_inside_the_house_footprint():
    snapshot = build_practice_plan(
        PracticeRequest(PracticeMode.FULL, 42, "GARDEN"), public_registry()
    ).snapshot
    with Image.open(BytesIO(mobile_photos.garden_plan(snapshot))) as image:
        # Inside the upper wing, adjoining square cells are 60 image pixels wide.
        for x in (510, 570, 630):
            assert image.getpixel((x, 170)) != image.getpixel((x + 8, 170))
