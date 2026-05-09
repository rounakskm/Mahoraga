"""End-to-end pipeline test: read OHLCV via ParquetAdapter, compute features, write."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
import pytest

from services.trader.data.connectors.base import ConnectorResult
from services.trader.data.storage import ParquetAdapter
from services.trader.features import FeaturePipeline
from services.trader.features.store import FeatureStore
from services.trader.features.tests.conftest import synthetic_ohlcv
from services.trader.features.trend import EMA, MACD, SMA, RegressionSlope


def _result(df: pd.DataFrame) -> ConnectorResult:
    return ConnectorResult(
        frame=df,
        source="test",
        fetched_at=datetime.now(UTC),
        rows=len(df),
    )


class TestPipelineSkeleton:
    @pytest.fixture
    def adapter(self, tmp_path: Path) -> ParquetAdapter:
        # Synthetic 2026 dates; opt out of vault for the round-trip
        return ParquetAdapter(tmp_path / "ohlcv", vault_cutoff_days=None)

    @pytest.fixture
    def store(self, tmp_path: Path) -> FeatureStore:
        return FeatureStore(tmp_path / "features", vault_cutoff_days=None)

    def test_single_ticker_writes_feature_columns(
        self, adapter: ParquetAdapter, store: FeatureStore
    ) -> None:
        df = synthetic_ohlcv(ticker="SPY", bars=60)
        adapter.write(_result(df), kind="ohlcv")

        features = [EMA(span=20), SMA(window=20), MACD(), RegressionSlope(window=20)]
        pipeline = FeaturePipeline(adapter=adapter, store=store, features=features)
        result = pipeline.compute(
            tickers=["SPY"],
            start=date(2026, 1, 5),
            end=date(2026, 3, 31),
        )

        assert result.rows_written == 60
        assert result.failures == []
        assert result.feature_columns == ["ema_20", "sma_20", "macd_12_26", "regression_slope_20"]
        # Each feature accumulates non-null values for bars after warmup
        for name, count in result.per_feature_non_null.items():
            assert count > 0, f"feature {name} produced zero non-null values"

        # Read back via the store. asof defaults to datetime.now(UTC) so it
        # is always >= fetched_at (which the pipeline sets to now() at
        # compute-time).
        out = store.read(
            keys=["SPY"],
            start=datetime(2026, 1, 5, tzinfo=UTC),
            end=datetime(2026, 3, 31, tzinfo=UTC),
            features=features,
        )
        assert len(out) == 60
        assert (out["ticker"] == "SPY").all()
        for f in features:
            assert f.name in out.columns

    def test_multi_ticker_segregates_partitions(
        self, adapter: ParquetAdapter, store: FeatureStore, tmp_path: Path
    ) -> None:
        for ticker in ("AAA", "BBB"):
            adapter.write(_result(synthetic_ohlcv(ticker=ticker, bars=30)), kind="ohlcv")

        features = [EMA(span=20)]
        pipeline = FeaturePipeline(adapter=adapter, store=store, features=features)
        pipeline.compute(
            tickers=["AAA", "BBB"],
            start=date(2026, 1, 5),
            end=date(2026, 3, 31),
        )

        # Partition files exist under both tickers
        aaa = list((tmp_path / "features" / "features" / "AAA").glob("*.parquet"))
        bbb = list((tmp_path / "features" / "features" / "BBB").glob("*.parquet"))
        assert len(aaa) == 1 and len(bbb) == 1

    def test_ticker_with_no_ohlcv_recorded_as_warning(
        self, adapter: ParquetAdapter, store: FeatureStore
    ) -> None:
        # Don't write any OHLCV
        features = [EMA(span=20)]
        pipeline = FeaturePipeline(adapter=adapter, store=store, features=features)
        result = pipeline.compute(
            tickers=["MISSING"],
            start=date(2026, 1, 5),
            end=date(2026, 3, 31),
        )
        # No rows written, no failures (missing data is a warning, not an error)
        assert result.rows_written == 0
        assert result.failures == []
        assert all(count == 0 for count in result.per_feature_non_null.values())

    def test_idempotent_recompute_does_not_grow_partitions(
        self, adapter: ParquetAdapter, store: FeatureStore
    ) -> None:
        df = synthetic_ohlcv(ticker="SPY", bars=30)
        adapter.write(_result(df), kind="ohlcv")
        features = [EMA(span=20)]
        pipeline = FeaturePipeline(adapter=adapter, store=store, features=features)
        pipeline.compute(tickers=["SPY"], start=date(2026, 1, 5), end=date(2026, 3, 31))
        first = store.read(
            keys=["SPY"],
            start=datetime(2026, 1, 5, tzinfo=UTC),
            end=datetime(2026, 3, 31, tzinfo=UTC),
            features=features,
        )
        # Re-run
        pipeline.compute(tickers=["SPY"], start=date(2026, 1, 5), end=date(2026, 3, 31))
        second = store.read(
            keys=["SPY"],
            start=datetime(2026, 1, 5, tzinfo=UTC),
            end=datetime(2026, 3, 31, tzinfo=UTC),
            features=features,
        )
        # Same number of rows — dedupe on (ticker, bar_timestamp) keeps latest
        assert len(first) == len(second)


class TestPipelineConstruction:
    def test_empty_features_rejected(self, tmp_path: Path) -> None:
        adapter = ParquetAdapter(tmp_path / "ohlcv", vault_cutoff_days=None)
        store = FeatureStore(tmp_path / "features", vault_cutoff_days=None)
        with pytest.raises(ValueError, match="at least one Feature"):
            FeaturePipeline(adapter=adapter, store=store, features=[])

    def test_default_features_uses_builtin_registry(self, tmp_path: Path) -> None:
        # Importing trend triggers BUILTIN_FEATURES registration (10 items)
        from services.trader.features import BUILTIN_FEATURES

        adapter = ParquetAdapter(tmp_path / "ohlcv", vault_cutoff_days=None)
        store = FeatureStore(tmp_path / "features", vault_cutoff_days=None)
        pipeline = FeaturePipeline(adapter=adapter, store=store)
        assert len(pipeline.features) == len(BUILTIN_FEATURES)
        assert any(f.name == "ema_20" for f in pipeline.features)
