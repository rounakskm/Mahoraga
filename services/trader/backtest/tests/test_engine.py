"""Tests for the Backtest engine (P1.6 B2).

These tests stand up the engine against tmp-path-backed parquet
stores so they're fast unit tests, not integration tests. The full
end-to-end chain (Postgres included) lives in B3's integration test.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
import pytest

from services.trader.backtest import Backtest, BuyAndHold, FitnessReport
from services.trader.data.connectors.base import ConnectorResult
from services.trader.data.storage import ParquetAdapter
from services.trader.features.store import FeatureStore
from services.trader.features.trend import SMA
from services.trader.regime.store import RegimeStore, encode_inputs

_BAR_DATES = pd.bdate_range(start="2026-01-05", periods=10, tz="UTC")


def _ohlcv_frame(ticker: str, dates: list[pd.Timestamp]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ticker": [ticker] * len(dates),
            "bar_timestamp": dates,
            "open": [100.0 + i for i in range(len(dates))],
            "high": [101.0 + i for i in range(len(dates))],
            "low": [99.0 + i for i in range(len(dates))],
            "close": [100.0 + i for i in range(len(dates))],
            "adj_close": [100.0 + i for i in range(len(dates))],
            "volume": [1_000_000 + i for i in range(len(dates))],
            "source": ["test"] * len(dates),
            "fetched_at": [pd.Timestamp(datetime.now(UTC))] * len(dates),
            "revision_at": [pd.NaT] * len(dates),
        }
    )


def _seed_ohlcv(adapter: ParquetAdapter, universe: list[str]) -> None:
    for t in universe:
        adapter.write(
            ConnectorResult(
                frame=_ohlcv_frame(t, list(_BAR_DATES)),
                source="test",
                fetched_at=datetime.now(UTC),
                rows=len(_BAR_DATES),
            ),
            kind="ohlcv",
        )


def _seed_features(store: FeatureStore, universe: list[str]) -> None:
    feature = SMA(window=3)
    for ticker in universe:
        frame = pd.DataFrame(
            {
                "ticker": [ticker] * len(_BAR_DATES),
                "bar_timestamp": _BAR_DATES,
                "sma_3": [float("nan")] * 2 + [100.5 + i for i in range(len(_BAR_DATES) - 2)],
                "source": ["test"] * len(_BAR_DATES),
                "fetched_at": [pd.Timestamp(datetime.now(UTC))] * len(_BAR_DATES),
                "revision_at": [pd.NaT] * len(_BAR_DATES),
            }
        )
        store.write(frame, features=[feature])


def _seed_regime(store: RegimeStore) -> None:
    frame = pd.DataFrame(
        {
            "scope": ["universe"] * len(_BAR_DATES),
            "asof": _BAR_DATES,
            "meso_label": ["trending_low_vol"] * len(_BAR_DATES),
            "meso_conf": [0.9] * len(_BAR_DATES),
            "macro_label": ["bull"] * len(_BAR_DATES),
            "macro_conf": [0.8] * len(_BAR_DATES),
            "composite_conf": [0.8] * len(_BAR_DATES),
            "inputs": [encode_inputs({})] * len(_BAR_DATES),
            "source": ["regime-detector"] * len(_BAR_DATES),
            "fetched_at": [pd.Timestamp(datetime.now(UTC))] * len(_BAR_DATES),
        }
    )
    store.write(frame, lens_names=["meso", "macro"])


def _build_backtest(tmp_path: Path) -> tuple[Backtest, ParquetAdapter, FeatureStore, RegimeStore]:
    adapter = ParquetAdapter(tmp_path / "ohlcv", vault_cutoff_days=None)
    feature_store = FeatureStore(tmp_path / "features-root", vault_cutoff_days=None)
    regime_store = RegimeStore(tmp_path / "regime-root", vault_cutoff_days=None)
    bt = Backtest(
        feature_store=feature_store,
        regime_store=regime_store,
        ohlcv_adapter=adapter,
        initial_capital=1_000_000.0,
        commission_bps=1.0,
        slippage_bps=5.0,
        builtin_features=[SMA(window=3)],
    )
    return bt, adapter, feature_store, regime_store


class TestBuyAndHoldEndToEnd:
    def test_runs_to_completion(self, tmp_path: Path) -> None:
        bt, adapter, feature_store, regime_store = _build_backtest(tmp_path)
        universe = ["SPY", "QQQ"]
        _seed_ohlcv(adapter, universe)
        _seed_features(feature_store, universe)
        _seed_regime(regime_store)

        report = bt.run(
            strategy=BuyAndHold(),
            universe=universe,
            start=date(2026, 1, 5),
            end=_BAR_DATES[-1].date(),
        )
        assert isinstance(report, FitnessReport)
        assert report.strategy == "buy_and_hold"
        assert report.rejected_reason is None
        # Equal-weight 0.5 per ticker is above the 5% per-position cap,
        # so the engine clips both legs to 0.05 each — total exposure 10%.
        # On a rising synthetic ($100→$109), portfolio still gains some.
        assert report.total_return != 0.0

    def test_per_regime_stats_populated(self, tmp_path: Path) -> None:
        bt, adapter, feature_store, regime_store = _build_backtest(tmp_path)
        _seed_ohlcv(adapter, ["SPY"])
        _seed_features(feature_store, ["SPY"])
        _seed_regime(regime_store)
        report = bt.run(
            strategy=BuyAndHold(),
            universe=["SPY"],
            start=date(2026, 1, 5),
            end=_BAR_DATES[-1].date(),
        )
        # The fixture has a single MESO label "trending_low_vol"
        assert "trending_low_vol" in report.per_regime
        stats = report.per_regime["trending_low_vol"]
        assert "return" in stats
        assert "sharpe" in stats
        assert "n_bars" in stats


class TestPlaceholderGate:
    def test_strategy_requiring_placeholder_rejected(self, tmp_path: Path) -> None:
        from services.trader.backtest.base import Strategy
        from services.trader.features.sentiment import PlaceholderFeature

        class _BadStrategy(Strategy):
            name = "needs_sentiment"
            requires_features = ["sentiment_score"]
            allow_placeholder_features = False

            def generate_signals(
                self, *, feature_frame, regime_frame
            ):  # type: ignore[no-untyped-def]
                return pd.DataFrame(
                    columns=["ticker", "bar_timestamp", "target_weight"]
                )

        bt, _adapter, _fs, _rs = _build_backtest(tmp_path)
        # Replace the builtin features registry with the placeholder so
        # the gate can fire.
        bt.builtin_features = [PlaceholderFeature("sentiment_score")]

        report = bt.run(
            strategy=_BadStrategy(),
            universe=["SPY"],
            start=date(2026, 1, 5),
            end=_BAR_DATES[-1].date(),
        )
        assert report.rejected_reason is not None
        assert "sentiment_score" in report.rejected_reason
        # Rejected reports zero every metric
        assert report.total_return == 0.0
        assert report.num_trades == 0


class TestEmptyUniverse:
    def test_no_ohlcv_returns_empty_report(self, tmp_path: Path) -> None:
        bt, _adapter, _fs, _rs = _build_backtest(tmp_path)
        report = bt.run(
            strategy=BuyAndHold(),
            universe=["SPY"],
            start=date(2026, 1, 5),
            end=_BAR_DATES[-1].date(),
        )
        # No OHLCV → engine returns empty report (not rejected)
        assert report.rejected_reason is None
        assert report.total_return == 0.0
        assert report.num_trades == 0


class TestRiskLimitsApplied:
    def test_per_position_clip_active(self, tmp_path: Path) -> None:
        """BuyAndHold on a single ticker assigns 1.0 weight; the 5% clip
        must hold so total_return is bounded by 5% of the price move."""
        bt, adapter, feature_store, regime_store = _build_backtest(tmp_path)
        _seed_ohlcv(adapter, ["SPY"])
        _seed_features(feature_store, ["SPY"])
        _seed_regime(regime_store)
        report = bt.run(
            strategy=BuyAndHold(),
            universe=["SPY"],
            start=date(2026, 1, 5),
            end=_BAR_DATES[-1].date(),
        )
        # Price moves $100 → $109 over 10 bars (9% gain). Clipping to
        # 5% position size + 1-bar lag + cost ≈ <0.005 return.
        assert -0.01 < report.total_return < 0.01

    def test_low_confidence_halts_new_entries(self, tmp_path: Path) -> None:
        bt, adapter, feature_store, regime_store = _build_backtest(tmp_path)
        _seed_ohlcv(adapter, ["SPY"])
        _seed_features(feature_store, ["SPY"])
        # Seed regime with composite_conf below 0.40 — halt every bar
        frame = pd.DataFrame(
            {
                "scope": ["universe"] * len(_BAR_DATES),
                "asof": _BAR_DATES,
                "meso_label": ["undefined"] * len(_BAR_DATES),
                "meso_conf": [0.0] * len(_BAR_DATES),
                "macro_label": ["undefined"] * len(_BAR_DATES),
                "macro_conf": [0.0] * len(_BAR_DATES),
                "composite_conf": [0.0] * len(_BAR_DATES),
                "inputs": [encode_inputs({})] * len(_BAR_DATES),
                "source": ["regime-detector"] * len(_BAR_DATES),
                "fetched_at": [pd.Timestamp(datetime.now(UTC))] * len(_BAR_DATES),
            }
        )
        regime_store.write(frame, lens_names=["meso", "macro"])
        report = bt.run(
            strategy=BuyAndHold(),
            universe=["SPY"],
            start=date(2026, 1, 5),
            end=_BAR_DATES[-1].date(),
        )
        # All bars halted → zero held positions → zero P&L and trades
        assert report.total_return == 0.0
        assert report.num_trades == 0


class TestFitnessReportMath:
    def test_sharpe_zero_when_returns_constant(self, tmp_path: Path) -> None:
        from services.trader.backtest.engine import _sharpe

        # zero-variance series → sharpe 0
        s = pd.Series([0.001] * 100)
        assert _sharpe(s) == 0.0

    def test_sharpe_nonzero_for_varying_returns(self) -> None:
        from services.trader.backtest.engine import _sharpe

        s = pd.Series([0.01, -0.005, 0.008, -0.003, 0.012])
        # Result should be a positive finite number (mean > 0)
        result = _sharpe(s)
        assert result > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
