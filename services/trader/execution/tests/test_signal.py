"""Tests for the daily regime-conditional signal (Phase-5 real-signal slice).

`compute_signal` is exercised on synthetic ~450-bar OHLCV frames whose LAST bar
is shaped deliberately (clear uptrend / clear breakdown / warmup-only), with the
artifact's detector thresholds derived from the frame's own computed features so
the expected regime label is unambiguous.

`intent_from_signal` is exercised against `sizing.size_order` with the REAL
production inputs (the "actually construct the Order" lesson): a SELL-close
intent must carry the sign convention `size_order` enforces, and the sized exit
qty must equal the held qty so the firewall classifies it as reducing.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from services.trader.execution.context import build_firewall_context
from services.trader.execution.firewall import HardLimitFirewall
from services.trader.execution.model import Order, OrderIntent, Portfolio, Position, Side
from services.trader.execution.signal import DailySignal, compute_signal, intent_from_signal
from services.trader.execution.sizing import size_order
from services.trader.execution.stops import atr_stop
from services.trader.training.regime import detector_features
from services.trader.training.strategy_template import REGIMES

# ---------------------------------------------------------------------------
# Synthetic OHLCV builders
# ---------------------------------------------------------------------------


def _bars(closes: np.ndarray) -> pd.DataFrame:
    """Daily OHLCV frame (bar-timestamp index) around a given close path."""
    idx = pd.date_range("2024-01-02", periods=len(closes), freq="B", tz="UTC")
    close = pd.Series(closes.astype("float64"), index=idx)
    return pd.DataFrame(
        {
            "open": close.shift(1).fillna(close.iloc[0]),
            "high": close * 1.005,
            "low": close * 0.995,
            "close": close,
            "volume": pd.Series(1_000_000.0, index=idx),
        }
    )


def _uptrend_bars(n: int = 450) -> pd.DataFrame:
    """Steady uptrend with small deterministic noise — last bar clearly trending."""
    rng = np.random.default_rng(7)
    ramp = np.linspace(100.0, 200.0, n)
    noise = rng.normal(0.0, 0.3, n).cumsum() * 0.05
    return _bars(ramp + noise)


def _breakdown_bars(n: int = 450) -> pd.DataFrame:
    """Rise then a sharp late decline — last close sits well below any long SMA."""
    rng = np.random.default_rng(11)
    up = np.linspace(100.0, 200.0, n - 100)
    down = np.linspace(200.0, 150.0, 100)
    path = np.concatenate([up, down])
    noise = rng.normal(0.0, 0.3, n).cumsum() * 0.05
    return _bars(path + noise)


def _artifact_for(bars: pd.DataFrame, windows: dict[str, int]) -> dict:
    """Artifact whose detector thresholds make the LAST bar trending_low_vol.

    Thresholds are derived from the frame's own computed (adx, vol_pct) so the
    expected label is exact: adx_threshold below the last ADX -> trending;
    vol_threshold above the last vol percentile -> low_vol.
    """
    adx, vol = detector_features(bars)
    last_adx = float(adx.iloc[-1])
    last_vol = float(vol.iloc[-1])
    assert not np.isnan(last_adx) and not np.isnan(last_vol)
    return {
        "windows": windows,
        "adx_threshold": max(last_adx - 5.0, 1.0),
        "vol_threshold": last_vol + 10.0,
    }


# ---------------------------------------------------------------------------
# compute_signal
# ---------------------------------------------------------------------------


def test_uptrend_last_bar_is_trending_low_vol_and_long() -> None:
    bars = _uptrend_bars()
    windows = {
        "trending_low_vol": 20,
        "trending_high_vol": 150,
        "ranging_low_vol": 70,
        "ranging_high_vol": 30,
    }
    sig = compute_signal(_artifact_for(bars, windows), bars)
    assert sig is not None
    assert sig.regime == "trending_low_vol"
    assert sig.want_long is True
    assert sig.close == pytest.approx(float(bars["close"].iloc[-1]))
    assert sig.close > sig.sma
    assert 0.0 <= sig.confidence <= 1.0


def test_breakdown_close_below_sma_is_not_long() -> None:
    bars = _breakdown_bars()
    # All windows 200 so want_long is regime-independent: the late 25% decline
    # leaves the last close far below the 200-bar SMA whatever the label is.
    adx, vol = detector_features(bars)
    artifact = {
        "windows": dict.fromkeys(REGIMES, 200),
        "adx_threshold": 25.0,
        "vol_threshold": float(vol.iloc[-1]) + 10.0,  # any low/high split works
    }
    sig = compute_signal(artifact, bars)
    assert sig is not None
    assert sig.regime in REGIMES
    assert sig.want_long is False
    assert sig.close < sig.sma


def test_warmup_only_frame_returns_none() -> None:
    # 100 bars < the ~312-bar realized_vol_pct_60 warmup -> undefined regime.
    bars = _uptrend_bars(100)
    artifact = {
        "windows": dict.fromkeys(REGIMES, 20),
        "adx_threshold": 25.0,
        "vol_threshold": 40.0,
    }
    assert compute_signal(artifact, bars) is None


def test_artifact_vol_threshold_used_as_is() -> None:
    # A legacy 0-1 scale threshold (0.4) against 0-100 percentile inputs must be
    # used verbatim: nearly every bar reads high-vol, exactly as in training.
    bars = _uptrend_bars()
    adx, _vol = detector_features(bars)
    artifact = {
        "windows": {
            "trending_low_vol": 200,
            "trending_high_vol": 20,
            "ranging_low_vol": 70,
            "ranging_high_vol": 20,
        },
        "adx_threshold": max(float(adx.iloc[-1]) - 5.0, 1.0),  # last bar trends
        "vol_threshold": 0.4,
    }
    sig = compute_signal(artifact, bars)
    assert sig is not None
    assert sig.regime == "trending_high_vol"


# ---------------------------------------------------------------------------
# intent_from_signal
# ---------------------------------------------------------------------------


def _signal(want_long: bool) -> DailySignal:
    return DailySignal(
        regime="trending_low_vol",
        want_long=want_long,
        sma=95.0,
        close=100.0,
        confidence=0.65,
    )


def _flat_portfolio(equity: float = 100_000.0) -> Portfolio:
    return Portfolio(equity=equity, cash=equity, buying_power=equity)


def _long_portfolio(qty: float = 30.0, mark: float = 100.0) -> Portfolio:
    pos = Position(
        ticker="SPY",
        qty=qty,
        avg_entry=mark,
        market_value=qty * mark,
        unrealized_pl=0.0,
        sector="ETF",
    )
    return Portfolio(
        equity=100_000.0, cash=97_000.0, buying_power=97_000.0, positions={"SPY": pos}
    )


def test_flat_book_long_signal_builds_buy_entry_with_stop() -> None:
    portfolio = _flat_portfolio()
    intent = intent_from_signal(_signal(True), portfolio, "SPY", 100.0, 2.0)
    assert intent is not None
    assert intent.side is Side.BUY
    assert intent.target_weight == pytest.approx(0.03)
    assert intent.stop_price == pytest.approx(atr_stop(100.0, 2.0, "BUY"))
    assert intent.regime_confidence == pytest.approx(0.65)
    assert "trending_low_vol" in intent.reason
    # Production input: the intent must size into a real Order.
    order = size_order(intent, portfolio, 100.0)
    assert isinstance(order, Order)
    assert order.qty == pytest.approx(30.0)


def test_flat_book_long_signal_without_atr_has_no_stop() -> None:
    intent = intent_from_signal(_signal(True), _flat_portfolio(), "SPY", 100.0, None)
    assert intent is not None
    assert intent.stop_price is None


def test_entry_weight_override() -> None:
    intent = intent_from_signal(
        _signal(True), _flat_portfolio(), "SPY", 100.0, 2.0, entry_weight=0.02
    )
    assert intent is not None
    assert intent.target_weight == pytest.approx(0.02)


def test_long_book_flat_signal_builds_sell_close_matching_sizing_convention() -> None:
    portfolio = _long_portfolio(qty=30.0, mark=100.0)
    intent = intent_from_signal(_signal(False), portfolio, "SPY", 100.0, 2.0)
    assert intent is not None
    assert intent.side is Side.SELL
    assert intent.target_weight < 0  # sizing.py: SELL requires non-positive weight
    assert "exit" in intent.reason
    assert intent.regime_confidence == pytest.approx(0.65)
    # Production input: sizes into a real Order (a sign mismatch would raise).
    order = size_order(intent, portfolio, 100.0)
    assert isinstance(order, Order)
    assert order.qty == pytest.approx(30.0)


def test_sell_close_qty_tracks_held_qty_when_price_moved() -> None:
    # Mark price 100 but the live quote is 90: the sized exit must still equal
    # the HELD qty (not overshoot into a short), so the firewall's
    # reduces_exposure classification holds and the exit is never gated.
    portfolio = _long_portfolio(qty=30.0, mark=100.0)
    intent = intent_from_signal(_signal(False), portfolio, "SPY", 90.0, None)
    assert intent is not None
    order = size_order(intent, portfolio, 90.0)
    assert isinstance(order, Order)
    assert order.qty == pytest.approx(30.0)
    ctx = build_firewall_context(
        intent, order, portfolio, now=pd.Timestamp("2026-07-06T15:00:00Z"), price=90.0
    )
    assert ctx.reduces_exposure is True
    # Exits are not confidence-gated: allowed even at 0 confidence via the
    # firewall's reduces_exposure short-circuit.
    verdict = HardLimitFirewall().check(intent, order, portfolio, ctx)
    assert verdict.allowed is True


def test_aligned_book_yields_no_intent() -> None:
    # Already long + long signal -> nothing to do.
    assert intent_from_signal(_signal(True), _long_portfolio(), "SPY", 100.0, 2.0) is None
    # Flat + flat signal -> nothing to do.
    assert intent_from_signal(_signal(False), _flat_portfolio(), "SPY", 100.0, 2.0) is None


def test_intent_is_order_intent_type() -> None:
    intent = intent_from_signal(_signal(True), _flat_portfolio(), "SPY", 100.0, 2.0)
    assert isinstance(intent, OrderIntent)
