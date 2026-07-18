"""Tests for the watchlist + sector map + multi-symbol signal/intent builders.

`signals_for` fans `compute_signal` over a per-symbol bars dict (skipping any
symbol whose last bar is undecidable). `intents_for` fans `intent_from_signal`
over the resulting signals. The intents are exercised against the REAL
production sizer (`size_order`) so the per-symbol sign/qty convention is proven,
not assumed — the "actually construct the Order" lesson applied per symbol.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from services.trader.execution.model import Order, Portfolio
from services.trader.execution.signal import DailySignal, compute_signal
from services.trader.execution.sizing import size_order
from services.trader.execution.watchlist import (
    DEFAULT_WATCHLIST,
    SECTOR_BY_TICKER,
    intents_for,
    sector_for,
    signals_for,
)
from services.trader.training.regime import detector_features

# ---------------------------------------------------------------------------
# Synthetic OHLCV builders (frame shape mirrors test_signal.py)
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


def _uptrend_bars(n: int = 450, seed: int = 7) -> pd.DataFrame:
    """Steady uptrend with small deterministic noise — last bar clearly trending."""
    rng = np.random.default_rng(seed)
    ramp = np.linspace(100.0, 200.0, n)
    noise = rng.normal(0.0, 0.3, n).cumsum() * 0.05
    return _bars(ramp + noise)


def _artifact_for(bars: pd.DataFrame, windows: dict[str, int]) -> dict:
    """Artifact whose thresholds make the LAST bar trending_low_vol + long."""
    adx, vol = detector_features(bars)
    last_adx = float(adx.iloc[-1])
    last_vol = float(vol.iloc[-1])
    return {
        "windows": windows,
        "adx_threshold": max(last_adx - 5.0, 1.0),
        "vol_threshold": last_vol + 10.0,
    }


_WINDOWS = {
    "trending_low_vol": 20,
    "trending_high_vol": 150,
    "ranging_low_vol": 70,
    "ranging_high_vol": 30,
}


# ---------------------------------------------------------------------------
# sector map
# ---------------------------------------------------------------------------


def test_default_watchlist_is_the_agreed_set() -> None:
    assert DEFAULT_WATCHLIST == ("SPY", "QQQ", "IWM", "XLK", "XLE", "XLF", "XLV")


def test_sector_for_known_ticker() -> None:
    assert sector_for("XLE") == "ENERGY"
    assert sector_for("XLK") == "TECH"
    assert sector_for("XLF") == "FINANCIALS"
    assert sector_for("XLV") == "HEALTHCARE"
    assert sector_for("SPY") == "BROAD"
    assert sector_for("QQQ") == "BROAD"
    assert sector_for("IWM") == "BROAD"


def test_sector_for_unknown_ticker_defaults() -> None:
    assert sector_for("TSLA") == "UNKNOWN"


def test_sector_map_covers_every_watchlist_symbol() -> None:
    for ticker in DEFAULT_WATCHLIST:
        assert ticker in SECTOR_BY_TICKER


# ---------------------------------------------------------------------------
# signals_for
# ---------------------------------------------------------------------------


def test_signals_for_returns_a_signal_per_decidable_symbol() -> None:
    bars = _uptrend_bars()
    artifact = _artifact_for(bars, _WINDOWS)
    bars_by_symbol = {"SPY": bars, "QQQ": _uptrend_bars(seed=11)}

    signals = signals_for(artifact, bars_by_symbol)

    assert set(signals) == {"SPY", "QQQ"}
    for sig in signals.values():
        assert isinstance(sig, DailySignal)
        assert sig.regime in _WINDOWS


def test_signals_for_skips_warmup_only_symbol() -> None:
    good = _uptrend_bars()
    artifact = _artifact_for(good, _WINDOWS)
    warmup = _uptrend_bars(100)  # < ~312-bar warmup -> compute_signal None
    assert compute_signal(artifact, warmup) is None

    signals = signals_for(artifact, {"SPY": good, "QQQ": warmup})

    assert set(signals) == {"SPY"}


def test_signals_for_empty_input_is_empty() -> None:
    assert signals_for(_artifact_for(_uptrend_bars(), _WINDOWS), {}) == {}


# ---------------------------------------------------------------------------
# intents_for
# ---------------------------------------------------------------------------


def _flat_portfolio(equity: float = 100_000.0) -> Portfolio:
    return Portfolio(equity=equity, cash=equity, buying_power=equity)


def _long_signal() -> DailySignal:
    return DailySignal(
        regime="trending_low_vol", want_long=True, sma=95.0, close=100.0, confidence=0.65
    )


def _flat_signal() -> DailySignal:
    return DailySignal(
        regime="trending_low_vol", want_long=False, sma=105.0, close=100.0, confidence=0.65
    )


def test_intents_for_builds_one_intent_per_actionable_signal() -> None:
    portfolio = _flat_portfolio()
    signals = {"SPY": _long_signal(), "QQQ": _long_signal()}
    prices = {"SPY": 100.0, "QQQ": 200.0}
    atrs: dict[str, float | None] = {"SPY": 2.0, "QQQ": None}

    intents = intents_for(signals, portfolio, prices, atrs)

    assert {i.ticker for i in intents} == {"SPY", "QQQ"}
    # Production-input check: every intent must size into a valid Order per symbol.
    for intent in intents:
        order = size_order(intent, portfolio, prices[intent.ticker])
        assert isinstance(order, Order)
        assert order.qty > 0
    # SPY carried an ATR -> a stop; QQQ had None -> no stop.
    by_ticker = {i.ticker: i for i in intents}
    assert by_ticker["SPY"].stop_price is not None
    assert by_ticker["QQQ"].stop_price is None


def test_intents_for_drops_non_actionable_signals() -> None:
    # Flat book + flat signal -> intent_from_signal returns None -> dropped.
    portfolio = _flat_portfolio()
    signals = {"SPY": _long_signal(), "QQQ": _flat_signal()}
    prices = {"SPY": 100.0, "QQQ": 200.0}
    atrs: dict[str, float | None] = {"SPY": 2.0, "QQQ": 2.0}

    intents = intents_for(signals, portfolio, prices, atrs)

    assert {i.ticker for i in intents} == {"SPY"}


def test_intents_for_honours_weight_override() -> None:
    portfolio = _flat_portfolio()
    signals = {"SPY": _long_signal()}
    intents = intents_for(signals, portfolio, {"SPY": 100.0}, {"SPY": 2.0}, weight=0.02)
    assert len(intents) == 1
    assert intents[0].target_weight == 0.02


def test_intents_for_empty_signals_is_empty() -> None:
    assert intents_for({}, _flat_portfolio(), {}, {}) == []
