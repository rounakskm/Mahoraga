"""PIT-correctness tests for the storage adapter.

Covers `data-foundation-spec.md` §7 (read contract) and §8 (multi-source PIT
consistency).
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pandas as pd

from services.trader.data.connectors.base import ConnectorResult
from services.trader.data.storage import ParquetAdapter
from services.trader.data.storage.tests.conftest import make_macro_frame, make_ohlcv_frame


def _result(frame: pd.DataFrame, source: str = "fred") -> ConnectorResult:
    return ConnectorResult(
        frame=frame,
        source=source,
        fetched_at=datetime.now(UTC),
        rows=len(frame),
    )


class TestOhlcvPit:
    def test_revision_in_future_excluded_at_earlier_asof(
        self, adapter: ParquetAdapter
    ) -> None:
        # Original publication
        original = make_ohlcv_frame(
            ticker="SPY", start=datetime(2026, 1, 5, tzinfo=UTC), bars=2
        )
        adapter.write(_result(original, source="yfinance"), kind="ohlcv")

        # Restatement issued in Feb (a non-null revision_at)
        restated = make_ohlcv_frame(
            ticker="SPY",
            start=datetime(2026, 1, 5, tzinfo=UTC),
            bars=2,
            revision_at=datetime(2026, 2, 1, tzinfo=UTC),
            base_close=999.0,  # different value to detect which row is returned
        )
        adapter.write(_result(restated, source="yfinance"), kind="ohlcv")

        # asof = Jan 31: restatement not yet public -> originals returned
        out_before = adapter.read(
            kind="ohlcv",
            keys=["SPY"],
            start=datetime(2026, 1, 5, tzinfo=UTC),
            end=datetime(2026, 1, 8, tzinfo=UTC),
            asof=datetime(2026, 1, 31, tzinfo=UTC),
        )
        assert len(out_before) == 2
        assert out_before["close"].iloc[0] == 100.5  # original

        # asof = Feb 28: restatement is public -> restated values returned
        out_after = adapter.read(
            kind="ohlcv",
            keys=["SPY"],
            start=datetime(2026, 1, 5, tzinfo=UTC),
            end=datetime(2026, 1, 8, tzinfo=UTC),
            asof=datetime(2026, 2, 28, tzinfo=UTC),
        )
        assert out_after["close"].iloc[0] == 999.5

    def test_window_filter_excludes_outside_range(self, adapter: ParquetAdapter) -> None:
        df = make_ohlcv_frame(ticker="SPY", start=datetime(2026, 1, 5, tzinfo=UTC), bars=10)
        adapter.write(_result(df, source="yfinance"), kind="ohlcv")
        out = adapter.read(
            kind="ohlcv",
            keys=["SPY"],
            start=datetime(2026, 1, 5, tzinfo=UTC),
            end=datetime(2026, 1, 7, tzinfo=UTC),
        )
        assert len(out) == 3


class TestMacroPit:
    def test_release_date_filter(self, adapter: ParquetAdapter) -> None:
        # CPI for Jan 2026, released Feb 13
        df = make_macro_frame(
            indicator="CPIAUCSL",
            reference=date(2026, 1, 1),
            release=date(2026, 2, 13),
            value=320.5,
        )
        adapter.write(_result(df), kind="macro")

        # asof = Feb 12 (one day before release): row excluded
        out_before = adapter.read(
            kind="macro",
            keys=["CPIAUCSL"],
            start=datetime(2026, 1, 1, tzinfo=UTC),
            end=datetime(2026, 1, 31, tzinfo=UTC),
            asof=datetime(2026, 2, 12, tzinfo=UTC),
        )
        assert out_before.empty

        # asof = Feb 13 (release day): row included
        out_after = adapter.read(
            kind="macro",
            keys=["CPIAUCSL"],
            start=datetime(2026, 1, 1, tzinfo=UTC),
            end=datetime(2026, 1, 31, tzinfo=UTC),
            asof=datetime(2026, 2, 13, tzinfo=UTC),
        )
        assert len(out_after) == 1

    def test_within_source_restatement_picks_latest_pre_asof(
        self, adapter: ParquetAdapter
    ) -> None:
        # Original CPI for Jan 2026
        original = make_macro_frame(
            indicator="CPIAUCSL",
            reference=date(2026, 1, 1),
            release=date(2026, 2, 13),
            value=320.0,
        )
        adapter.write(_result(original), kind="macro")

        # Restatement (FRED frequently revises CPI)
        restated = make_macro_frame(
            indicator="CPIAUCSL",
            reference=date(2026, 1, 1),
            release=date(2026, 3, 13),
            value=321.5,
        )
        adapter.write(_result(restated), kind="macro")

        # asof = Feb 28: only original is public
        out_pre_revision = adapter.read(
            kind="macro",
            keys=["CPIAUCSL"],
            start=datetime(2026, 1, 1, tzinfo=UTC),
            end=datetime(2026, 1, 31, tzinfo=UTC),
            asof=datetime(2026, 2, 28, tzinfo=UTC),
        )
        assert len(out_pre_revision) == 1
        assert out_pre_revision["value"].iloc[0] == 320.0

        # asof = Mar 31: restatement is public, picks the latest pre-asof
        out_post_revision = adapter.read(
            kind="macro",
            keys=["CPIAUCSL"],
            start=datetime(2026, 1, 1, tzinfo=UTC),
            end=datetime(2026, 1, 31, tzinfo=UTC),
            asof=datetime(2026, 3, 31, tzinfo=UTC),
        )
        assert len(out_post_revision) == 1
        assert out_post_revision["value"].iloc[0] == 321.5


class TestMultiSourceConsistency:
    def test_keeps_both_sources(self, adapter: ParquetAdapter) -> None:
        # Same indicator + reference month from two providers
        fred = make_macro_frame(
            indicator="CPIAUCSL",
            reference=date(2026, 1, 1),
            release=date(2026, 2, 13),
            value=320.5,
            source="fred",
        )
        bls = make_macro_frame(
            indicator="CPIAUCSL",
            reference=date(2026, 1, 1),
            release=date(2026, 2, 7),  # BLS releases earlier than FRED's republish
            value=320.4,
            source="bls",
        )
        adapter.write(_result(fred), kind="macro")
        adapter.write(_result(bls), kind="macro")

        out = adapter.read(
            kind="macro",
            keys=["CPIAUCSL"],
            start=datetime(2026, 1, 1, tzinfo=UTC),
            end=datetime(2026, 1, 31, tzinfo=UTC),
            asof=datetime(2026, 2, 28, tzinfo=UTC),
        )
        # Both sources survive — joiners pick the conservative one downstream
        sources = set(out["source"])
        assert sources == {"fred", "bls"}, f"expected both sources kept; got {sources}"
