from datetime import date, datetime, timedelta
from decimal import Decimal
from io import BytesIO
from zoneinfo import ZoneInfo

from PIL import Image

from app.admin.presentation import render_admin_view
from app.admin.service import ReportWindow


def test_admin_overview_renders_a_data_driven_png_and_keeps_actual_navigation():
    now = datetime(2026, 11, 28, 12, tzinfo=ZoneInfo("Europe/Moscow"))
    window = ReportWindow.at("7", now)
    data = {"active": 34, "answered": 428, "known_cost": Decimal("0.0184"), "errors": 2}
    view = render_admin_view("home", data, window=window, updated_at=now, revision="check")
    assert view.photo and view.caption
    with Image.open(BytesIO(view.photo)) as image:
        assert image.format == "PNG"
        assert image.width == 1200 and image.height < 1000
        image.verify()
    assert "Ошибки письменных проверок  <b>2</b>" in view.caption
    assert "Известные расходы на ИИ  <b>$0,0184</b>" in view.text
    assert any(
        button.callback_data == "adm:check:tools"
        for row in view.markup.inline_keyboard
        for button in row
    )
    changed = render_admin_view("home", {**data, "active": 89}, window=window)
    assert changed.photo and changed.photo != view.photo


def test_28_day_activity_keeps_exact_counts_in_a_photo_caption():
    beginning = date(2026, 11, 1)
    days = [{"day": beginning + timedelta(days=i), "active": i + 10} for i in range(28)]
    modes = [
        {"mode": mode, "users": 12, "answered": 34, "submitted": 0}
        for mode in (
            "personal",
            "mixed",
            "number",
            "family",
            "full_part",
            "scenario_single",
            "scenario_full",
            "replay",
            "unknown",
        )
    ]
    modes.append({"mode": "written", "users": 5, "answered": 0, "submitted": 10})
    view = render_admin_view("usage", {"active": 37, "days": days, "modes": modes}, period="28")
    assert view.photo and view.caption
    assert "01.11–07.11  10 / 11 / 12 / 13 / 14 / 15 / 16" in view.caption
    assert "22.11–28.11  31 / 32 / 33 / 34 / 35 / 36 / 37" in view.caption
    assert "<b>Персональная пятёрка</b>" in view.caption
    assert "<b>Письменная работа</b>" in view.caption


def test_photo_empty_state_and_text_unavailability_remain_distinct():
    empty = render_admin_view("written", {"issued": 2, "submitted": 0}, number=21)
    unavailable = render_admin_view("written", {"unavailable": "timeout"}, number=21)
    assert empty.photo and empty.caption and "работы на проверку не отправляли" in empty.caption
    assert not unavailable.photo and not unavailable.caption
    assert "<b>Данные недоступны</b>" in unavailable.text
    assert "Заданий выдано" not in unavailable.text


def test_text_details_escape_historical_identifiers_and_keep_selected_filter():
    view = render_admin_view(
        "types",
        {"rows": [{"family_id": "old <type> & id", "answered": 4}], "more": True},
        number=7,
        page=1,
        sort="help",
    )
    assert not view.photo
    assert "<b>old &lt;type&gt; &amp; id</b>" in view.text
    assert "Страница 2" in view.text
    buttons = [button for row in view.markup.inline_keyboard for button in row]
    assert any(b.callback_data == "adm:preview:types:7:2:help" for b in buttons)
    assert any(b.text == "✓ Подсказки" and b.style == "success" for b in buttons)


def test_render_failure_preserves_full_text_and_keyboard(monkeypatch):
    def fail(*args, **kwargs):
        raise ValueError("synthetic renderer failure")

    monkeypatch.setattr("app.admin.presentation.render_summary", fail)
    original = render_admin_view("home", {"active": 4})
    assert not original.photo
    assert "Занимались  <b>4</b>" in original.text
    assert any(
        button.callback_data == "adm:preview:refresh"
        for row in original.markup.inline_keyboard
        for button in row
    )
