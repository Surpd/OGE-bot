"""Bounded, in-memory Telegram profile lookup for the private admin desk."""

import asyncio
import re
import unicodedata
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from time import monotonic
from typing import Any
from uuid import UUID

from aiogram.exceptions import TelegramRetryAfter
from aiogram.types import ChatFullInfo

from app.admin.queries import PAGE_SIZE
from app.admin.repository import AdminRepository

PROFILE_TTL = 300
PROFILE_FAILURE_TTL = 30
PROFILE_CACHE_LIMIT = 256
PROFILE_CALL_TIMEOUT = 1.5
PROFILE_REPORT_TIMEOUT = 5
ProfileLookup = Callable[[int], Awaitable[ChatFullInfo]]


def _plain_name(value: object, limit: int = 120) -> str:
    """Keep Telegram names on one line; HTML escaping belongs to presentation."""
    if not isinstance(value, str):
        return ""
    # Remove control/bidi characters while preserving emoji joiners and variation selectors.
    cleaned = "".join(
        " " if char.isspace() else char
        for char in value
        if char.isspace()
        or unicodedata.category(char) not in {"Cc", "Cs", "Cf"}
        or char in "\u200c\u200d"
    )
    return " ".join(cleaned.split())[:limit]


@dataclass(frozen=True)
class LearnerProfile:
    display_name: str | None = None
    username: str | None = None

    @classmethod
    def from_chat(cls, chat: ChatFullInfo) -> "LearnerProfile":
        name = _plain_name(" ".join(filter(None, (chat.first_name, chat.last_name))))
        username = chat.username
        # Do not turn unexpected provider text into a link or a Telegram handle.
        if not isinstance(username, str) or not re.fullmatch(r"[A-Za-z0-9_]{1,32}", username):
            username = None
        return cls(name or None, username)

    def fields(self) -> dict[str, str | None]:
        return {"display_name": self.display_name, "username": self.username}


class LearnerProfiles:
    """Only a read-only getChat callable is shared with the companion process."""

    def __init__(self, repository: AdminRepository, lookup: ProfileLookup) -> None:
        self._repository = repository
        self._lookup = lookup
        self._cache: OrderedDict[tuple[UUID, tuple[str, ...]], tuple[float, LearnerProfile]] = (
            OrderedDict()
        )
        self._slot = asyncio.Semaphore(2)
        self._cooldown_until = 0.0

    def clear(self) -> None:
        self._cache.clear()

    async def resolve(
        self,
        user_ids: list[UUID],
        excluded_keys: tuple[str, ...],
        *,
        refresh: bool = False,
    ) -> dict[UUID, LearnerProfile]:
        """Enrich only the displayed page, never crawl the account table."""
        identities = list(dict.fromkeys(user_ids))
        if len(identities) > PAGE_SIZE:
            raise ValueError("Too many learner profiles")
        profiles: dict[UUID, LearnerProfile] = {}
        missing: list[UUID] = []
        now = monotonic()
        for identity in identities:
            cache_key = identity, excluded_keys
            cached = self._cache.get(cache_key)
            if not refresh and cached and cached[0] > now:
                profiles[identity] = cached[1]
                self._cache.move_to_end(cache_key)
            else:
                self._cache.pop(cache_key, None)
                missing.append(identity)
        if not missing:
            return profiles
        try:
            async with asyncio.timeout(PROFILE_REPORT_TIMEOUT):
                telegram_ids = await self._repository.telegram_user_ids(missing, excluded_keys)
                # Never retain Telegram IDs in either report data or the profile cache.
                await asyncio.gather(
                    *(
                        self._resolve_one(identity, telegram_ids[identity], profiles, excluded_keys)
                        for identity in missing
                        if identity in telegram_ids
                    )
                )
        except Exception:
            # Profiles are optional: a network/database error must not discard the report.
            # Do not log exception text, user IDs or provider payloads.
            pass
        return profiles

    async def _resolve_one(
        self,
        identity: UUID,
        telegram_id: int,
        profiles: dict[UUID, LearnerProfile],
        excluded_keys: tuple[str, ...],
    ) -> None:
        profile = LearnerProfile()
        ttl = PROFILE_FAILURE_TTL
        try:
            async with self._slot, asyncio.timeout(PROFILE_CALL_TIMEOUT):
                if monotonic() < self._cooldown_until:
                    return
                chat = await self._lookup(telegram_id)
            if chat.id == telegram_id and chat.type == "private":
                profile = LearnerProfile.from_chat(chat)
                ttl = PROFILE_TTL
        except TelegramRetryAfter as exc:
            ttl = max(PROFILE_FAILURE_TTL, exc.retry_after)
            self._cooldown_until = max(self._cooldown_until, monotonic() + ttl)
        except Exception:
            pass
        profiles[identity] = profile
        cache_key = identity, excluded_keys
        self._cache[cache_key] = monotonic() + ttl, profile
        self._cache.move_to_end(cache_key)
        if len(self._cache) > PROFILE_CACHE_LIMIT:
            self._cache.popitem(last=False)

    async def enrich(
        self,
        view: str,
        data: dict[str, Any],
        key: str,
        excluded_keys: tuple[str, ...],
        *,
        refresh: bool = False,
    ) -> dict[str, Any]:
        """Attach public display fields; UUIDs remain the stable internal key."""
        if view == "learners":
            rows = data.get("rows", [])
            identities = [UUID(str(row["user_id"])) for row in rows]
        elif view == "learner" and data.get("found"):
            identities = [UUID(key)]
        else:
            return data
        profiles = await self.resolve(identities, excluded_keys, refresh=refresh)

        def fields(identity: UUID) -> Mapping[str, str | None]:
            return profiles.get(identity, LearnerProfile()).fields()

        if view == "learner":
            return {**data, **fields(identities[0])}
        return {
            **data,
            "rows": [
                {**row, **fields(identity)} for row, identity in zip(rows, identities, strict=True)
            ],
        }
