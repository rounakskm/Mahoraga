"""Tests for the FRED connector.

All HTTP traffic is mocked via the same `FakeFetcher` shape used in
`test_release_calendar.py`. No live network calls.
"""

from __future__ import annotations

from datetime import date

import pytest

from services.trader.data.connectors.base import ConnectorError, RateLimiter
from services.trader.data.connectors.fred import FredConnector


class FakeFetcher:
    """Pluggable fetcher that returns canned bodies keyed by URL suffix.

    Tracks call counts so tests can assert caching behaviour.
    """

    def __init__(self, responses: dict[str, dict[str, object]]) -> None:
        self._responses = responses
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get_json(self, url: str, params: dict[str, str]) -> dict[str, object]:
        self.calls.append((url, dict(params)))
        for suffix, body in self._responses.items():
            if url.endswith(suffix):
                return body
        raise AssertionError(f"unexpected URL: {url}")


CPI_RESPONSES = {
    "/series": {
        "seriess": [
            {
                "id": "CPIAUCSL",
                "title": "Consumer Price Index for All Urban Consumers",
                "units_short": "Index 1982-1984=100",
            }
        ]
    },
    "/series/release": {"releases": [{"id": 10, "name": "Consumer Price Index"}]},
    "/release/dates": {
        "release_dates": [
            {"release_id": 10, "date": "2026-01-15"},
            {"release_id": 10, "date": "2026-02-13"},
            {"release_id": 10, "date": "2026-03-13"},
        ]
    },
    "/series/observations": {
        "observations": [
            {"date": "2025-12-01", "value": "319.0"},
            {"date": "2026-01-01", "value": "320.5"},
            {"date": "2026-02-01", "value": "321.2"},
        ]
    },
}


def _make_connector(
    *,
    responses: dict[str, dict[str, object]] | None = None,
    api_key: str = "test-key",
) -> tuple[FredConnector, FakeFetcher]:
    fetcher = FakeFetcher(responses or CPI_RESPONSES)
    rate_limiter = RateLimiter(capacity=100.0, refill_rate_per_sec=1000.0)
    connector = FredConnector(
        api_key=api_key,
        rate_limiter=rate_limiter,
        fetcher=fetcher,
        sleep=lambda _s: None,
    )
    return connector, fetcher


class TestFetchHappyPath:
    def test_returns_normalized_macro_frame(self) -> None:
        connector, _ = _make_connector()
        result = connector.fetch(
            "CPIAUCSL", date(2025, 12, 1), date(2026, 2, 28)
        )
        assert result.source == "fred"
        assert result.rows == 3
        df = result.frame
        assert list(df.columns) == [
            "indicator",
            "reference_date",
            "as_of_release_date",
            "value",
            "unit",
            "source",
            "fetched_at",
        ]
        assert (df["indicator"] == "CPIAUCSL").all()
        assert (df["source"] == "fred").all()
        assert (df["unit"] == "Index 1982-1984=100").all()
        assert df["value"].tolist() == [319.0, 320.5, 321.2]

    def test_as_of_release_date_populated_from_calendar(self) -> None:
        connector, _ = _make_connector()
        df = connector.fetch(
            "CPIAUCSL", date(2025, 12, 1), date(2026, 2, 28)
        ).frame
        # Dec 2025 -> first release >= Dec 1 is Jan 15
        # Jan 2026 -> first release >= Jan 1 is Jan 15
        # Feb 2026 -> first release >= Feb 1 is Feb 13
        assert df["as_of_release_date"].tolist() == [
            date(2026, 1, 15),
            date(2026, 1, 15),
            date(2026, 2, 13),
        ]

    def test_caching_avoids_redundant_metadata_calls(self) -> None:
        connector, fetcher = _make_connector()
        connector.fetch("CPIAUCSL", date(2025, 12, 1), date(2026, 2, 28))
        # Re-fetch a longer window — same series, same release. Metadata calls
        # should be cached.
        before = len(fetcher.calls)
        connector.fetch("CPIAUCSL", date(2025, 12, 1), date(2026, 2, 28))
        after = len(fetcher.calls)
        new_calls = fetcher.calls[before:after]
        # Only /series and /series/observations refetched; /release/dates and
        # /series/release should be cached.
        suffixes = [u for u, _ in new_calls]
        assert any(s.endswith("/series/observations") for s in suffixes)
        assert not any(s.endswith("/release/dates") for s in suffixes)
        assert not any(s.endswith("/series/release") for s in suffixes)


class TestFetchEdgeCases:
    def test_missing_observations_skipped_not_fabricated(self) -> None:
        responses = {
            **CPI_RESPONSES,
            "/series/observations": {
                "observations": [
                    {"date": "2026-01-01", "value": "."},  # FRED's missing-value sentinel
                    {"date": "2026-02-01", "value": "321.2"},
                ]
            },
        }
        connector, _ = _make_connector(responses=responses)
        result = connector.fetch("CPIAUCSL", date(2026, 1, 1), date(2026, 2, 28))
        assert result.rows == 1  # only Feb survives
        assert result.frame["reference_date"].iloc[0] == date(2026, 2, 1)

    def test_observation_after_all_release_dates_skipped(self) -> None:
        responses = {
            **CPI_RESPONSES,
            "/series/observations": {
                "observations": [
                    {"date": "2026-01-01", "value": "320.5"},
                    {"date": "2099-12-01", "value": "999.0"},  # no release date >= this
                ]
            },
        }
        connector, _ = _make_connector(responses=responses)
        result = connector.fetch("CPIAUCSL", date(2026, 1, 1), date(2099, 12, 31))
        assert result.rows == 1
        assert result.frame["reference_date"].iloc[0] == date(2026, 1, 1)


class TestFetchValidation:
    def test_missing_api_key_raises(self) -> None:
        with pytest.raises(ConnectorError, match="FRED_API_KEY"):
            FredConnector(api_key="", fetcher=FakeFetcher({}))

    def test_inverted_window_rejected(self) -> None:
        connector, _ = _make_connector()
        with pytest.raises(ConnectorError, match="after end"):
            connector.fetch("CPIAUCSL", date(2026, 5, 1), date(2026, 1, 1))

    def test_empty_series_id_rejected(self) -> None:
        connector, _ = _make_connector()
        with pytest.raises(ConnectorError, match="invalid FRED series_id"):
            connector.fetch("", date(2026, 1, 1), date(2026, 5, 1))

    def test_unknown_series_raises(self) -> None:
        responses = {
            **CPI_RESPONSES,
            "/series": {"seriess": []},
        }
        connector, _ = _make_connector(responses=responses)
        with pytest.raises(ConnectorError, match="not found"):
            connector.fetch("BOGUS", date(2026, 1, 1), date(2026, 5, 1))
