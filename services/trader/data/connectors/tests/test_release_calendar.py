"""Tests for the FRED release-calendar lookup."""

from __future__ import annotations

from datetime import date

import pytest

from services.trader.data.connectors.base import ConnectorError
from services.trader.data.connectors.release_calendar import (
    ReleaseCalendar,
    ReleaseDateMissingError,
)


class FakeFetcher:
    """Records calls + returns canned bodies keyed by URL suffix."""

    def __init__(self, responses: dict[str, dict[str, object]]) -> None:
        self._responses = responses
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get_json(self, url: str, params: dict[str, str]) -> dict[str, object]:
        self.calls.append((url, dict(params)))
        for suffix, body in self._responses.items():
            if url.endswith(suffix):
                return body
        raise AssertionError(f"unexpected URL: {url}")


CPI_SERIES_RELEASE = {
    "/series/release": {
        "releases": [{"id": 10, "name": "Consumer Price Index"}]
    }
}

CPI_RELEASE_DATES = {
    "/release/dates": {
        "release_dates": [
            {"release_id": 10, "date": "2025-12-11"},
            {"release_id": 10, "date": "2026-01-15"},
            {"release_id": 10, "date": "2026-02-13"},
            {"release_id": 10, "date": "2026-03-13"},
        ]
    }
}


class TestReleaseIdLookup:
    def test_series_release_returns_first_release(self) -> None:
        fetcher = FakeFetcher({**CPI_SERIES_RELEASE, **CPI_RELEASE_DATES})
        calendar = ReleaseCalendar(fetcher, api_key="dummy")
        assert calendar.release_id_for_series("CPIAUCSL") == 10

    def test_release_id_cached(self) -> None:
        fetcher = FakeFetcher({**CPI_SERIES_RELEASE, **CPI_RELEASE_DATES})
        calendar = ReleaseCalendar(fetcher, api_key="dummy")
        calendar.release_id_for_series("CPIAUCSL")
        calendar.release_id_for_series("CPIAUCSL")
        # Only one call to /series/release for that series
        series_calls = [c for c in fetcher.calls if c[0].endswith("/series/release")]
        assert len(series_calls) == 1

    def test_no_release_raises(self) -> None:
        fetcher = FakeFetcher({"/series/release": {"releases": []}})
        calendar = ReleaseCalendar(fetcher, api_key="dummy")
        with pytest.raises(ConnectorError, match="no associated release"):
            calendar.release_id_for_series("MISSING")


class TestReleaseDates:
    def test_release_dates_returned_sorted(self) -> None:
        fetcher = FakeFetcher({**CPI_SERIES_RELEASE, **CPI_RELEASE_DATES})
        calendar = ReleaseCalendar(fetcher, api_key="dummy")
        dates = calendar.release_dates(10)
        assert dates == [
            date(2025, 12, 11),
            date(2026, 1, 15),
            date(2026, 2, 13),
            date(2026, 3, 13),
        ]

    def test_release_dates_cached(self) -> None:
        fetcher = FakeFetcher({**CPI_SERIES_RELEASE, **CPI_RELEASE_DATES})
        calendar = ReleaseCalendar(fetcher, api_key="dummy")
        calendar.release_dates(10)
        calendar.release_dates(10)
        date_calls = [c for c in fetcher.calls if c[0].endswith("/release/dates")]
        assert len(date_calls) == 1


class TestAsOfReleaseDate:
    def test_picks_smallest_release_date_after_reference(self) -> None:
        fetcher = FakeFetcher({**CPI_SERIES_RELEASE, **CPI_RELEASE_DATES})
        calendar = ReleaseCalendar(fetcher, api_key="dummy")
        # Jan 2026 reference month -> first release on/after Jan 1 is Jan 15.
        assert calendar.as_of_release_date("CPIAUCSL", date(2026, 1, 1)) == date(
            2026, 1, 15
        )

    def test_reference_date_after_all_releases_raises(self) -> None:
        fetcher = FakeFetcher({**CPI_SERIES_RELEASE, **CPI_RELEASE_DATES})
        calendar = ReleaseCalendar(fetcher, api_key="dummy")
        with pytest.raises(ReleaseDateMissingError):
            calendar.as_of_release_date("CPIAUCSL", date(2099, 1, 1))

    def test_reset_cache_forces_refetch(self) -> None:
        fetcher = FakeFetcher({**CPI_SERIES_RELEASE, **CPI_RELEASE_DATES})
        calendar = ReleaseCalendar(fetcher, api_key="dummy")
        calendar.as_of_release_date("CPIAUCSL", date(2026, 1, 1))
        before = len(fetcher.calls)
        calendar.reset_cache()
        calendar.as_of_release_date("CPIAUCSL", date(2026, 1, 1))
        after = len(fetcher.calls)
        # Two more calls: re-resolve series_release + re-fetch release_dates.
        assert after - before == 2
