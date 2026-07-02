"""Tests for the ATR + 2xATR stop-loss utility (`execution.stops`)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from services.trader.execution.stops import atr, atr_stop


def _make_ohlcv(n: int = 20, seed: int = 7) -> pd.DataFrame:
    """A small deterministic OHLCV frame with sane high >= low."""
    rng = np.random.default_rng(seed)
    close = 100.0 + np.cumsum(rng.normal(0.0, 1.0, size=n))
    high = close + rng.uniform(0.5, 2.0, size=n)
    low = close - rng.uniform(0.5, 2.0, size=n)
    return pd.DataFrame({"high": high, "low": low, "close": close})


def _expected_wilder_atr(ohlcv: pd.DataFrame, window: int) -> pd.Series:
    """Hand-rolled Wilder ATR, computed independently of the impl."""
    high = ohlcv["high"].astype("float64").reset_index(drop=True)
    low = ohlcv["low"].astype("float64").reset_index(drop=True)
    close = ohlcv["close"].astype("float64").reset_index(drop=True)
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1.0 / window, adjust=False).mean()


def test_atr_matches_hand_computed_wilder() -> None:
    ohlcv = _make_ohlcv()
    result = atr(ohlcv, window=14)
    expected = _expected_wilder_atr(ohlcv, window=14)
    pd.testing.assert_series_equal(
        result.reset_index(drop=True),
        expected.reset_index(drop=True),
        check_names=False,
    )


def test_atr_stop_buy_places_stop_below_entry() -> None:
    assert atr_stop(100.0, 2.0, "BUY") == 96.0


def test_atr_stop_sell_places_stop_above_entry() -> None:
    assert atr_stop(100.0, 2.0, "SELL") == 104.0


def test_atr_stop_custom_multiplier() -> None:
    assert atr_stop(100.0, 2.0, "BUY", mult=1.5) == 97.0
    assert atr_stop(100.0, 2.0, "SELL", mult=3.0) == 106.0


def test_atr_stop_side_is_case_insensitive() -> None:
    assert atr_stop(100.0, 2.0, "buy") == 96.0
    assert atr_stop(100.0, 2.0, "sell") == 104.0


def test_atr_is_point_in_time() -> None:
    """Altering bars after index i must not change ATR at index i."""
    ohlcv = _make_ohlcv()
    i = 10
    baseline = atr(ohlcv, window=14).iloc[i]

    perturbed = ohlcv.copy()
    perturbed.loc[i + 1 :, "high"] += 50.0
    perturbed.loc[i + 1 :, "low"] += 50.0
    perturbed.loc[i + 1 :, "close"] += 50.0

    assert atr(perturbed, window=14).iloc[i] == baseline
