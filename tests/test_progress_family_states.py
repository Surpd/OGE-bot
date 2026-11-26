from datetime import UTC, datetime

from app.adaptive.engine import Stage, State
from app.bot.progress import _include_family_states, progress_keyboard, render_progress
from app.config import get_settings
from app.persistence.training_insights import summarize


async def test_number_detail_uses_global_streak_and_keeps_unseen_types(monkeypatch):
    from app.bot.adaptive import catalog

    first, second, *_ = [f for f, n in catalog().items() if n == 9]
    state = State(stage=Stage.PRACTICE, practice=2, independent_count=4, reviewed_at=1737417600)

    async def overview(repository, user):
        return [(9, first, state, datetime.now(UTC))]

    monkeypatch.setenv("OGE_ADAPTIVE_ENABLED", "true")
    monkeypatch.setattr("app.adaptive.store.overview", overview)
    monkeypatch.setattr("app.bot.adaptive.catalog", lambda: {first: 9, second: 9})
    get_settings.cache_clear()
    try:
        insights = summarize([])
        await _include_family_states(insights, object(), 1, 9)
        body = render_progress(insights, "number:9:0")
        assert "Закрепляется, 2/3" in body and "Нет данных" in body
        assert "Новых вариантов самостоятельно: 4" in body
        assert "повторено самостоятельно" not in body
        assert "повторено самостоятельно" not in render_progress(insights, "family:9:0")
        assert first not in body and second not in body
        markup = progress_keyboard("number:9:0", number=9, family_total=2, insights=insights)
        actions = [b.callback_data for row in markup.inline_keyboard for b in row]
        assert f"train:family:{first}" in actions and "train:number:9" in actions
        assert "progress:family:9:0" not in actions
        assert "progress:numhist:9:0" in actions
        catalog_markup = progress_keyboard("family:9:1", number=9, insights=insights)
        assert [
            (b.text, b.callback_data)
            for row in catalog_markup.inline_keyboard for b in row
            if b.callback_data.startswith("train:family:")
        ] == [("Тренировать тип 2", f"train:family:{second}")]
        assert "2. " in render_progress(insights, "family:9:1")
    finally:
        get_settings.cache_clear()


def test_number_prioritizes_difficulties_and_solved_tasks_and_hides_large_catalog():
    insights = summarize([])
    data = [
        ("Не проверено", "unchecked", 0, 0),
        ("Подтверждено", "confirmed", 8, 9),
        ("В закреплении", "practice", 6, 7),
        ("Трудно, меньше решено", "gap", 1, 10),
        ("Вновь трудно, больше решено", "reopened", 4, 5),
        ("Нужна проверка", "check", 3, 4),
        ("Ещё не проверено", "unchecked", 0, 0),
    ]
    insights["families"] = [
        {
            "number": 9, "name": name, "family_id": f"f{i}", "diagnosis_key": stage,
            "diagnosis": stage, "correct": correct, "answered_tasks": answered,
        }
        for i, (name, stage, correct, answered) in enumerate(data)
    ]
    body = render_progress(insights, "number:9")
    assert [
        line.partition(" · ")[0] for line in body.splitlines() if line[:1].isdigit()
    ] == [
        "1. Вновь трудно, больше решено", "2. Трудно, меньше решено", "3. Нужна проверка",
        "4. В закреплении", "5. Подтверждено",
    ]
    assert all("Нет данных" not in line for line in body.splitlines())
    assert "Ещё не проверено" in render_progress(insights, "family:9:0")
    assert "Не проверено" in render_progress(insights, "family:9:6")
    keyboard = progress_keyboard("number:9", number=9, family_total=7, insights=insights)
    actions = [button.callback_data for row in keyboard.inline_keyboard for button in row]
    assert "progress:family:9:0" in actions
