"""Window definitions, bounded report caching and read-only data access for bop Admin."""

import asyncio
import hashlib
import logging
import re
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from time import monotonic
from typing import Any
from zoneinfo import ZoneInfo

import asyncpg

from app.admin.queries import DAYS, MODES, PAGE_SIZE, RETENTION, TYPE_ORDERS, ReportQueries
from app.admin.repository import AdminRepository, AdminUnavailable
from app.config import Settings

MOSCOW = ZoneInfo("Europe/Moscow")
LOGGER = logging.getLogger("oge_trainer")
CACHE_SECONDS = 60
CACHE_LIMIT = 128
PERIODS = {"today": 1, "7": 7, "28": 28}


@dataclass(frozen=True)
class ReportWindow:
    period: str
    start: datetime
    end: datetime

    @classmethod
    def at(cls, period: str, now: datetime) -> "ReportWindow":
        now = now.astimezone(MOSCOW)
        midnight = datetime.combine(now.date(), time.min, MOSCOW)
        if period == "today":
            return cls(period, midnight, now)
        return cls(period, midnight - timedelta(days=PERIODS[period]), midnight)

    def mature_cohorts(self) -> tuple[datetime, datetime]:
        # D0+13 must be wholly observed. Even Today starts at a completed midnight.
        observed_through = datetime.combine(self.end.date(), time.min, MOSCOW)
        cohort_end = observed_through - timedelta(days=13)
        return cohort_end - timedelta(days=PERIODS[self.period]), cohort_end


@dataclass(frozen=True)
class AdminReport:
    window: ReportWindow
    updated_at: datetime
    data: dict[str, Any]
    unavailable: str | None = None


class AdminService:
    def __init__(
        self,
        repository: AdminRepository | None,
        *,
        excluded: frozenset[int],
        primary_id: int,
        environment: str,
        budget: Decimal,
        misconfigured: bool = False,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.repository = repository
        self.primary_id = primary_id
        self.environment = environment
        self.budget = budget
        self._misconfigured = misconfigured
        self._now = now
        self._excluded_keys = tuple(
            hashlib.md5(str(identity).encode(), usedforsecurity=False).hexdigest()
            for identity in sorted(excluded)
        )
        self._cache: OrderedDict[tuple[object, ...], tuple[float, AdminReport]] = OrderedDict()

    async def load(
        self,
        view: str,
        period: str,
        *,
        number: int = 0,
        key: str = "",
        page: int = 0,
        sort: str = "sample",
        refresh: bool = False,
    ) -> AdminReport:
        if (
            period not in PERIODS or not 0 <= page <= 500
            or not 0 <= number <= 25 or sort not in TYPE_ORDERS or len(key) > 160
        ):
            raise ValueError("Invalid admin filters")
        now = self._now().astimezone(MOSCOW)
        window = ReportWindow.at(period, now)
        if self._misconfigured or self.repository is None:
            return AdminReport(
                window, now, {}, "unavailable" if self._misconfigured else "unconfigured"
            )
        cache_key = (
            self.environment, self.primary_id, self._excluded_keys, MOSCOW.key,
            window.period, window.start, window.end.date(), view, number, key, page, sort,
        )
        cached = self._cache.get(cache_key)
        if not refresh and cached and monotonic() - cached[0] < CACHE_SECONDS:
            self._cache.move_to_end(cache_key)
            return cached[1]
        self._cache.pop(cache_key, None)
        try:
            async with asyncio.timeout(10), self.repository.read() as conn:
                args = (window.start, window.end, self._excluded_keys)
                query = ReportQueries(conn, args)
                data = await query.load(
                    view, number, key, sort, page * PAGE_SIZE,
                    primary_id=self.primary_id, budget=self.budget,
                )
                if view == "usage":
                    first, last = window.mature_cohorts()
                    retention = await ReportQueries(
                        conn, (first, last, self._excluded_keys)
                    ).one(RETENTION)
                    data.update(
                        days=[dict(row) for row in await query.many(DAYS)],
                        modes=[dict(row) for row in await query.many(MODES)],
                        retention={
                            **retention,
                            "first_day": first.date(),
                            "last_day": (last - timedelta(days=1)).date(),
                        },
                    )
        except (TimeoutError, asyncpg.QueryCanceledError) as exc:
            LOGGER.warning("admin_report_timeout type=%s", type(exc).__name__)
            return AdminReport(window, now, {}, "timeout")
        except (AdminUnavailable, asyncpg.PostgresError, asyncpg.InterfaceError, OSError) as exc:
            LOGGER.warning("admin_report_unavailable type=%s", type(exc).__name__)
            return AdminReport(window, now, {}, "unavailable")

        report = AdminReport(window, now, data)
        self._cache[cache_key] = monotonic(), report
        if len(self._cache) > CACHE_LIMIT:
            self._cache.popitem(last=False)
        return report

    async def close(self) -> None:
        self._cache.clear()
        if self.repository is not None:
            await self.repository.close()


def make_service(settings: Settings, owner_ids: frozenset[int], primary_id: int) -> AdminService:
    raw_exclusions = settings.oge_admin_excluded_user_ids.strip()
    entries = [item.strip() for item in raw_exclusions.split(",")] if raw_exclusions else []
    invalid = len(entries) > 100 or any(not re.fullmatch(r"[1-9][0-9]{0,14}", i) for i in entries)
    excluded = owner_ids if invalid else owner_ids.union(int(i) for i in entries)
    dsn = settings.oge_admin_database_url
    repository = (
        AdminRepository(dsn, settings.oge_admin_schema)
        if dsn is not None and dsn.get_secret_value().strip()
        else None
    )
    return AdminService(
        repository,
        excluded=excluded,
        primary_id=primary_id,
        environment=settings.app_env,
        budget=settings.oge_grading_monthly_budget_usd,
        misconfigured=invalid,
    )
