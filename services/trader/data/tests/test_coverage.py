"""Tests for the coverage monitor."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
import pytest

from services.trader.data.connectors.base import ConnectorResult
from services.trader.data.coverage import (
    CoverageError,
    nyse_trading_days,
    report_macro,
    report_ohlcv,
)
from services.trader.data.storage import ParquetAdapter


@pytest.fixture
def adapter(tmp_path: Path) -> ParquetAdapter:
    # Coverage tests use 2026 dates; opt out of vault enforcement so the
    # default 180-day cutoff doesn't false-positive.
    return ParquetAdapter(tmp_path, vault_cutoff_days=None)


def _result(frame: pd.DataFrame, source: str = "yfinance") -> ConnectorResult:
    return ConnectorResult(
        frame=frame,
        source=source,
        fetched_at=datetime.now(UTC),
        rows=len(frame),
    )


def _ohlcv_frame(ticker: str, dates: list[pd.Timestamp]) -> pd.DataFrame:
    fetched = pd.Timestamp("2026-01-31 23:00", tz="UTC")
    rows = [
        {
            "ticker": ticker,
            "bar_timestamp": ts,
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 1_000_000,
            "adj_close": 100.4,
            "source": "yfinance",
            "fetched_at": fetched,
            "revision_at": pd.NaT,
        }
        for ts in dates
    ]
    df = pd.DataFrame(rows)
    df["bar_timestamp"] = pd.to_datetime(df["bar_timestamp"], utc=True)
    df["fetched_at"] = pd.to_datetime(df["fetched_at"], utc=True)
    df["revision_at"] = pd.to_datetime(df["revision_at"], utc=True)
    return df


def _macro_frame(rows: list[dict[str, object]]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df["fetched_at"] = pd.to_datetime(df["fetched_at"], utc=True)
    return df


# ---- OHLCV --------------------------------------------------------------


class TestOhlcvCoverage:
    def test_full_coverage_passes(self, adapter: ParquetAdapter) -> None:
        # Synthetic 5-day window; all 5 expected trading days present.
        expected = pd.DatetimeIndex(
            ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08", "2026-01-09"],
            tz="UTC",
        )
        df = _ohlcv_frame("SPY", list(expected))
        adapter.write(_result(df), kind="ohlcv")

        report = report_ohlcv(
            adapter,
            ticker="SPY",
            start=date(2026, 1, 5),
            end=date(2026, 1, 9),
            expected=expected,
        )
        assert report.passed
        assert report.coverage_pct == 100.0
        assert report.missing_count == 0

    def test_deliberate_gap_fails(self, adapter: ParquetAdapter) -> None:
        expected = pd.DatetimeIndex(
            ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08", "2026-01-09"],
            tz="UTC",
        )
        # Drop the middle day deliberately
        present = [expected[0], expected[1], expected[3], expected[4]]
        df = _ohlcv_frame("SPY", present)
        adapter.write(_result(df), kind="ohlcv")

        report = report_ohlcv(
            adapter,
            ticker="SPY",
            start=date(2026, 1, 5),
            end=date(2026, 1, 9),
            expected=expected,
            threshold_pct=99.0,
        )
        assert not report.passed
        assert report.missing_count == 1
        assert "2026-01-07" in report.missing_sample

    def test_no_data_for_ticker_reports_zero(self, adapter: ParquetAdapter) -> None:
        expected = pd.DatetimeIndex(["2026-01-05", "2026-01-06"], tz="UTC")
        report = report_ohlcv(
            adapter,
            ticker="MISSING",
            start=date(2026, 1, 5),
            end=date(2026, 1, 6),
            expected=expected,
            threshold_pct=99.0,
        )
        assert report.present_count == 0
        assert report.missing_count == 2
        assert report.coverage_pct == 0.0
        assert not report.passed


# ---- Macro --------------------------------------------------------------


class TestMacroCoverage:
    def test_all_releases_present(self, adapter: ParquetAdapter) -> None:
        rows = [
            {
                "indicator": "CPIAUCSL",
                "reference_date": date(2026, 1, 1),
                "as_of_release_date": date(2026, 2, 13),
                "value": 320.0,
                "unit": "Index",
                "source": "fred",
                "fetched_at": pd.Timestamp("2026-02-13 12:00", tz="UTC"),
            },
            {
                "indicator": "CPIAUCSL",
                "reference_date": date(2026, 2, 1),
                "as_of_release_date": date(2026, 3, 13),
                "value": 321.0,
                "unit": "Index",
                "source": "fred",
                "fetched_at": pd.Timestamp("2026-03-13 12:00", tz="UTC"),
            },
        ]
        adapter.write(_result(_macro_frame(rows), source="fred"), kind="macro")

        expected = pd.DatetimeIndex(["2026-01-01", "2026-02-01"])
        report = report_macro(
            adapter,
            indicator="CPIAUCSL",
            expected_reference_dates=expected,
            asof=datetime(2026, 4, 1, tzinfo=UTC),
        )
        assert report.passed
        assert report.coverage_pct == 100.0

    def test_missing_release_fails(self, adapter: ParquetAdapter) -> None:
        rows = [
            {
                "indicator": "CPIAUCSL",
                "reference_date": date(2026, 1, 1),
                "as_of_release_date": date(2026, 2, 13),
                "value": 320.0,
                "unit": "Index",
                "source": "fred",
                "fetched_at": pd.Timestamp("2026-02-13 12:00", tz="UTC"),
            }
        ]
        adapter.write(_result(_macro_frame(rows), source="fred"), kind="macro")

        expected = pd.DatetimeIndex(["2026-01-01", "2026-02-01"])
        report = report_macro(
            adapter,
            indicator="CPIAUCSL",
            expected_reference_dates=expected,
            asof=datetime(2026, 4, 1, tzinfo=UTC),
            threshold_pct=99.0,
        )
        assert not report.passed
        assert report.missing_count == 1
        assert "2026-02-01" in report.missing_sample


# ---- Calendar awareness -------------------------------------------------


@pytest.mark.skipif(
    pytest.importorskip("pandas_market_calendars", reason="pandas_market_calendars not installed")
    is None,
    reason="pandas_market_calendars not installed",
)
class TestCalendarAwareness:
    def test_nyse_skips_weekends_and_holidays(self) -> None:
        # Jan 1 2026 (Thu) is New Year's Day (NYSE closed)
        # Jan 5–9 (Mon–Fri) all trading, Jan 19 is MLK Day
        days = nyse_trading_days(date(2026, 1, 1), date(2026, 1, 31))
        assert pd.Timestamp("2026-01-01", tz="UTC") not in days  # holiday
        assert pd.Timestamp("2026-01-03", tz="UTC") not in days  # weekend
        assert pd.Timestamp("2026-01-05", tz="UTC") in days
        assert pd.Timestamp("2026-01-19", tz="UTC") not in days  # MLK


def test_coverage_error_is_exception_subclass() -> None:
    assert issubclass(CoverageError, Exception)
