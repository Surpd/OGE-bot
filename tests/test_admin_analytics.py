from datetime import UTC, date, datetime
from decimal import Decimal

from app.admin.queries import cost_report
from app.admin.service import MOSCOW, ReportWindow, make_service
from app.config import Settings


def test_moscow_report_windows_and_mature_retention() -> None:
    # UTC is still Nov 27 while today has already started in Moscow.
    now = datetime(2026, 11, 27, 22, 15, tzinfo=UTC)
    today = ReportWindow.at("today", now)
    assert today.start == datetime(2026, 11, 28, tzinfo=MOSCOW)
    assert today.end == now
    week = ReportWindow.at("7", now)
    assert week.start == datetime(2026, 11, 21, tzinfo=MOSCOW)
    assert week.end == today.start
    assert [bound.date() for bound in week.mature_cohorts()] == [
        date(2026, 11, 8), date(2026, 11, 15)
    ]
    assert (ReportWindow.at("28", now).end - ReportWindow.at("28", now).start).days == 28


async def test_admin_never_falls_back_to_the_primary_connection() -> None:
    service = make_service(
        Settings(database_url="postgresql://invalid.example/never-open", _env_file=None),
        frozenset({1}), 2,
    )
    report = await service.load("home", "7")
    assert service.repository is None
    assert report.unavailable == "unconfigured" and report.data == {}


def test_cost_with_only_unknown_fees_preserves_unknown() -> None:
    report = cost_report(
        dict(written_cost=None, graded=2, unknown_written=3, spent=Decimal(4), held=Decimal(2)),
        Decimal(5),
    )
    assert report["known_cost_per_result"] is None
    assert report["available"] == Decimal(0)
