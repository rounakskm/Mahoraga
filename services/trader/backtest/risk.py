"""Phase 1 hard-limit firewall stub (P1.6 B2).

Per `backtest-harness-spec.md` §4. The production firewall lives at
the execution boundary in Phase 7; this module exercises a subset of
the same guard-rails in the backtest harness so the project plan's
hard limits are tested end-to-end during training.

All functions are pure transforms — no I/O.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

import pandas as pd

# Defaults map 1:1 to the project plan's "Hard risk limits" table.
DEFAULT_MAX_POSITION = 0.05
DEFAULT_MAX_SECTOR = 0.20
DEFAULT_DAILY_LOSS_HALT = -0.02
DEFAULT_MONTHLY_DRAWDOWN_HALT = -0.10
DEFAULT_REGIME_CONFIDENCE_HALT = 0.40


def clip_positions(
    weights: pd.DataFrame,
    *,
    max_per_position: float = DEFAULT_MAX_POSITION,
) -> pd.DataFrame:
    """Clip every (ticker, bar) cell to ±`max_per_position`.

    `weights` is wide: index = bar_timestamp, columns = ticker.
    """
    if weights.empty:
        return weights
    return weights.clip(lower=-max_per_position, upper=max_per_position)


def clip_sectors(
    weights: pd.DataFrame,
    *,
    sector_map: Mapping[str, str] | None = None,
    max_per_sector: float = DEFAULT_MAX_SECTOR,
) -> pd.DataFrame:
    """Cap the per-sector aggregate weight to ±`max_per_sector`.

    Phase 1 ships with a stub `sector_map`: every ticker maps to
    `"unknown"`. Real GICS metadata lands in Phase 3.

    Scaling preserves sign: if a sector's aggregate exceeds the cap,
    every weight in that sector is scaled by `cap / |aggregate|`.
    """
    if weights.empty:
        return weights
    smap = dict(sector_map or {})
    out = weights.copy()
    # Group columns by sector
    by_sector: dict[str, list[str]] = {}
    for col in out.columns:
        sector = smap.get(col, "unknown")
        by_sector.setdefault(sector, []).append(col)

    for _sector, cols in by_sector.items():
        sub = out[cols]
        agg = sub.sum(axis=1)
        over = agg.abs() > max_per_sector
        if not over.any():
            continue
        scale = max_per_sector / agg.abs().where(over)
        scale = scale.where(over, 1.0).fillna(1.0)
        out.loc[:, cols] = sub.mul(scale, axis=0)
    return out


def halt_low_confidence(
    regime_frame: pd.DataFrame,
    *,
    threshold: float = DEFAULT_REGIME_CONFIDENCE_HALT,
) -> pd.Series:
    """Return a boolean series indexed by `asof` indicating halt-new-entries days.

    A day is halted when `composite_conf < threshold`. Phase-7
    firewall reads the same gate at the execution-tool boundary.
    """
    if regime_frame.empty:
        return pd.Series(dtype="bool")
    asof = pd.to_datetime(regime_frame["asof"], utc=True)
    mask = regime_frame["composite_conf"] < threshold
    return pd.Series(mask.values, index=asof, name="halt_low_confidence")


def halt_daily_loss(
    daily_returns: pd.Series,
    *,
    threshold: float = DEFAULT_DAILY_LOSS_HALT,
) -> pd.Series:
    """Halt new entries on the day following any day where return ≤ threshold.

    Returns a boolean series aligned to `daily_returns.index`; True
    at index t means "halt new entries on day t because day t-1's
    return was below the threshold".
    """
    if daily_returns.empty:
        return pd.Series(dtype="bool")
    prior_breach = (daily_returns.shift(1) <= threshold).fillna(False)
    return prior_breach.astype("bool")


def catastrophic_drawdown_halt(
    equity_curve: pd.Series,
    *,
    threshold: float = DEFAULT_MONTHLY_DRAWDOWN_HALT,
    window_days: int = 30,
) -> datetime | None:
    """Return the first timestamp at which trailing-30-day drawdown ≤ threshold.

    Drawdown computed as `equity / trailing_30d_peak - 1`. If the
    drawdown never breaches the threshold, returns `None`.
    """
    if equity_curve.empty:
        return None
    trailing_peak = equity_curve.rolling(window=window_days, min_periods=1).max()
    dd = equity_curve / trailing_peak - 1.0
    breaches = dd[dd <= threshold]
    if breaches.empty:
        return None
    return breaches.index[0].to_pydatetime()
