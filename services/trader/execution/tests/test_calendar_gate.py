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


# ---------------------------------------------------------------------------
# C5 — fail-closed on persistent calendar failure, FOMC-schedule expiry guard,
# and US/Eastern date normalization.
# ---------------------------------------------------------------------------

_FAR_FUTURE_FOMC = date(2099, 1, 1)  # keeps the expiry guard out of the way.


def test_three_consecutive_failures_fail_closed() -> None:
    """1st/2nd lookup failures stay graceful-open; the 3rd fails CLOSED (blackout)."""
    gate = EconCalendarGate(
        release_calendar=_RaisingCalendar(), fomc_dates=[_FAR_FUTURE_FOMC]
    )
    now = pd.Timestamp("2026-07-15 09:30:00")
    assert gate.is_blackout(now, series=("CPIAUCSL",)) is False  # failure 1
    assert gate.is_blackout(now, series=("CPIAUCSL",)) is False  # failure 2
    assert gate.is_blackout(now, series=("CPIAUCSL",)) is True  # failure 3 -> closed


def test_successful_lookup_resets_failure_counter() -> None:
    """A success between failures resets the consecutive-failure count."""

    class _FlakyCalendar:
        def __init__(self) -> None:
            self.fail = True

        def as_of_release_date(self, series_id: str, reference_date: date) -> date:
            if self.fail:
                raise RuntimeError("FRED unreachable")
            return date(2099, 6, 1)  # not today -> no blackout

    cal = _FlakyCalendar()
    gate = EconCalendarGate(release_calendar=cal, fomc_dates=[_FAR_FUTURE_FOMC])
    now = pd.Timestamp("2026-07-15 09:30:00")
    assert gate.is_blackout(now, series=("CPIAUCSL",)) is False  # failure 1
    assert gate.is_blackout(now, series=("CPIAUCSL",)) is False  # failure 2
    cal.fail = False
    assert gate.is_blackout(now, series=("CPIAUCSL",)) is False  # success -> reset
    cal.fail = True
    assert gate.is_blackout(now, series=("CPIAUCSL",)) is False  # failure 1 again
    assert gate.is_blackout(now, series=("CPIAUCSL",)) is False  # failure 2
    assert gate.is_blackout(now, series=("CPIAUCSL",)) is True  # failure 3 -> closed


def test_last_known_fomc() -> None:
    gate = EconCalendarGate(release_calendar=None)
    assert gate.last_known_fomc() == max(EconCalendarGate.DEFAULT_FOMC_DATES)
    assert EconCalendarGate(release_calendar=None, fomc_dates=[]).last_known_fomc() is None


def test_fomc_schedule_exhausted_fails_closed() -> None:
    """Past the last known FOMC date the gate refuses entries until updated."""
    gate = EconCalendarGate(release_calendar=None)
    beyond = pd.Timestamp(max(EconCalendarGate.DEFAULT_FOMC_DATES)) + pd.Timedelta(days=30)
    assert gate.is_blackout(beyond) is True


def test_fomc_day_matched_in_eastern_time() -> None:
    """2026-09-17 03:00 UTC is still 2026-09-16 (FOMC day) in US/Eastern."""
    gate = EconCalendarGate(release_calendar=None, fomc_dates=[date(2026, 9, 16)])
    now = pd.Timestamp("2026-09-17 03:00:00", tz="UTC")
    assert gate.is_blackout(now) is True


def test_day_after_fomc_in_eastern_is_no_blackout() -> None:
    gate = EconCalendarGate(
        release_calendar=None, fomc_dates=[date(2026, 9, 16), _FAR_FUTURE_FOMC]
    )
    now = pd.Timestamp("2026-09-17 15:00:00", tz="UTC")  # 11:00 ET on the 17th.
    assert gate.is_blackout(now) is False


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
