from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import SecretStr

from app.config import Settings
from scripts import companion_polling


@pytest.mark.parametrize("url", [
    "postgresql://localhost/oge_companion_qa",
    "postgresql://remote.example/oge_companion_qa",
    "postgresql://127.0.0.1/postgres",
    "postgresql://127.0.0.1/oge_companion_qa?host=remote.example",
])
def test_companion_polling_rejects_non_disposable_targets(url):
    with pytest.raises(ValueError):
        companion_polling.validate_target(url, 100001, 100002)


async def test_companion_polling_never_uses_primary_or_changes_webhook(monkeypatch):
    primary, companion = 100001, 100002
    url = "postgresql://127.0.0.1/oge_companion_qa"
    settings = Settings.model_construct(
        telegram_test_bot_token=SecretStr("synthetic"),
        telegram_test_owner_ids="42",
    )
    with pytest.raises(ValueError):
        companion_polling.validate_target(url, primary, primary)
    bot = Mock(
        id=primary, session=Mock(close=AsyncMock()),
        get_me=AsyncMock(return_value=Mock(id=companion)),
        get_webhook_info=AsyncMock(return_value=Mock(url="https://example.invalid")),
    )
    prepare = AsyncMock()
    monkeypatch.setattr(companion_polling, "Bot", lambda _: bot)
    monkeypatch.setattr(companion_polling, "open_storage", prepare)
    with pytest.raises(ValueError):
        await companion_polling.poll(settings, url, primary, companion, "a" * 40)
    bot.get_me.assert_not_awaited()
    bot.id = companion
    with pytest.raises(ValueError):
        await companion_polling.poll(settings, url, primary, companion, "a" * 40)
    bot.get_webhook_info.assert_awaited_once()
    bot.delete_webhook.assert_not_called()
    bot.set_webhook.assert_not_called()
    prepare.assert_not_awaited()
