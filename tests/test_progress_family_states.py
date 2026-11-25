from datetime import UTC, datetime

from app.adaptive.engine import Stage, State
from app.bot.progress import _include_family_states, progress_keyboard, render_progress
from app.config import get_settings
from app.persistence.training_insights import summarize


async def test_number_detail_uses_global_streak_and_keeps_unseen_types(monkeypatch):
    from app.bot.adaptive import catalog

    first, second, *_ = [f for f, n in catalog().items() if n == 9]
    state = State(stage=Stage.PRACTICE, practice=2, independent_count=4)

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
        assert "Закрепляется, 2/3" in body and "Нет данных" not in body
        assert "Нет данных" in render_progress(insights, "family:9:0")
        assert "Новых вариантов самостоятельно: 4" in body
        assert first not in body and second not in body
        markup = progress_keyboard("number:9:0", number=9, family_total=2, insights=insights)
        actions = [b.callback_data for row in markup.inline_keyboard for b in row]
        assert f"train:family:{first}" in actions and "train:number:9" in actions
        assert "progress:family:9:0" in actions
    finally:
        get_settings.cache_clear()
