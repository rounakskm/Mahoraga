"""Tests for the backtest ABC + dataclasses + placeholder-feature gate."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from services.trader.backtest.base import (
    FitnessReport,
    PlaceholderFeatureError,
    Strategy,
    validate_strategy,
)
from services.trader.backtest.strategies import BuyAndHold
from services.trader.features.base import Feature, FeatureContext


class _PlaceholderFeature(Feature):
    category = "sentiment"
    placeholder = True

    def __init__(self, name: str) -> None:
        self.name = name

    def required_history_bars(self) -> int:
        return 0

    def compute(self, ctx: FeatureContext) -> pd.Series:
        return pd.Series([0.0] * len(ctx.frame), dtype="float64")


class _RealFeature(Feature):
    category = "trend"
    placeholder = False
    name = "fake_real"

    def required_history_bars(self) -> int:
        return 0

    def compute(self, ctx: FeatureContext) -> pd.Series:
        return pd.Series([1.0] * len(ctx.frame), dtype="float64")


class _SentimentStrategy(Strategy):
    name = "sentiment_only"
    requires_features = ["sentiment_score"]
    allow_placeholder_features = False

    def generate_signals(
        self,
        *,
        feature_frame: pd.DataFrame,
        regime_frame: pd.DataFrame,
    ) -> pd.DataFrame:
        return feature_frame[["ticker", "bar_timestamp"]].assign(target_weight=0.0)


class _SentimentOptInStrategy(_SentimentStrategy):
    name = "sentiment_opted_in"
    allow_placeholder_features = True


class TestStrategyABC:
    def test_buy_and_hold_satisfies_contract(self) -> None:
        strategy = BuyAndHold()
        assert strategy.name == "buy_and_hold"
        assert strategy.requires_features == []
        assert strategy.allow_placeholder_features is False

    def test_abstract_class_cannot_instantiate(self) -> None:
        with pytest.raises(TypeError):
            Strategy()  # type: ignore[abstract]


class TestBuyAndHoldSignals:
    def test_equal_weight_two_tickers(self) -> None:
        feature_frame = pd.DataFrame(
            {
                "ticker": ["SPY", "QQQ", "SPY", "QQQ"],
                "bar_timestamp": pd.to_datetime(
                    ["2026-01-05", "2026-01-05", "2026-01-06", "2026-01-06"],
                    utc=True,
                ),
            }
        )
        regime = pd.DataFrame()
        signals = BuyAndHold().generate_signals(
            feature_frame=feature_frame, regime_frame=regime
        )
        assert len(signals) == 4
        assert (signals["target_weight"] == 0.5).all()

    def test_empty_universe_returns_empty(self) -> None:
        signals = BuyAndHold().generate_signals(
            feature_frame=pd.DataFrame(
                columns=["ticker", "bar_timestamp"]
            ),
            regime_frame=pd.DataFrame(),
        )
        assert signals.empty
        assert list(signals.columns) == ["ticker", "bar_timestamp", "target_weight"]


class TestFitnessReport:
    def test_dataclass_fields(self) -> None:
        report = FitnessReport(
            strategy="x",
            start=date(2026, 1, 1),
            end=date(2026, 12, 31),
            total_return=0.10,
            sharpe=1.5,
            max_drawdown=-0.05,
            num_trades=42,
            win_rate=0.6,
        )
        assert report.strategy == "x"
        assert report.rejected_reason is None
        assert report.per_regime == {}

    def test_frozen(self) -> None:
        report = FitnessReport(
            strategy="x",
            start=date(2026, 1, 1),
            end=date(2026, 12, 31),
            total_return=0.0,
            sharpe=0.0,
            max_drawdown=0.0,
            num_trades=0,
            win_rate=0.0,
        )
        with pytest.raises(AttributeError):
            report.total_return = 1.0  # type: ignore[misc]


class TestPlaceholderFeatureGate:
    def test_strategy_without_placeholder_passes(self) -> None:
        validate_strategy(
            BuyAndHold(),
            builtin_features=[_PlaceholderFeature("sentiment_score")],
        )

    def test_sentiment_strategy_without_opt_in_rejected(self) -> None:
        with pytest.raises(PlaceholderFeatureError) as exc_info:
            validate_strategy(
                _SentimentStrategy(),
                builtin_features=[_PlaceholderFeature("sentiment_score")],
            )
        assert "sentiment_score" in str(exc_info.value)

    def test_sentiment_strategy_with_opt_in_allowed(self) -> None:
        # Should NOT raise — strategy acknowledged the placeholder.
        validate_strategy(
            _SentimentOptInStrategy(),
            builtin_features=[_PlaceholderFeature("sentiment_score")],
        )

    def test_no_placeholder_features_means_no_gate(self) -> None:
        # Registry without any placeholder columns → gate is a no-op.
        validate_strategy(
            _SentimentStrategy(),
            builtin_features=[_RealFeature()],
        )

    def test_requires_only_real_features_passes(self) -> None:
        class _RealOnly(Strategy):
            name = "real_only"
            requires_features = ["fake_real"]

            def generate_signals(
                self, *, feature_frame, regime_frame
            ):  # type: ignore[no-untyped-def]
                return feature_frame

        validate_strategy(
            _RealOnly(),
            builtin_features=[
                _PlaceholderFeature("sentiment_score"),
                _RealFeature(),
            ],
        )
