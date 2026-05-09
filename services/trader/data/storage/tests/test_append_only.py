"""Append-only semantics: re-running the same write must not duplicate rows;
restatements must coexist with originals.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from services.trader.data.connectors.base import ConnectorResult
from services.trader.data.storage import ParquetAdapter
from services.trader.data.storage.tests.conftest import make_ohlcv_frame


def _result(frame: pd.DataFrame, source: str = "yfinance") -> ConnectorResult:
    return ConnectorResult(
        frame=frame,
        source=source,
        fetched_at=datetime.now(UTC),
        rows=len(frame),
    )


class TestIdempotentRewrites:
    def test_writing_same_frame_twice_dedupes(self, adapter: ParquetAdapter) -> None:
        df = make_ohlcv_frame(ticker="SPY", bars=5)
        first = adapter.write(_result(df), kind="ohlcv")
        second = adapter.write(_result(df), kind="ohlcv")
        assert first == 5
        assert second == 0  # all rows already present, none added

        out = adapter.read(
            kind="ohlcv",
            keys=["SPY"],
            start=datetime(2026, 1, 1, tzinfo=UTC),
            end=datetime(2026, 1, 31, tzinfo=UTC),
        )
        assert len(out) == 5  # not 10 — duplicates collapsed


class TestRestatementsCoexist:
    def test_original_plus_restatement_both_persist(
        self, adapter: ParquetAdapter
    ) -> None:
        original = make_ohlcv_frame(ticker="SPY", bars=2)
        adapter.write(_result(original), kind="ohlcv")

        restated = make_ohlcv_frame(
            ticker="SPY",
            bars=2,
            revision_at=datetime(2026, 2, 1, tzinfo=UTC),
            base_close=999.0,
        )
        rows_added = adapter.write(_result(restated), kind="ohlcv")
        assert rows_added == 2  # both restated bars are new rows

        # Both versions exist on disk; verify by reading at far-future asof and seeing
        # the restated value, then again at pre-restatement asof and seeing the original.
        future = adapter.read(
            kind="ohlcv",
            keys=["SPY"],
            start=datetime(2026, 1, 1, tzinfo=UTC),
            end=datetime(2026, 1, 31, tzinfo=UTC),
            asof=datetime(2026, 12, 31, tzinfo=UTC),
        )
        assert future["close"].iloc[0] == 999.5

        early = adapter.read(
            kind="ohlcv",
            keys=["SPY"],
            start=datetime(2026, 1, 1, tzinfo=UTC),
            end=datetime(2026, 1, 31, tzinfo=UTC),
            asof=datetime(2026, 1, 31, tzinfo=UTC),
        )
        assert early["close"].iloc[0] == 100.5  # the original value


def test_partition_file_grows_across_writes(adapter: ParquetAdapter) -> None:
    week1 = make_ohlcv_frame(ticker="SPY", start=datetime(2026, 1, 5, tzinfo=UTC), bars=3)
    week2 = make_ohlcv_frame(ticker="SPY", start=datetime(2026, 1, 12, tzinfo=UTC), bars=3)
    adapter.write(_result(week1), kind="ohlcv")
    adapter.write(_result(week2), kind="ohlcv")

    # One partition file (same ticker, same year), with all 6 rows
    partitions = adapter.list_partitions(kind="ohlcv", key="SPY")
    assert len(partitions) == 1

    out = adapter.read(
        kind="ohlcv",
        keys=["SPY"],
        start=datetime(2026, 1, 1, tzinfo=UTC),
        end=datetime(2026, 1, 31, tzinfo=UTC),
    )
    assert len(out) == 6
