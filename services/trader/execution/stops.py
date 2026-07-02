"""ATR + 2xATR stop-loss utility.

`atr` wraps the Wilder-smoothed Average True Range already implemented as the
`atr_14` feature in `services.trader.features.volatility.ATR` (single source of
truth for the true-range math), adapting it from the `FeatureContext` boundary
to a plain OHLCV `DataFrame` so the execution layer can call it without the
feature-pipeline machinery.

`atr_stop` places a hard stop `mult * atr` away from entry — below for a long
(BUY), above for a short (SELL) — the Phase-5 "stop-loss on every trade,
max 2x ATR from entry" hard limit.

PIT: ATR at bar `i` depends only on bars `<= i` (Wilder EMA of the true range,
which uses the prior close). Future bars never affect a past value.

`side` is accepted as a plain string ("BUY"/"SELL") rather than importing the
`Side` enum from `execution.model`, which is a sibling Wave-1 task not yet on
this branch. When the firewall (T7) wires these together it can pass either an
enum's `.value` or the raw string; both round-trip through the case-insensitive
comparison here.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from services.trader.features.base import FeatureContext
from services.trader.features.volatility import ATR

_EPOCH = datetime(1970, 1, 1)


def atr(ohlcv: pd.DataFrame, window: int = 14) -> pd.Series:
    """Wilder's Average True Range over `ohlcv` (columns high/low/close).

    Reuses `features.volatility.ATR` so the true-range / smoothing formula lives
    in exactly one place. Returns a `pd.Series` aligned to a 0-based range index.
    """
    ctx = FeatureContext(ticker="", frame=ohlcv, asof=_EPOCH)
    return ATR(window=window).compute(ctx)


def atr_stop(entry: float, atr_value: float, side: str, mult: float = 2.0) -> float:
    """Stop price `mult * atr_value` away from `entry`.

    BUY (long)  -> entry - mult * atr_value  (stop below).
    SELL (short) -> entry + mult * atr_value  (stop above).
    """
    normalized = side.strip().upper()
    if normalized == "BUY":
        return entry - mult * atr_value
    if normalized == "SELL":
        return entry + mult * atr_value
    raise ValueError(f"side must be 'BUY' or 'SELL', got {side!r}")
