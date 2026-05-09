"""Tests for the Feature ABC + registry + schema helpers."""

from __future__ import annotations

import pandas as pd
import pyarrow as pa
import pytest

from services.trader.features.base import (
    BUILTIN_FEATURES,
    Feature,
    FeatureCategory,
    feature_frame_schema,
    features_in,
    register_feature,
)
from services.trader.features.tests.conftest import make_ctx, synthetic_ohlcv


class _DummyFeature(Feature):
    category: FeatureCategory = "trend"

    def __init__(self, name: str = "test_dummy") -> None:
        self.name = name

    def required_history_bars(self) -> int:
        return 1

    def compute(self, ctx) -> pd.Series:  # type: ignore[no-untyped-def]
        return ctx.frame["close"].astype("float64").reset_index(drop=True)


class TestRegistry:
    def test_register_appends(self) -> None:
        before = len(BUILTIN_FEATURES)
        register_feature(_DummyFeature("test_register_appends"))
        assert len(BUILTIN_FEATURES) == before + 1
        # Cleanup so we don't leak into other tests
        BUILTIN_FEATURES[:] = [f for f in BUILTIN_FEATURES if f.name != "test_register_appends"]

    def test_register_duplicate_rejected(self) -> None:
        register_feature(_DummyFeature("test_register_duplicate"))
        with pytest.raises(ValueError, match="already registered"):
            register_feature(_DummyFeature("test_register_duplicate"))
        BUILTIN_FEATURES[:] = [f for f in BUILTIN_FEATURES if f.name != "test_register_duplicate"]

    def test_features_in_filters_by_category(self) -> None:
        # The trend module registers ten features at import time
        from services.trader.features import trend  # noqa: F401  (side-effect registration)

        trend_features = features_in("trend")
        assert len(trend_features) >= 10
        assert all(f.category == "trend" for f in trend_features)


class TestFeatureContext:
    def test_context_carries_frame_and_asof(self) -> None:
        df = synthetic_ohlcv(bars=10)
        ctx = make_ctx(df)
        assert ctx.ticker == "TST"
        assert len(ctx.frame) == 10
        assert ctx.asof is not None


class TestFeatureFrameSchema:
    def test_includes_fixed_and_trailing_columns(self) -> None:
        feature = _DummyFeature("schema_test")
        schema = feature_frame_schema([feature])
        names = schema.names
        assert names[0] == "ticker"
        assert names[1] == "bar_timestamp"
        assert "schema_test" in names
        assert names[-3:] == ["source", "fetched_at", "revision_at"]

    def test_feature_columns_are_float64_nullable(self) -> None:
        schema = feature_frame_schema([_DummyFeature("f64_test")])
        field = schema.field("f64_test")
        assert field.type == pa.float64()
        assert field.nullable

    def test_ticker_and_bar_timestamp_not_null(self) -> None:
        schema = feature_frame_schema([_DummyFeature("nn_test")])
        assert not schema.field("ticker").nullable
        assert not schema.field("bar_timestamp").nullable


def test_dummy_feature_compute_returns_close() -> None:
    df = synthetic_ohlcv(bars=5)
    ctx = make_ctx(df)
    feature = _DummyFeature()
    series = feature.compute(ctx)
    assert len(series) == 5
    pd.testing.assert_series_equal(
        series.astype("float64").reset_index(drop=True),
        df["close"].astype("float64").reset_index(drop=True),
        check_names=False,
    )
