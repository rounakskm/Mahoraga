"""Daily regime-conditional signal — promoted artifact -> DailySignal -> OrderIntent.

This is the REAL live-signal path for the Phase-5 paper window: it evaluates a
promoted strategy artifact (windows + detector thresholds, e.g.
`strategies/seed4-*.json`) against ~450 daily OHLCV bars and emits at most one
long/flat decision for the runner.

The pipeline mirrors the training evaluation exactly:

1. `training.regime.detector_features` computes the MESO inputs
   (`adx_14`, `realized_vol_pct_60`) from the bars (~312-bar warmup).
2. `RegimeConditionalStrategy.regimes_for` labels every bar with the artifact's
   OWN thresholds — NOT the MESO defaults. In particular the artifact's
   `vol_threshold` is used AS-IS even when it is on the legacy 0-1 scale
   (e.g. 0.4 against 0-100 percentile inputs): the strategy was trained AND
   vault-validated under its own thresholds, so self-consistency beats
   "correcting" the scale here — a 0.4 threshold simply means the candidate
   learned to treat (almost) every bar as high-vol.
3. Hold when the last close is above that regime's SMA window; else flat.

Pure functions, no I/O — the runner supplies bars/portfolio/price and owns all
broker interaction. The hard-limit firewall remains the real gate downstream.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from services.trader.execution.model import OrderIntent, Portfolio, Side
from services.trader.execution.stops import atr_stop
from services.trader.training.regime import detector_features
from services.trader.training.strategy_template import RegimeConditionalStrategy

# A position below 0.5% of equity counts as flat (dust from partial fills /
# rounding must not block a fresh entry or trigger a phantom exit).
_FLAT_EPS = 0.005

_DEFAULT_ENTRY_WEIGHT = 0.03


@dataclass(frozen=True)
class DailySignal:
    """One day's regime-conditional long/flat decision."""

    regime: str
    want_long: bool
    sma: float
    close: float
    confidence: float


def _clip(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def compute_signal(artifact: dict, bars: pd.DataFrame) -> DailySignal | None:
    """Evaluate a promoted artifact on daily OHLCV bars; None when undecidable.

    `bars` is a daily OHLCV frame (columns open/high/low/close/volume, bar-
    timestamp index, ~450 rows — the detector inputs need ~312 warmup bars).
    Returns None when the last bar's regime is `undefined` (warmup / NaN
    inputs) or the regime's SMA window has insufficient history.
    """
    strategy = RegimeConditionalStrategy(
        windows={label: int(window) for label, window in artifact["windows"].items()},
        adx_threshold=float(artifact.get("adx_threshold", 25.0)),
        # AS-IS by design — see the module docstring (self-consistency with the
        # thresholds the artifact was trained/vault-validated under).
        vol_threshold=float(artifact.get("vol_threshold", 40.0)),
    )

    adx, vol_pct = detector_features(bars)
    labels = strategy.regimes_for(adx, vol_pct)
    regime = str(labels.iloc[-1])
    if regime == "undefined" or regime not in strategy.windows:
        return None

    window = int(strategy.windows[regime])
    close = bars["close"].astype("float64")
    sma = close.rolling(window, min_periods=window).mean().iloc[-1]
    if pd.isna(sma):
        return None

    last_close = float(close.iloc[-1])
    last_adx = float(adx.iloc[-1])
    last_vol = float(vol_pct.iloc[-1])

    # Distance-to-threshold blend (meso.py style): crude but monotone in signal
    # clarity — the further the inputs sit from the detector's decision
    # boundaries, the cleaner the regime read. The firewall's 40% regime-
    # confidence floor is the real gate; this just feeds it honestly.
    confidence = _clip(
        (
            abs(last_adx - strategy.adx_threshold) / max(strategy.adx_threshold, 1.0)
            + abs(last_vol - strategy.vol_threshold) / max(strategy.vol_threshold, 1.0)
        )
        / 2.0,
        0.0,
        1.0,
    )

    return DailySignal(
        regime=regime,
        want_long=last_close > float(sma),
        sma=float(sma),
        close=last_close,
        confidence=confidence,
    )


def intent_from_signal(
    sig: DailySignal,
    portfolio: Portfolio,
    symbol: str,
    price: float,
    atr_value: float | None,
    *,
    entry_weight: float = _DEFAULT_ENTRY_WEIGHT,
) -> OrderIntent | None:
    """Translate a DailySignal + current book into at most one OrderIntent.

    Sign convention (from `sizing.size_order`, which RAISES on a mismatch):
    BUY carries a non-negative `target_weight`; SELL a non-positive one.

    - long signal + flat book  -> BUY entry at `entry_weight` (default 3%) with
      a 2xATR stop when `atr_value` is available.
    - flat signal + long book  -> SELL close. The weight is sized from the HELD
      qty at the CURRENT price (`-qty * price / equity`) rather than the marked
      position pct, so the sized order's qty equals the held qty exactly and
      the firewall classifies it as reducing (exits are never confidence- or
      blackout-gated — `reduces_exposure` short-circuits those checks).
    - already aligned          -> None.
    """
    held_pct = portfolio.position_pct(symbol)

    if sig.want_long and held_pct < _FLAT_EPS:
        return OrderIntent(
            ticker=symbol,
            side=Side.BUY,
            target_weight=abs(entry_weight),
            reason=(
                f"signal long in {sig.regime} "
                f"(close {sig.close:.2f} > sma {sig.sma:.2f})"
            ),
            regime_confidence=sig.confidence,
            stop_price=atr_stop(price, atr_value, "BUY") if atr_value is not None else None,
        )

    if not sig.want_long and held_pct > _FLAT_EPS:
        existing = portfolio.positions.get(symbol)
        if existing is None or portfolio.equity <= 0 or price <= 0:
            return None
        return OrderIntent(
            ticker=symbol,
            side=Side.SELL,
            target_weight=-(existing.qty * price) / portfolio.equity,
            reason=(
                f"signal exit in {sig.regime} "
                f"(close {sig.close:.2f} <= sma {sig.sma:.2f}) — close position"
            ),
            regime_confidence=sig.confidence,
            stop_price=None,
        )

    return None
