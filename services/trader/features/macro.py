"""Macro-category features.

Ten features per `feature-pipeline-spec.md` §2:

- vix_level, vix_change_5d, vix_regime
- yield_2y, yield_10y, yield_2s10s, yield_curve_regime
- dxy_level, dxy_change_20d
- spy_qqq_rs_20d

These features rely on `ctx.macro_fetcher` (PIT-correct macro series from
the data foundation) and `ctx.ohlcv_fetcher` (cross-ticker OHLCV for the
SPY/QQQ relative-strength feature). Both are populated by the pipeline
when a macro adapter is wired in.

Regime fields are encoded as integers cast to float64 (parquet stores
float64; the encoding is documented in each feature's docstring).
"""

from __future__ import annotations

import logging
from typing import ClassVar

import numpy as np
import pandas as pd

from services.trader.features.base import (
    Feature,
    FeatureContext,
    register_feature,
)

logger = logging.getLogger(__name__)


# FRED series IDs used by these features.
VIX_SERIES_ID = "VIXCLS"
TREASURY_2Y_SERIES_ID = "DGS2"
TREASURY_10Y_SERIES_ID = "DGS10"
DXY_SERIES_ID = "DTWEXBGS"  # Trade-Weighted Broad Dollar Index, FRED

SPY_TICKER = "SPY"
QQQ_TICKER = "QQQ"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _bar_timestamps(ctx: FeatureContext) -> pd.Series:
    return pd.to_datetime(ctx.frame["bar_timestamp"], utc=True).reset_index(drop=True)


def _null_series(ctx: FeatureContext) -> pd.Series:
    return pd.Series([np.nan] * len(ctx.frame), dtype="float64")


def _join_macro_to_bars(
    macro: pd.DataFrame, bars: pd.Series
) -> pd.Series:
    """For each bar timestamp, return the latest macro value with
    `as_of_release_date <= bar_timestamp`.
    """
    if macro is None or macro.empty or len(bars) == 0:
        return pd.Series([np.nan] * len(bars), dtype="float64")

    m = macro.copy()
    # Convert + force microsecond precision so both sides of merge_asof match
    # bar_timestamp's `datetime64[us, UTC]` dtype. Without the explicit cast,
    # pandas 2.x infers `[s, UTC]` from `date` inputs and rejects the merge.
    m["as_of_release_dt"] = (
        pd.to_datetime(m["as_of_release_date"], utc=True).astype("datetime64[us, UTC]")
    )
    m = m.sort_values("as_of_release_dt").reset_index(drop=True)

    # Build the left side with tz-aware microsecond-precision bar_timestamp.
    bars_df = pd.DataFrame(
        {"bar_timestamp": pd.to_datetime(bars, utc=True).astype("datetime64[us, UTC]")}
    )
    bars_df = bars_df.sort_values("bar_timestamp").reset_index()
    merged = pd.merge_asof(
        bars_df,
        m[["as_of_release_dt", "value"]],
        left_on="bar_timestamp",
        right_on="as_of_release_dt",
        direction="backward",
        allow_exact_matches=True,
    )
    # Restore original bars order
    merged = merged.sort_values("index").reset_index(drop=True)
    return merged["value"].astype("float64").reset_index(drop=True)


def _fetch_macro(ctx: FeatureContext, series_id: str) -> pd.DataFrame:
    if ctx.macro_fetcher is None:
        return pd.DataFrame()
    return ctx.macro_fetcher(series_id)


def _fetch_ohlcv(ctx: FeatureContext, ticker: str) -> pd.DataFrame:
    if ctx.ohlcv_fetcher is None:
        return pd.DataFrame()
    return ctx.ohlcv_fetcher(ticker)


# ---------------------------------------------------------------------------
# VIX features
# ---------------------------------------------------------------------------


class VIXLevel(Feature):
    category: ClassVar[str] = "macro"
    name: ClassVar[str] = "vix_level"

    def required_history_bars(self) -> int:
        return 1

    def compute(self, ctx: FeatureContext) -> pd.Series:
        macro = _fetch_macro(ctx, VIX_SERIES_ID)
        return _join_macro_to_bars(macro, _bar_timestamps(ctx))


class VIXChange5D(Feature):
    """5-bar change in VIX level (absolute, in vol points)."""

    category: ClassVar[str] = "macro"
    name: ClassVar[str] = "vix_change_5d"

    def required_history_bars(self) -> int:
        return 6

    def compute(self, ctx: FeatureContext) -> pd.Series:
        level = VIXLevel().compute(ctx)
        return level - level.shift(5)


class VIXRegime(Feature):
    """VIX regime encoded as float64 (0/1/2/3).

    0 = calm   (<15)
    1 = normal (15..25)
    2 = elevated (25..40)
    3 = crisis (>=40)
    """

    category: ClassVar[str] = "macro"
    name: ClassVar[str] = "vix_regime"

    def required_history_bars(self) -> int:
        return 1

    def compute(self, ctx: FeatureContext) -> pd.Series:
        level = VIXLevel().compute(ctx)
        regime = pd.Series([np.nan] * len(level), dtype="float64")
        regime[level < 15.0] = 0.0
        regime[(level >= 15.0) & (level < 25.0)] = 1.0
        regime[(level >= 25.0) & (level < 40.0)] = 2.0
        regime[level >= 40.0] = 3.0
        return regime


# ---------------------------------------------------------------------------
# Treasury yields
# ---------------------------------------------------------------------------


class Yield2Y(Feature):
    category: ClassVar[str] = "macro"
    name: ClassVar[str] = "yield_2y"

    def required_history_bars(self) -> int:
        return 1

    def compute(self, ctx: FeatureContext) -> pd.Series:
        return _join_macro_to_bars(_fetch_macro(ctx, TREASURY_2Y_SERIES_ID), _bar_timestamps(ctx))


class Yield10Y(Feature):
    category: ClassVar[str] = "macro"
    name: ClassVar[str] = "yield_10y"

    def required_history_bars(self) -> int:
        return 1

    def compute(self, ctx: FeatureContext) -> pd.Series:
        return _join_macro_to_bars(_fetch_macro(ctx, TREASURY_10Y_SERIES_ID), _bar_timestamps(ctx))


class Yield2s10s(Feature):
    """2s10s curve slope: 10y - 2y, in percentage points (FRED quotes in percent)."""

    category: ClassVar[str] = "macro"
    name: ClassVar[str] = "yield_2s10s"

    def required_history_bars(self) -> int:
        return 1

    def compute(self, ctx: FeatureContext) -> pd.Series:
        y10 = Yield10Y().compute(ctx)
        y2 = Yield2Y().compute(ctx)
        return y10 - y2


class YieldCurveRegime(Feature):
    """Curve regime encoded as float64.

    0 = normal   (2s10s > 0.5)
    1 = flat     (0 <= 2s10s <= 0.5)
    2 = inverted (2s10s < 0)

    The full taxonomy in `feature-pipeline-spec.md` §2 also lists a
    `humped` shape, but detecting that reliably needs the full curve;
    Phase 1 ships the three-regime variant and defers the humped case to
    a future spec revision.
    """

    category: ClassVar[str] = "macro"
    name: ClassVar[str] = "yield_curve_regime"

    def required_history_bars(self) -> int:
        return 1

    def compute(self, ctx: FeatureContext) -> pd.Series:
        slope = Yield2s10s().compute(ctx)
        regime = pd.Series([np.nan] * len(slope), dtype="float64")
        regime[slope > 0.5] = 0.0
        regime[(slope >= 0.0) & (slope <= 0.5)] = 1.0
        regime[slope < 0.0] = 2.0
        return regime


# ---------------------------------------------------------------------------
# DXY (Trade-Weighted Broad Dollar Index)
# ---------------------------------------------------------------------------


class DXYLevel(Feature):
    category: ClassVar[str] = "macro"
    name: ClassVar[str] = "dxy_level"

    def required_history_bars(self) -> int:
        return 1

    def compute(self, ctx: FeatureContext) -> pd.Series:
        return _join_macro_to_bars(_fetch_macro(ctx, DXY_SERIES_ID), _bar_timestamps(ctx))


class DXYChange20D(Feature):
    """20-bar relative change in DXY: `(dxy[t] - dxy[t-20]) / dxy[t-20]`."""

    category: ClassVar[str] = "macro"
    name: ClassVar[str] = "dxy_change_20d"

    def required_history_bars(self) -> int:
        return 21

    def compute(self, ctx: FeatureContext) -> pd.Series:
        level = DXYLevel().compute(ctx)
        prev = level.shift(20)
        return (level - prev) / prev.replace(0.0, pd.NA)


# ---------------------------------------------------------------------------
# SPY/QQQ relative strength (cross-ticker feature)
# ---------------------------------------------------------------------------


class SpyQqqRS20D(Feature):
    """20-bar relative strength: `(QQQ / SPY) / (QQQ / SPY).shift(20)`.

    Values > 1 mean QQQ has outperformed SPY over the last 20 bars; < 1 means
    SPY has outperformed. Cross-ticker; the same value is broadcast to every
    bar of every ticker in a run.
    """

    category: ClassVar[str] = "macro"
    name: ClassVar[str] = "spy_qqq_rs_20d"

    def required_history_bars(self) -> int:
        return 21

    def compute(self, ctx: FeatureContext) -> pd.Series:
        spy = _fetch_ohlcv(ctx, SPY_TICKER)
        qqq = _fetch_ohlcv(ctx, QQQ_TICKER)
        if spy.empty or qqq.empty:
            return _null_series(ctx)

        bars = _bar_timestamps(ctx)
        spy_close = _join_ohlcv_to_bars(spy, bars)
        qqq_close = _join_ohlcv_to_bars(qqq, bars)
        ratio = qqq_close / spy_close.replace(0.0, pd.NA)
        return ratio / ratio.shift(20)


def _join_ohlcv_to_bars(ohlcv: pd.DataFrame, bars: pd.Series) -> pd.Series:
    """Align OHLCV close to `bars` timestamps via backward-direction merge_asof."""
    if ohlcv is None or ohlcv.empty or len(bars) == 0:
        return pd.Series([np.nan] * len(bars), dtype="float64")

    o = ohlcv.sort_values("bar_timestamp").reset_index(drop=True).copy()
    # Force microsecond precision on both sides so pd.merge_asof is happy
    # regardless of how the OHLCV producer constructed its timestamps.
    o["bar_timestamp"] = pd.to_datetime(o["bar_timestamp"], utc=True).astype(
        "datetime64[us, UTC]"
    )
    bars_df = pd.DataFrame(
        {"bar_timestamp": pd.to_datetime(bars, utc=True).astype("datetime64[us, UTC]")}
    ).reset_index()
    bars_df = bars_df.sort_values("bar_timestamp")
    merged = pd.merge_asof(
        bars_df,
        o[["bar_timestamp", "close"]].rename(columns={"bar_timestamp": "ohlcv_bar"}),
        left_on="bar_timestamp",
        right_on="ohlcv_bar",
        direction="backward",
        allow_exact_matches=True,
    )
    merged = merged.sort_values("index").reset_index(drop=True)
    return merged["close"].astype("float64").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


_REGISTERED_MACRO = [
    register_feature(VIXLevel()),
    register_feature(VIXChange5D()),
    register_feature(VIXRegime()),
    register_feature(Yield2Y()),
    register_feature(Yield10Y()),
    register_feature(Yield2s10s()),
    register_feature(YieldCurveRegime()),
    register_feature(DXYLevel()),
    register_feature(DXYChange20D()),
    register_feature(SpyQqqRS20D()),
]
"""Side-effect registration; importing this module fills BUILTIN_FEATURES."""
