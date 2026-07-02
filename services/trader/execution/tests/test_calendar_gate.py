"""Tests for the economic-calendar entry blackout gate."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from services.trader.execution.calendar_gate import EconCalendarGate


class _StubCalendar:
    """Minimal stub matching the ReleaseCalendar surface the gate uses.

    Returns a single known release date for every series so a test can pin
    the blackout window without touching FRED.
    """

    def __init__(self, release_date: date) -> None:
        self._release_date = release_date
        self.calls: list[tuple[str, date]] = []

    def as_of_release_date(self, series_id: str, reference_date: date) -> date:
        self.calls.append((series_id, reference_date))
        return self._release_date


class _RaisingCalendar:
    """Calendar whose lookup blows up — the gate must swallow it."""

    def as_of_release_date(self, series_id: str, reference_date: date) -> date:
        raise RuntimeError("FRED unreachable")


def test_blackout_true_on_release_day() -> None:
    release = date(2026, 7, 15)
    gate = EconCalendarGate(release_calendar=_StubCalendar(release))
    now = pd.Timestamp("2026-07-15 09:30:00")
    assert gate.is_blackout(now) is True


def test_no_blackout_day_after_release() -> None:
    release = date(2026, 7, 15)
    gate = EconCalendarGate(release_calendar=_StubCalendar(release))
    now = pd.Timestamp("2026-07-16 09:30:00")
    assert gate.is_blackout(now) is False


def test_fomc_date_is_blackout() -> None:
    fomc = date(2026, 9, 16)
    gate = EconCalendarGate(release_calendar=None, fomc_dates=[fomc])
    now = pd.Timestamp("2026-09-16 14:00:00")
    assert gate.is_blackout(now) is True


def test_fomc_from_default_constant_list() -> None:
    # A gate with a real default FOMC list should blackout a known 2026 date.
    gate = EconCalendarGate(release_calendar=None)
    assert len(EconCalendarGate.DEFAULT_FOMC_DATES) > 0
    known_fomc = EconCalendarGate.DEFAULT_FOMC_DATES[0]
    now = pd.Timestamp(known_fomc)
    assert gate.is_blackout(now) is True


def test_none_calendar_never_blackout() -> None:
    gate = EconCalendarGate(release_calendar=None, fomc_dates=[])
    # No calendar and no FOMC match -> never blackout, on any date.
    assert gate.is_blackout(pd.Timestamp("2026-07-15 09:30:00")) is False
    assert gate.is_blackout(pd.Timestamp("2020-01-02 09:30:00")) is False


def test_raising_calendar_is_graceful() -> None:
    gate = EconCalendarGate(release_calendar=_RaisingCalendar(), fomc_dates=[])
    # Calendar raises -> gate swallows and returns False, never propagates.
    assert gate.is_blackout(pd.Timestamp("2026-07-15 09:30:00")) is False


def test_custom_series_are_queried() -> None:
    release = date(2026, 7, 15)
    stub = _StubCalendar(release)
    gate = EconCalendarGate(release_calendar=stub)
    now = pd.Timestamp("2026-07-15 09:30:00")
    gate.is_blackout(now, series=("CPIAUCSL",))
    assert stub.calls == [("CPIAUCSL", date(2026, 7, 15))]


def test_non_release_day_with_calendar_returning_other_date() -> None:
    # Calendar's next release is in the future -> today is not a release day.
    stub = _StubCalendar(date(2026, 8, 12))
    gate = EconCalendarGate(release_calendar=stub, fomc_dates=[])
    now = pd.Timestamp("2026-07-15 09:30:00")
    assert gate.is_blackout(now) is False


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
