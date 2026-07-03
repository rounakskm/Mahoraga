"""Economic-calendar entry blackout gate (FOMC / CPI / NFP).

Blocks new entries on scheduled macro-release days so the executor never opens
a position into a known volatility event. Two sources:

1. **FOMC** — the Fed has no FRED series, so meeting-decision dates come from a
   small committed constant list (`DEFAULT_FOMC_DATES`, the 2026 schedule).
2. **CPI / NFP** — via the injected `ReleaseCalendar` (FRED release dates for
   `CPIAUCSL` and `PAYEMS`).

Graceful by design — but FAIL-CLOSED under persistent failure: a transient
calendar error is swallowed (no blackout) so one flaky FRED lookup can never
wedge the executor, yet after `MAX_CONSECUTIVE_FAILURES` consecutive lookup
failures the gate returns True (blackout) until a lookup succeeds — a broken
calendar must not silently disarm the release-day protection. Likewise, once
`now` passes the last known FOMC date the schedule is exhausted and the gate
refuses entries until the constant list is updated.

Dates are compared in US/Eastern (the release-clock timezone): a tz-aware `now`
is converted before `.date()`; a naive `now` is trusted as already-Eastern wall
time.

# ponytail: daily-granularity blackout (release day) since FRED gives dates
# not times; tighten to ±30min around the intraday release time when an
# intraday time source is wired.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Protocol

import pandas as pd

logger = logging.getLogger(__name__)

# Default CPI (CPIAUCSL) + NFP (PAYEMS) FRED series to check for release days.
DEFAULT_SERIES: tuple[str, ...] = ("CPIAUCSL", "PAYEMS")


class _ReleaseCalendarLike(Protocol):
    """The single method the gate needs from `ReleaseCalendar`."""

    def as_of_release_date(self, series_id: str, reference_date: date) -> date:
        ...


class EconCalendarGate:
    """Return True when `now` lands on a scheduled FOMC / CPI / NFP release day.

    Args:
        release_calendar: A `ReleaseCalendar` (or compatible) for CPI/NFP FRED
            release dates. `None` disables the CPI/NFP check (graceful no-op).
        blackout_minutes: Reserved for the future intraday ±window; unused while
            blackout is release-day granularity (see module ponytail note).
        fomc_dates: FOMC decision dates to blackout. Defaults to the committed
            `DEFAULT_FOMC_DATES` 2026 schedule.
    """

    # 2026 FOMC meeting decision (second/statement) days — Federal Reserve schedule.
    DEFAULT_FOMC_DATES: tuple[date, ...] = (
        date(2026, 1, 28),
        date(2026, 3, 18),
        date(2026, 4, 29),
        date(2026, 6, 17),
        date(2026, 7, 29),
        date(2026, 9, 16),
        date(2026, 10, 28),
        date(2026, 12, 9),
    )

    # Consecutive lookup failures tolerated before the gate fails CLOSED.
    MAX_CONSECUTIVE_FAILURES: int = 3

    def __init__(
        self,
        release_calendar: _ReleaseCalendarLike | None = None,
        blackout_minutes: int = 30,
        fomc_dates: list[date] | None = None,
    ) -> None:
        self._release_calendar = release_calendar
        self._blackout_minutes = blackout_minutes
        self._fomc_dates: frozenset[date] = frozenset(
            self.DEFAULT_FOMC_DATES if fomc_dates is None else fomc_dates
        )
        self._consecutive_failures = 0

    def last_known_fomc(self) -> date | None:
        """The last FOMC date the gate knows about, or None with an empty schedule."""
        return max(self._fomc_dates) if self._fomc_dates else None

    @staticmethod
    def _eastern_date(now: pd.Timestamp) -> date:
        """`now` as a US/Eastern calendar date (naive input = already-Eastern)."""
        if now.tzinfo is None:
            return now.date()
        return now.tz_convert("US/Eastern").date()

    def is_blackout(
        self,
        now: pd.Timestamp,
        series: tuple[str, ...] = DEFAULT_SERIES,
    ) -> bool:
        """True if `now`'s US/Eastern date is a scheduled FOMC / CPI / NFP release day.

        Fail-closed twice over: past the last known FOMC date the schedule is
        exhausted (True until updated), and after `MAX_CONSECUTIVE_FAILURES`
        consecutive calendar-lookup failures the gate blacks out rather than
        trading blind through an unknown release day.
        """
        today = self._eastern_date(now)

        # Expiry guard: an exhausted FOMC schedule cannot clear any date after
        # its last entry. (An explicitly-empty schedule disables the FOMC check
        # entirely — test isolation — so the guard only applies when non-empty.)
        last_fomc = self.last_known_fomc()
        if last_fomc is not None and today > last_fomc:
            logger.error(
                "FOMC schedule exhausted (last known %s < %s) — "
                "refusing entries until updated",
                last_fomc,
                today,
            )
            return True

        if today in self._fomc_dates:
            logger.info("econ-calendar blackout: %s is an FOMC decision day", today)
            return True

        if self._release_calendar is None:
            return False

        for series_id in series:
            try:
                next_release = self._release_calendar.as_of_release_date(series_id, today)
            except Exception:  # noqa: BLE001 — tolerate transient failures, bounded below
                self._consecutive_failures += 1
                if self._consecutive_failures >= self.MAX_CONSECUTIVE_FAILURES:
                    logger.error(
                        "econ-calendar lookup failed %d consecutive time(s) for %s — "
                        "failing CLOSED (blackout) until a lookup succeeds",
                        self._consecutive_failures,
                        series_id,
                        exc_info=True,
                    )
                    return True
                logger.warning(
                    "econ-calendar lookup failed for %s (consecutive failure %d/%d); "
                    "treating as no blackout",
                    series_id,
                    self._consecutive_failures,
                    self.MAX_CONSECUTIVE_FAILURES,
                    exc_info=True,
                )
                continue
            self._consecutive_failures = 0
            if next_release == today:
                logger.info(
                    "econ-calendar blackout: %s is a %s release day", today, series_id
                )
                return True

        return False
