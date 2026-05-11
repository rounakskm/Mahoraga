"""Tests for the sentiment placeholder + pipeline coverage/manifest integration."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from services.trader.data.connectors.base import ConnectorResult
from services.trader.data.storage import ParquetAdapter
from services.trader.features import BUILTIN_FEATURES, FeaturePipeline
from services.trader.features.sentiment import PlaceholderFeature
from services.trader.features.store import FeatureStore
from services.trader.features.tests.conftest import make_ctx, synthetic_ohlcv
from services.trader.features.trend import EMA


def _result(df: pd.DataFrame) -> ConnectorResult:
    return ConnectorResult(
        frame=df,
        source="test",
        fetched_at=datetime.now(UTC),
        rows=len(df),
    )


# --- PlaceholderFeature semantics ---------------------------------------


class TestPlaceholderFeature:
    def test_returns_zero_per_bar(self) -> None:
        df = synthetic_ohlcv(bars=10)
        ctx = make_ctx(df)
        feature = PlaceholderFeature("sentiment_score")
        series = feature.compute(ctx).reset_index(drop=True)
        assert len(series) == 10
        assert (series == 0.0).all()

    def test_placeholder_flag_true(self) -> None:
        feature = PlaceholderFeature("sentiment_score")
        assert feature.placeholder is True
        assert feature.category == "sentiment"
        assert feature.required_history_bars() == 0

    def test_in_builtin_registry(self) -> None:
        names = [f.name for f in BUILTIN_FEATURES]
        assert "sentiment_score" in names
        sentiment = next(f for f in BUILTIN_FEATURES if f.name == "sentiment_score")
        assert sentiment.placeholder is True

    def test_only_sentiment_score_is_placeholder(self) -> None:
        placeholders = [f for f in BUILTIN_FEATURES if f.placeholder]
        assert [f.name for f in placeholders] == ["sentiment_score"]


# --- Pipeline manifest + audit integration ------------------------------


class TestPipelineManifest:
    def test_manifest_row_written_per_run(self, tmp_path: Path) -> None:
        adapter = ParquetAdapter(tmp_path / "ohlcv", vault_cutoff_days=None)
        store = FeatureStore(tmp_path / "features", vault_cutoff_days=None)
        adapter.write(_result(synthetic_ohlcv(ticker="SPY", bars=30)), kind="ohlcv")

        manifest_root = tmp_path / "manifests-root"
        pipeline = FeaturePipeline(
            adapter=adapter,
            store=store,
            features=[EMA(span=20), PlaceholderFeature("sentiment_score")],
            manifest_root=str(manifest_root),
        )
        pipeline.compute(
            tickers=["SPY"],
            start=date(2026, 1, 5),
            end=date(2026, 3, 31),
        )

        manifest_path = manifest_root / "manifests" / "ingest-runs.parquet"
        assert manifest_path.exists()
        df = pq.read_table(manifest_path).to_pandas()
        assert len(df) == 1
        assert df["source"].iloc[0] == "feature-pipeline"
        assert df["rows_written"].iloc[0] == 30

    def test_no_manifest_root_skips_manifest(self, tmp_path: Path) -> None:
        # Without manifest_root, the pipeline does not error and writes nothing.
        adapter = ParquetAdapter(tmp_path / "ohlcv", vault_cutoff_days=None)
        store = FeatureStore(tmp_path / "features", vault_cutoff_days=None)
        adapter.write(_result(synthetic_ohlcv(ticker="SPY", bars=30)), kind="ohlcv")
        pipeline = FeaturePipeline(adapter=adapter, store=store, features=[EMA(span=20)])
        result = pipeline.compute(
            tickers=["SPY"],
            start=date(2026, 1, 5),
            end=date(2026, 3, 31),
        )
        assert result.rows_written == 30


class _FakeAuditWriter:
    """Records vault_override calls for assertion in tests."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def is_enabled(self) -> bool:
        return True

    def write(self, *, actor, action, payload):  # type: ignore[no-untyped-def]
        self.calls.append({"actor": actor, "action": action, "payload": dict(payload)})
        return b"\x00" * 32


class TestPipelineAudit:
    def test_audit_row_written_per_run(self, tmp_path: Path) -> None:
        adapter = ParquetAdapter(tmp_path / "ohlcv", vault_cutoff_days=None)
        store = FeatureStore(tmp_path / "features", vault_cutoff_days=None)
        adapter.write(_result(synthetic_ohlcv(ticker="SPY", bars=30)), kind="ohlcv")

        writer = _FakeAuditWriter()
        pipeline = FeaturePipeline(
            adapter=adapter,
            store=store,
            features=[EMA(span=20)],
            audit_writer=writer,  # type: ignore[arg-type]
            audit_actor="test-feature-pipeline",
        )
        pipeline.compute(
            tickers=["SPY"],
            start=date(2026, 1, 5),
            end=date(2026, 3, 31),
        )
        assert len(writer.calls) == 1
        call = writer.calls[0]
        assert call["actor"] == "test-feature-pipeline"
        assert call["action"] == "compute"
        payload = call["payload"]
        assert payload["rows_written"] == 30
        assert payload["feature_count"] == 1
        assert payload["source"] == "feature-pipeline"


# --- Coverage report -----------------------------------------------------


class TestPipelineCoverage:
    def test_coverage_report_per_feature(self, tmp_path: Path) -> None:
        adapter = ParquetAdapter(tmp_path / "ohlcv", vault_cutoff_days=None)
        store = FeatureStore(tmp_path / "features", vault_cutoff_days=None)
        adapter.write(_result(synthetic_ohlcv(ticker="SPY", bars=30)), kind="ohlcv")

        # EMA-20 has warmup → first 19 bars are NaN → ~63% null rate
        pipeline = FeaturePipeline(
            adapter=adapter,
            store=store,
            features=[EMA(span=20), PlaceholderFeature("sentiment_score")],
        )
        result = pipeline.compute(
            tickers=["SPY"],
            start=date(2026, 1, 5),
            end=date(2026, 3, 31),
        )
        assert len(result.coverage) == 2
        by_name = {c.feature: c for c in result.coverage}

        # EMA warmup → null rate > 1% → coverage gate fails (passed=False)
        ema = by_name["ema_20"]
        assert ema.placeholder is False
        assert ema.null_rate_pct > 1.0
        assert ema.passed is False

        # Placeholder column has zero null rate by construction; passed=True
        sentiment = by_name["sentiment_score"]
        assert sentiment.placeholder is True
        assert sentiment.null_rate_pct == 0.0
        assert sentiment.passed is True

    def test_deliberate_gap_flagged(self, tmp_path: Path) -> None:
        adapter = ParquetAdapter(tmp_path / "ohlcv", vault_cutoff_days=None)
        store = FeatureStore(tmp_path / "features", vault_cutoff_days=None)
        adapter.write(_result(synthetic_ohlcv(ticker="SPY", bars=30)), kind="ohlcv")

        # Use SMA-10 so warmup is shorter — only the first 9 bars are null
        # (30% null rate). Still > 1% threshold but more obviously a coverage
        # warning than a constraint failure.
        from services.trader.features.trend import SMA

        pipeline = FeaturePipeline(
            adapter=adapter, store=store, features=[SMA(window=10)]
        )
        result = pipeline.compute(
            tickers=["SPY"],
            start=date(2026, 1, 5),
            end=date(2026, 3, 31),
        )
        sma = next(c for c in result.coverage if c.feature == "sma_10")
        assert sma.passed is False
        assert 25.0 < sma.null_rate_pct < 35.0  # ~30% NaN warmup

    def test_zero_warmup_feature_passes(self, tmp_path: Path) -> None:
        adapter = ParquetAdapter(tmp_path / "ohlcv", vault_cutoff_days=None)
        store = FeatureStore(tmp_path / "features", vault_cutoff_days=None)
        adapter.write(_result(synthetic_ohlcv(ticker="SPY", bars=30)), kind="ohlcv")

        # PlaceholderFeature has zero warmup and is marked placeholder.
        pipeline = FeaturePipeline(
            adapter=adapter,
            store=store,
            features=[PlaceholderFeature("sentiment_score")],
        )
        result = pipeline.compute(
            tickers=["SPY"],
            start=date(2026, 1, 5),
            end=date(2026, 3, 31),
        )
        sentiment = result.coverage[0]
        assert sentiment.passed is True
        assert sentiment.placeholder is True
