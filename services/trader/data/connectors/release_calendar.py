"""FRED release-calendar lookup.

Maps `(series_id, reference_date) -> as_of_release_date` so that every macro
row can be tagged with the date its value first became publicly available —
the load-bearing piece of the storage layer's PIT discipline.

Implementation strategy (per `data-foundation-spec.md` §6 and §7):

1. For each `series_id`, FRED tells us which release schedule it belongs to
   via `/fred/series/release`.
2. For that `release_id`, FRED returns the historical schedule of release
   dates via `/fred/release/dates`.
3. The `as_of_release_date` for a given observation is the smallest release
   date `>= reference_date` (the first scheduled release on or after the
   period the value covers).

Both lookups are cached locally so a typical ingest hits FRED once per series
+ once per release per process, regardless of how many observations are
fetched.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Protocol

from services.trader.data.connectors.base import ConnectorError

logger = logging.getLogger(__name__)

FRED_BASE_URL = "https://api.stlouisfed.org/fred"


class HttpFetcher(Protocol):
    """Minimal HTTP-fetch surface so tests can inject a fake."""

    def get_json(self, url: str, params: dict[str, str]) -> dict[str, object]:
        ...


@dataclass
class ReleaseDateMissingError(Exception):
    series_id: str
    reference_date: date

    def __str__(self) -> str:  # pragma: no cover - simple formatting
        return (
            f"FRED release-calendar lookup failed: no release date >= {self.reference_date} "
            f"found for series {self.series_id}"
        )


class ReleaseCalendar:
    """Cached lookup for FRED's release schedule.

    Designed for thread-naive single-process use; if multiple ingests run in
    parallel they should each construct their own instance.
    """

    def __init__(self, fetcher: HttpFetcher, *, api_key: str) -> None:
        self._fetcher = fetcher
        self._api_key = api_key
        self._series_release_cache: dict[str, int] = {}
        self._release_dates_cache: dict[int, list[date]] = {}

    # --- public ----------------------------------------------------------

    def release_id_for_series(self, series_id: str) -> int:
        if series_id in self._series_release_cache:
            return self._series_release_cache[series_id]
        body = self._fetcher.get_json(
            f"{FRED_BASE_URL}/series/release",
            {"series_id": series_id, "api_key": self._api_key, "file_type": "json"},
        )
        releases = body.get("releases") or []
        if not releases:
            raise ConnectorError(f"FRED series {series_id!r} has no associated release")
        # FRED returns one or more releases; the first is the canonical
        # publication schedule for the series.
        release_id = int(releases[0]["id"])  # type: ignore[index]
        self._series_release_cache[series_id] = release_id
        return release_id

    def release_dates(self, release_id: int) -> list[date]:
        if release_id in self._release_dates_cache:
            return self._release_dates_cache[release_id]
        body = self._fetcher.get_json(
            f"{FRED_BASE_URL}/release/dates",
            {
                "release_id": str(release_id),
                "api_key": self._api_key,
                "file_type": "json",
                "include_release_dates_with_no_data": "false",
                # FRED defaults to ascending order; be explicit.
                "sort_order": "asc",
            },
        )
        rows = body.get("release_dates") or []
        dates = sorted(date.fromisoformat(str(row["date"])) for row in rows)  # type: ignore[index]
        self._release_dates_cache[release_id] = dates
        return dates

    def as_of_release_date(self, series_id: str, reference_date: date) -> date:
        """Return the smallest release date `>= reference_date` for `series_id`."""
        release_id = self.release_id_for_series(series_id)
        dates = self.release_dates(release_id)
        for d in dates:
            if d >= reference_date:
                return d
        raise ReleaseDateMissingError(series_id=series_id, reference_date=reference_date)

    # Helper used by tests + future maintainers to clear caches between runs.
    def reset_cache(self) -> None:
        self._series_release_cache.clear()
        self._release_dates_cache.clear()


# Public helper: cushion the release-window query for downstream callers that
# want to avoid a tiny edge case where a release_date barely beats `reference
# + N days`. Currently unused; left as a stub for chunk 4's coverage monitor.
def expected_release_window(reference_date: date, *, lag_days: int = 45) -> tuple[date, date]:
    return reference_date, reference_date + timedelta(days=lag_days)
