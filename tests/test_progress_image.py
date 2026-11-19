from __future__ import annotations

import io

from PIL import Image

from app.bot.navigation import navigation_revision, prepare_navigation_markup
from app.bot.progress_image import (
    PAGE_SIZE,
    _exclusive_segments,
    _status,
    progress_image_keyboard,
    render_progress_image,
)
from app.persistence.training_insights import summarize
from scripts.generate_progress_previews import demo_insights


def test_overview_categories_partition_completed_tasks() -> None:
    insights = demo_insights()
    segments = _exclusive_segments(insights["total"])

    assert sum(value for _, value, _ in segments) == insights["total"]["completed"] == 72
    assert dict((label, value) for label, value, _ in segments) == {
        "Без подсказки": 14,
        "С подсказкой": 6,
        "Старые данные · подсказка неизвестна": 4,
        "Две ошибки": 8,
        "Пропущено": 35,
        "Открыт разбор": 5,
    }


def test_solution_viewed_action_does_not_overlap_terminal_outcomes() -> None:
    insights = summarize(
        [
            {
                "number": 9,
                "family_id": "OGE09-F001",
                "outcome": "solved",
                "solution_viewed": True,
                "attempt_records": [{"attempt_no": 1, "is_correct": True, "used_hint": False}],
            },
            {
                "number": 12,
                "family_id": "OGE12-F001",
                "outcome": "failed",
                "solution_viewed": True,
                "attempt_records": [
                    {"attempt_no": 1, "is_correct": False},
                    {"attempt_no": 2, "is_correct": False},
                ],
            },
        ]
    )

    assert insights["total"]["solutions_viewed"] == 2
    segments = _exclusive_segments(insights["total"])
    assert sum(value for _, value, _ in segments) == insights["total"]["completed"] == 2
    assert dict((label, value) for label, value, _ in segments)["Открыт разбор"] == 0


def test_history_status_keeps_success_green_after_an_error() -> None:
    solved_after_error = {
        "outcome": "solved",
        "has_error": True,
        "attempt_records": [
            {"attempt_no": 1, "is_correct": False, "used_hint": False},
            {"attempt_no": 2, "is_correct": True, "used_hint": False},
        ],
    }
    failed = {"outcome": "failed", "attempt_records": []}
    solution_after_error = {"outcome": "solution_viewed", "has_error": True}

    assert _status(solved_after_error) == ("Верно со 2-й попытки", "#42AD7B", "Была ошибка")
    assert _status(failed)[0] == "Две ошибки"
    assert _status(failed)[1] == "#D96973"
    assert _status(solution_after_error)[0] == "Открыт разбор"
    assert _status(solution_after_error)[2] == "Была ошибка"
    assert _status({"outcome": "active"})[0] == "В процессе"
    unknown_hint = {
        "outcome": "solved",
        "has_error": True,
        "attempt_records": [
            {"attempt_no": 1, "is_correct": False, "used_hint": None},
            {"attempt_no": 2, "is_correct": True, "used_hint": None},
        ],
    }
    assert _status(unknown_hint) == (
        "Верно · попытка 2",
        "#42AD7B",
        "Подсказка неизвестна",
    )


def test_progress_keyboard_has_real_navigation_and_bounded_callbacks() -> None:
    markup = prepare_navigation_markup(progress_image_keyboard("numbers", 0, 14))
    revision = navigation_revision(markup)

    assert revision is not None
    assert [[button.text for button in row] for row in markup.inline_keyboard[:3]] == [
        ["📊 Обзор", "📚 По номерам"],
        ["🕘 История", "⚠️ Ошибки"],
        ["↩ В меню"],
    ]
    callbacks = [
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
        if button.callback_data
    ]
    assert any(button.text == "Дальше →" for row in markup.inline_keyboard for button in row)
    assert all(len(callback.encode("utf-8")) <= 64 for callback in callbacks)

    for section, offset, total in (
        ("summary", 0, 0),
        ("numbers", 7, 14),
        ("history", 4, 9),
        ("errors", 0, 9),
    ):
        revised = prepare_navigation_markup(progress_image_keyboard(section, offset, total))
        revision = navigation_revision(revised)
        assert revision is not None
        assert all(
            len(button.callback_data.encode("utf-8")) <= 64
            for row in revised.inline_keyboard
            for button in row
            if button.callback_data
        )

    previous_page = progress_image_keyboard("numbers", 7, 14)
    previous_labels = [button.text for row in previous_page.inline_keyboard for button in row]
    assert "← Назад" in previous_labels
    assert "Дальше →" in previous_labels
    assert any(
        button.callback_data == "progress:numbers:14"
        for row in previous_page.inline_keyboard for button in row
    )
    last_page = progress_image_keyboard("numbers", 14, 19)
    assert "Дальше →" not in [button.text for row in last_page.inline_keyboard for button in row]
    assert any(
        button.callback_data == "progress:numbers:7"
        for row in last_page.inline_keyboard for button in row
    )

    history = progress_image_keyboard("history", 0, PAGE_SIZE + 1)
    assert any(button.text == "Дальше →" for row in history.inline_keyboard for button in row)


def test_all_dashboard_screens_render_as_reasonable_pngs() -> None:
    insights = demo_insights()
    error_page = dict(insights)
    error_page["errors"] = [
        insights["history"][14],
        insights["history"][24],
        insights["history"][67],
        insights["history"][15],
    ]
    error_page["page_total"] = len(insights["errors"])
    long_history = dict(insights)
    long_history["history"] = [
        {
            **insights["history"][14],
            "family_name": "Очень длинное название практического задания для проверки переноса",
            "number": 11,
            "family_id": "OGE11-F001",
        }
    ] * 4
    empty = {
        "total": {key: 0 for key in insights["total"]},
        "numbers": {
            number: {key: 0 for key in values} for number, values in insights["numbers"].items()
        },
        "history": [],
        "errors": [],
        "families": [],
    }
    cases = [
        (insights, "summary"),
        (insights, "numbers:0"),
        (insights, "numbers:7"),
        (long_history, "history:0"),
        (error_page, "errors:0"),
        (empty, "summary"),
    ]
    large_values = dict(insights)
    large_values["total"] = {
        **insights["total"],
        "completed": 99_999_999,
        "issued": 1_234_567_890,
        "correct": 99_999_999,
        "unassisted_correct": 99_999_999,
        "assisted_correct": 0,
        "unknown_assistance": 0,
        "failed": 0,
        "skipped": 0,
        "solutions_viewed": 0,
    }
    cases.append((large_values, "summary"))

    for data, page in cases:
        png = render_progress_image(data, page)
        with Image.open(io.BytesIO(png)) as image:
            assert image.format == "PNG"
            assert image.width == 1200
            assert image.height <= 2000
            for screen_width in (320, 375, 430):
                assert round(image.height * screen_width / image.width) <= 550
        assert len(png) < 10 * 1024 * 1024


def test_history_image_height_tracks_rows_and_empty_state_is_compact() -> None:
    insights = demo_insights()
    one_row = dict(insights)
    one_row["history"] = insights["history"][:1]
    one_row["page_total"] = 1
    four_rows = dict(insights)
    four_rows["history"] = insights["history"][:4]
    four_rows["page_total"] = 4
    empty = dict(insights)
    empty["history"] = []
    empty["page_total"] = 0

    heights = []
    for data in (empty, one_row, four_rows):
        png = render_progress_image(data, "history:0")
        with Image.open(io.BytesIO(png)) as image:
            heights.append(image.height)

    assert heights[1] < heights[2]
    assert heights[2] < 900
    assert heights[0] < 400
