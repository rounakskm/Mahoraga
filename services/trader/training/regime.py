"""Real Phase-1 regime detection for the training loop.

Replaces `strategy_template.label_regimes` (the inline trend×vol proxy) with the
actual Phase-1 detector: compute the MESO lens's inputs (`adx_14` +
`realized_vol_pct_60`) from SPY OHLCV via the Phase-1 feature builtins, then label
each bar with the real `MesoLens`. This makes the regime-detection objective real —
the loop reads the same detector the rest of the system uses, and Layer 2+ can
mutate it. Warmup bars come back as the MESO `undefined` label (the strategy
naturally skips them).

ponytail: regime is detected on raw OHLC ranges (ADX/realized-vol); the strategy
times on adjusted close. Fine for Layer 1; revisit if it matters.
"""

from __future__ import annotations

import pandas as pd

from services.trader.features import BUILTIN_FEATURES
from services.trader.features.base import FeatureContext
from services.trader.regime.meso import MesoLens

_FEATS = {f.name: f for f in BUILTIN_FEATURES}
_LENS = MesoLens()


def meso_regimes(ohlcv: pd.DataFrame, ticker: str = "SPY") -> pd.Series:
    """Per-bar MESO regime label from OHLCV (index = bar timestamp).

    Labels are the 4 MESO quadrants (trending/ranging × low/high vol) that
    `RegimeConditionalStrategy` already keys on; warmup bars are ``undefined``.
    """
    ctx = FeatureContext(ticker=ticker, frame=ohlcv, asof=ohlcv.index[-1])
    # The Phase-1 feature compute returns positional (RangeIndex) series; re-attach
    # the bar-timestamp index so labels align to price bars downstream.
    feats = pd.DataFrame(
        {
            "adx_14": _FEATS["adx_14"].compute(ctx).to_numpy(),
            "realized_vol_pct_60": _FEATS["realized_vol_pct_60"].compute(ctx).to_numpy(),
        },
        index=ohlcv.index,
    )
    return feats.apply(
        lambda row: _LENS.classify(feature_row=row, macro_row=None).label, axis=1
    )


def detector_features(ohlcv: pd.DataFrame, ticker: str = "SPY") -> tuple[pd.Series, pd.Series]:
    """The MESO inputs (adx_14, realized_vol_pct_60) as bar-indexed series — for the
    learnable detector, where the candidate applies its OWN thresholds to these."""
    ctx = FeatureContext(ticker=ticker, frame=ohlcv, asof=ohlcv.index[-1])
    adx = pd.Series(_FEATS["adx_14"].compute(ctx).to_numpy(), index=ohlcv.index)
    vol = pd.Series(_FEATS["realized_vol_pct_60"].compute(ctx).to_numpy(), index=ohlcv.index)
    return adx, vol
