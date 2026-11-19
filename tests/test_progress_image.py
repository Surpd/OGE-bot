from __future__ import annotations

import io

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from PIL import Image

from app.bot.navigation import prepare_navigation_markup
from app.bot.progress import decode_record_ref, encode_record_ref, progress_keyboard
from app.bot.progress_image import (
    GRID_COLUMNS,
    GRID_ROWS,
    WIDTH,
    dashboard_tile_values,
    progress_image_keyboard,
    render_progress_image,
)
from app.persistence.training_insights import summarize
from scripts.generate_progress_previews import demo_insights


def test_dashboard_has_all_nineteen_tiles_and_correct_success_denominators() -> None:
    insights = demo_insights("full")
    tiles = dashboard_tile_values(insights)
    assert len(tiles) == 19
    assert [tile[0] for tile in tiles] == list(range(1, 20))
    for number, correct, answered, rate, sufficient in tiles:
        bucket = insights["numbers"][number]
        assert correct == bucket["correct"]
        assert answered == bucket["answered_tasks"]
        assert rate == f"{round(correct * 100 / answered)}%"
        assert sufficient is (answered >= 5)
    assert GRID_COLUMNS * GRID_ROWS >= 19


def test_empty_and_insufficient_samples_are_neutral_and_render_on_phone() -> None:
    empty = demo_insights("empty")
    partial = demo_insights("partial")
    assert all(tile[2:] == (0, "—", False) for tile in dashboard_tile_values(empty))
    partial_tiles = {tile[0]: tile for tile in dashboard_tile_values(partial)}
    assert partial_tiles[6][1:4] == (3, 4, "75%")
    assert partial_tiles[6][4] is False
    assert partial_tiles[11][1:4] == (2, 5, "40%")
    assert partial_tiles[11][4] is True

    for insights in (empty, partial, demo_insights("full")):
        png = render_progress_image(insights)
        with Image.open(io.BytesIO(png)) as image:
            assert image.format == "PNG"
            assert image.width == WIDTH
            assert image.height < 1300
            for width in (360, 375, 390):
                mobile = image.resize((width, round(image.height * width / image.width)))
                assert mobile.width == width
                assert mobile.height < 600
        assert len(png) < 10 * 1024 * 1024


def test_dashboard_handles_large_counts_and_long_recommendation_without_overflow() -> None:
    insights = demo_insights("full")
    insights["total"]["correct"] = 9_999_999_999
    insights["total"]["skipped"] = 1_234_567_890
    insights["total"]["answered_tasks"] = 9_999_999_999
    insights["total"]["success_rate"] = 100
    insights["numbers"][6]["correct"] = 9_999_999_999
    insights["numbers"][6]["answered_tasks"] = 9_999_999_999
    insights["numbers"][6]["success_rate"] = 100
    png = render_progress_image(insights)
    with Image.open(io.BytesIO(png)) as image:
        assert image.width == WIDTH
        assert image.getbbox() == (0, 0, image.width, image.height)


def test_summary_buttons_and_all_callback_payloads_fit_telegram_limit() -> None:
    markup = prepare_navigation_markup(progress_image_keyboard())
    assert [[button.text for button in row] for row in markup.inline_keyboard] == [
        ["📊 Подробнее о номере"],
        ["⚠️ Мои ошибки", "🕘 История"],
        ["🔄 Обновить", "↩ В меню"],
    ]
    callbacks = [button.callback_data for row in markup.inline_keyboard for button in row]
    assert all(
        callback is not None and len(callback.encode("utf-8")) <= 64 for callback in callbacks
    )
    demo_records = [
        {
            "record_id": "o:12345678-1234-5678-1234-567812345678",
            "number": 19,
            "family_id": "OGE19-FAMILY-WITH-A-LONG-NAME",
        }
    ]
    list_markup = prepare_navigation_markup(
        progress_keyboard("history:999999", 1, records=demo_records)
    )
    assert all(
        len(button.callback_data.encode("utf-8")) <= 64
        for row in list_markup.inline_keyboard
        for button in row
        if button.callback_data
    )


def test_record_callbacks_use_compact_reversible_source_references() -> None:
    refs = (
        "o:12345678-1234-5678-1234-567812345678",
        "m:12345678-1234-5678-1234-567812345678",
        "s:12345678-1234-5678-1234-567812345678:5",
    )
    for ref in refs:
        token = encode_record_ref(ref)
        assert decode_record_ref(token) == ref
        callback = f"progress:item:{token}:hzzzz"
        revised = prepare_navigation_markup(
            InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="Открыть", callback_data=callback)]]
            )
        )
        data = revised.inline_keyboard[0][0].callback_data
        assert data is not None and len(data.encode("utf-8")) <= 64


def test_dashboard_uses_existing_summary_values_without_changing_metrics() -> None:
    sample = summarize(
        [
            {
                "number": 7,
                "family_id": "OGE07-C01",
                "outcome": "solved",
                "attempt_records": [{"attempt_no": 1, "is_correct": True, "used_hint": False}],
            },
            {"number": 7, "family_id": "OGE07-C01", "outcome": "skipped", "attempt_records": []},
        ]
    )
    tile = dashboard_tile_values(sample)[6]
    assert tile == (7, 1, 1, "100%", False)
