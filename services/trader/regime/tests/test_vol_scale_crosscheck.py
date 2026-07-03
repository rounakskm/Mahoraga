"""Cross-check: the real `realized_vol_pct_60` feature (0-100 scale) drives
non-degenerate MesoLens and TransitionPredictor outputs (review B4).

Before the fix, the MESO vol threshold (0.40) and the transition high-vol
threshold (0.75) sat on a 0-1 scale while the feature emits 0-100, so every
warmed-up bar read as high-vol. This test computes the feature from synthetic
OHLCV with a calm and a turbulent stretch, feeds the *actual* values through
both consumers, and asserts both low-vol and high-vol behavior occur.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd

from services.trader.features.base import FeatureContext
from services.trader.features.volatility import RealizedVolPercentile
from services.trader.intel.transition import TransitionPredictor
from services.trader.regime.meso import MesoLens

_BARS = 800
_HIGH_VOL_START = 500  # calm before, turbulent after


def _synthetic_ohlcv(*, bars: int = _BARS, seed: int = 11) -> pd.DataFrame:
    """Deterministic OHLCV: a long calm stretch then a turbulent one, so the
    trailing 252-bar percentile rank visits both tails after warmup."""
    rng = np.random.default_rng(seed)
    sigma = np.full(bars, 0.004)
    sigma[_HIGH_VOL_START:] = 0.03
    log_ret = rng.normal(0.0002, 1.0, size=bars) * sigma
    closes = 100.0 * np.exp(np.cumsum(log_ret))
    start = datetime(2020, 1, 2, tzinfo=UTC)
    return pd.DataFrame(
        {
            "ticker": "SPY",
            "bar_timestamp": pd.to_datetime(
                [start + timedelta(days=i) for i in range(bars)], utc=True
            ),
            "open": closes,
            "high": closes * 1.005,
            "low": closes * 0.995,
            "close": closes,
            "volume": np.full(bars, 1_000_000.0),
        }
    )


def _vol_pct_series() -> pd.Series:
    df = _synthetic_ohlcv()
    ctx = FeatureContext(
        ticker="SPY",
        frame=df,
        asof=df["bar_timestamp"].iloc[-1].to_pydatetime(),
        macro_fetcher=None,
    )
    return RealizedVolPercentile(window=60, lookback=252).compute(ctx)


def test_feature_emits_0_100_scale() -> None:
    vol_pct = _vol_pct_series().dropna()
    assert len(vol_pct) > 100
    assert vol_pct.max() > 1.0  # unmistakably 0-100, not 0-1
    assert vol_pct.max() <= 100.0
    assert vol_pct.min() >= 0.0


def test_meso_lens_produces_both_vol_axes_from_real_feature() -> None:
    vol_pct = _vol_pct_series()
    lens = MesoLens()
    labels = {
        lens.classify(
            feature_row=pd.Series({"adx_14": 30.0, "realized_vol_pct_60": v}),
            macro_row=None,
        ).label
        for v in vol_pct.dropna()
    }
    # Non-degenerate: both low-vol and high-vol quadrants occur across the series.
    assert "trending_low_vol" in labels
    assert "trending_high_vol" in labels


def test_transition_predictor_non_degenerate_on_real_feature() -> None:
    vol_pct = _vol_pct_series().dropna()
    predictor = TransitionPredictor(hindsight=None)

    def _predict(v: float, sentiment: float) -> float:
        row = pd.Series({"realized_vol_pct_60": v, "sentiment_score": sentiment})
        return predictor.predict(["trending_up"] * 3, row).prob

    # Turbulent-stretch bars reach a genuinely high percentile -> instability
    # (elevated prob) with negative sentiment; calm bars read stable. (The
    # rank is over the trailing 252 bars, so the peak sits just after the
    # calm->turbulent switch, not at the very end.)
    high_bar = float(vol_pct.max())  # most extreme bar of the turbulent stretch
    low_bar = float(vol_pct.min())  # calmest warmed-up bar
    assert high_bar >= 75.0
    assert low_bar < 75.0
    assert _predict(high_bar, -0.5) > 0.5  # elevated toward shock
    assert _predict(low_bar, 0.4) < 0.3  # stable, low transition prob
