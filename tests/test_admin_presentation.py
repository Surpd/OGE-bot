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
    assert "Ошибки проверок: <b>2</b>" in view.caption
    assert len(view.caption) < 200
    assert "Известные расходы на ИИ  <b>$0,0184</b>" in view.text
    assert any(
        button.callback_data == "adm:check:tools"
        for row in view.markup.inline_keyboard
        for button in row
    )
    changed = render_admin_view("home", {**data, "active": 89}, window=window)
    assert changed.photo and changed.photo != view.photo


def test_28_day_activity_moves_exact_counts_to_explicit_details():
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
    data = {"active": 37, "days": days, "modes": modes}
    view = render_admin_view("usage", data, period="28", companion_status="ready")
    assert view.photo and view.caption is None
    assert any(button.text == "Подробнее" for row in view.markup.inline_keyboard for button in row)
    details = render_admin_view("usage", data, period="28", expanded=True)
    assert details.photo is None
    assert "01.11–07.11  10 / 11 / 12 / 13 / 14 / 15 / 16" in details.text
    assert "22.11–28.11  31 / 32 / 33 / 34 / 35 / 36 / 37" in details.text
    assert "<b>Персональная пятёрка</b>" in details.text
    assert "<b>Письменная работа</b>" in details.text
    assert any(button.text == "Кратко" for row in details.markup.inline_keyboard for button in row)


def test_photo_empty_state_and_text_unavailability_remain_distinct():
    empty = render_admin_view("written", {"issued": 2, "submitted": 0}, number=21)
    unavailable = render_admin_view("written", {"unavailable": "timeout"}, number=21)
    assert empty.photo and empty.caption is None
    assert "работы на проверку не отправляли" in empty.text
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


def test_learner_profiles_replace_visible_ids_without_becoming_html():
    identity = "17a8f719-f34a-4aa3-8e94-bd7f4d77eb01"
    profile = {"user_id": identity, "display_name": "Демо <ученик> & друг", "username": "demo_user"}
    listing = render_admin_view("learners", {"rows": [profile]}, page=0)
    assert identity not in listing.text and "Последнее занятие" not in listing.text
    button = listing.markup.inline_keyboard[0][0]
    assert button.text == "@demo_user"
    assert button.callback_data.endswith(f"learner:{identity}")
    card_data = {**profile, "found": True, "days": 1, "answered": 2, "solved": 1, "numbers": [8]}
    card = render_admin_view("learner", card_data, learner_id=identity)
    assert card.photo and card.caption is None
    details = render_admin_view("learner", card_data, learner_id=identity, expanded=True)
    assert "Демо &lt;ученик&gt; &amp; друг" in details.text
    assert identity not in details.text
    unnamed = render_admin_view("learners", {"rows": [{"user_id": identity}]}, page=1)
    assert unnamed.markup.inline_keyboard[0][0].text == "Ученик без имени · 7"
    long_name = render_admin_view("learner", {**card_data, "display_name": "Ж" * 120})
    assert long_name.photo and long_name.caption is None


def test_empty_and_populated_cost_cards_keep_only_nonzero_caveats():
    data = {"known_cost": Decimal("0.0191"), "budget": 5, "spent": Decimal("0.0191"), "held": 0}
    view = render_admin_view("cost", data)
    assert view.photo and view.caption is None
    incomplete = render_admin_view("cost", {**data, "unknown_cost": 3})
    assert incomplete.photo and "<b>3</b>" in incomplete.caption
    assert "Диагностика" not in incomplete.caption
    detailed = render_admin_view("cost", data, expanded=True)
    assert detailed.photo is None and "Диагностика" in detailed.text


def test_compact_system_keeps_operation_errors_visible_without_raw_release():
    data = {
        "errors": 0,
        "operations": [{"status": "failed", "count": 2}, {"status": "ok", "count": 90}],
    }
    view = render_admin_view("system", data, companion_status="ready", release="a" * 40)
    assert "Ошибки операций  <b>2</b>" in view.text
    assert "a" * 40 not in view.text
    assert "<b>90</b>" not in view.text
