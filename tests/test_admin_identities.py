import asyncio
import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.methods import GetChat

from app.admin.identities import LearnerProfile, LearnerProfiles


def profile(user_id=101, **fields):
    return SimpleNamespace(
        id=user_id,
        type="private",
        first_name=fields.get("first_name", "Synthetic learner"),
        last_name=fields.get("last_name"),
        username=fields.get("username", "SyntheticLearner"),
    )


async def test_profiles_are_limited_to_visible_accounts_and_refresh_replaces_names():
    identities = [uuid4(), uuid4()]
    excluded = (hashlib.md5(b"42").hexdigest(),)
    repository = SimpleNamespace(telegram_user_ids=AsyncMock(return_value={identities[0]: 101}))
    lookup = AsyncMock(return_value=profile())
    profiles = LearnerProfiles(repository, lookup)
    data = {"rows": [{"user_id": str(identity)} for identity in identities], "more": True}

    result = await profiles.enrich("learners", data, "", excluded)
    repository.telegram_user_ids.assert_awaited_once_with(identities, excluded)
    lookup.assert_awaited_once_with(101)
    assert result["rows"][0]["display_name"] == "Synthetic learner"
    assert result["rows"][0]["username"] == "SyntheticLearner"
    assert result["rows"][1]["display_name"] is None
    assert "telegram_user_id" not in str(result)
    assert data["rows"][0] == {"user_id": str(identities[0])}

    lookup.return_value = profile(first_name="Changed name", username=None)
    cached = await profiles.enrich("learner", {"found": True}, str(identities[0]), excluded)
    assert cached["username"] == "SyntheticLearner"
    assert lookup.await_count == 1
    refreshed = await profiles.enrich(
        "learner", {"found": True}, str(identities[0]), excluded, refresh=True
    )
    assert refreshed["display_name"] == "Changed name" and refreshed["username"] is None
    assert lookup.await_count == 2

    await profiles.enrich("home", {}, "", excluded)
    await profiles.enrich("learner", {"found": False}, str(identities[0]), excluded)
    assert lookup.await_count == 2


async def test_profile_errors_and_timeouts_leave_report_data_available(monkeypatch):
    identities = [uuid4(), uuid4()]
    repository = SimpleNamespace(
        telegram_user_ids=AsyncMock(return_value=dict(zip(identities, (101, 102), strict=True)))
    )
    stopped = asyncio.Event()

    async def lookup(telegram_id):
        if telegram_id == 101:
            raise TelegramBadRequest(
                method=GetChat(chat_id=101), message="private provider details"
            )
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    monkeypatch.setattr("app.admin.identities.PROFILE_CALL_TIMEOUT", 0.01)
    profiles = LearnerProfiles(repository, lookup)
    data = {
        "rows": [{"user_id": identity, "last_activity": "unchanged"} for identity in identities]
    }
    result = await profiles.enrich("learners", data, "", ())
    assert stopped.is_set()
    assert [row["last_activity"] for row in result["rows"]] == ["unchanged", "unchanged"]
    assert all(row["display_name"] is None and row["username"] is None for row in result["rows"])

    repository.telegram_user_ids.side_effect = RuntimeError("database unavailable")
    failed = await profiles.enrich("learners", data, "", (), refresh=True)
    assert len(failed["rows"]) == 2
    assert all(row["display_name"] is None for row in failed["rows"])


async def test_profile_lookup_respects_cooldown_cache_limit_and_owner_filter(monkeypatch):
    identity = uuid4()
    repository = SimpleNamespace(telegram_user_ids=AsyncMock(return_value={identity: 101}))
    lookup = AsyncMock(
        side_effect=TelegramRetryAfter(
            method=GetChat(chat_id=101), message="rate limit", retry_after=90
        )
    )
    profiles = LearnerProfiles(repository, lookup)
    await profiles.resolve([identity], ())
    await profiles.resolve([identity], (), refresh=True)
    assert lookup.await_count == 1

    profiles = LearnerProfiles(repository, AsyncMock(return_value=profile()))
    await profiles.resolve([identity], ())
    # A changed exclusion set may not reuse an identity cached for the prior owner set.
    repository.telegram_user_ids.return_value = {}
    excluded = (hashlib.md5(b"101").hexdigest(),)
    assert await profiles.resolve([identity], excluded) == {}

    monkeypatch.setattr("app.admin.identities.PROFILE_CACHE_LIMIT", 1)
    newer = uuid4()
    repository.telegram_user_ids.return_value = {newer: 101}
    await profiles.resolve([newer], ())
    assert len(profiles._cache) == 1
    assert list(profiles._cache)[0][0] == newer
    with pytest.raises(ValueError, match="Too many"):
        await profiles.resolve([uuid4() for _ in range(7)], ())
    profiles.clear()
    assert not profiles._cache


def test_profile_names_are_single_line_bounded_and_username_is_optional():
    rendered = LearnerProfile.from_chat(
        profile(
            first_name="  <b>Synthetic\nname</b>\u202e\x00 👩\u200d💻 ",
            last_name="x" * 200,
            username="bad\nname",
        )
    )
    assert rendered.display_name.startswith("<b>Synthetic name</b> 👩\u200d💻 ")
    assert len(rendered.display_name) == 120
    assert not any(mark in rendered.display_name for mark in ("\n", "\u202e", "\x00"))
    assert rendered.username is None
