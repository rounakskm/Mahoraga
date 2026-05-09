"""Round-trip tests: write a frame, read it back."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from services.trader.data.connectors.base import ConnectorResult
from services.trader.data.storage import ParquetAdapter
from services.trader.data.storage.tests.conftest import make_macro_frame, make_ohlcv_frame


def _make_result(frame: pd.DataFrame, source: str = "yfinance") -> ConnectorResult:
    return ConnectorResult(
        frame=frame,
        source=source,
        fetched_at=datetime.now(UTC),
        rows=len(frame),
    )


class TestOhlcvRoundtrip:
    def test_write_then_read_returns_same_rows(self, adapter: ParquetAdapter) -> None:
        df = make_ohlcv_frame(ticker="SPY", bars=5)
        written = adapter.write(_make_result(df), kind="ohlcv")
        assert written == 5

        out = adapter.read(
            kind="ohlcv",
            keys=["SPY"],
            start=datetime(2026, 1, 5, tzinfo=UTC),
            end=datetime(2026, 1, 31, tzinfo=UTC),
        )
        assert len(out) == 5
        assert (out["ticker"] == "SPY").all()
        assert out["close"].tolist() == df["close"].tolist()

    def test_partition_files_created_under_ohlcv_ticker_year(
        self, adapter: ParquetAdapter, tmp_path: Path
    ) -> None:
        df = make_ohlcv_frame(ticker="QQQ", bars=2)
        adapter.write(_make_result(df), kind="ohlcv")
        partitions = adapter.list_partitions(kind="ohlcv", key="QQQ")
        assert len(partitions) == 1
        assert partitions[0].name == "2026.parquet"
        assert partitions[0].parent == tmp_path / "ohlcv" / "QQQ"

    def test_multi_ticker_segregated(self, adapter: ParquetAdapter) -> None:
        adapter.write(_make_result(make_ohlcv_frame(ticker="SPY", bars=3)), kind="ohlcv")
        adapter.write(_make_result(make_ohlcv_frame(ticker="QQQ", bars=3)), kind="ohlcv")
        spy = adapter.read(
            kind="ohlcv",
            keys=["SPY"],
            start=datetime(2026, 1, 1, tzinfo=UTC),
            end=datetime(2026, 1, 31, tzinfo=UTC),
        )
        qqq = adapter.read(
            kind="ohlcv",
            keys=["QQQ"],
            start=datetime(2026, 1, 1, tzinfo=UTC),
            end=datetime(2026, 1, 31, tzinfo=UTC),
        )
        assert (spy["ticker"] == "SPY").all() and len(spy) == 3
        assert (qqq["ticker"] == "QQQ").all() and len(qqq) == 3

    def test_unknown_ticker_returns_empty(self, adapter: ParquetAdapter) -> None:
        adapter.write(_make_result(make_ohlcv_frame()), kind="ohlcv")
        out = adapter.read(
            kind="ohlcv",
            keys=["MISSING"],
            start=datetime(2026, 1, 1, tzinfo=UTC),
            end=datetime(2026, 1, 31, tzinfo=UTC),
        )
        assert out.empty


class TestMacroRoundtrip:
    def test_write_then_read_returns_same_row(self, adapter: ParquetAdapter) -> None:
        df = make_macro_frame()
        written = adapter.write(_make_result(df, source="fred"), kind="macro")
        assert written == 1

        out = adapter.read(
            kind="macro",
            keys=["CPIAUCSL"],
            start=datetime(2026, 1, 1, tzinfo=UTC),
            end=datetime(2026, 1, 31, tzinfo=UTC),
        )
        assert len(out) == 1
        assert out["indicator"].iloc[0] == "CPIAUCSL"
        assert out["value"].iloc[0] == 320.0


class TestWriteValidation:
    def test_missing_required_column_raises(self, adapter: ParquetAdapter) -> None:
        df = make_ohlcv_frame().drop(columns=["volume"])
        with pytest.raises(ValueError, match="missing columns"):
            adapter.write(_make_result(df), kind="ohlcv")

    def test_empty_frame_writes_zero_rows(self, adapter: ParquetAdapter) -> None:
        empty = make_ohlcv_frame().iloc[0:0]
        result = ConnectorResult(
            frame=empty,
            source="yfinance",
            fetched_at=datetime.now(UTC),
            rows=0,
        )
        assert adapter.write(result, kind="ohlcv") == 0
        assert adapter.list_partitions(kind="ohlcv", key="SPY") == []


def test_health_returns_root(adapter: ParquetAdapter) -> None:
    health = adapter.health()
    assert health.healthy is True
