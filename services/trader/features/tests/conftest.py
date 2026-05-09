"""Shared fixtures for feature tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd

from services.trader.features.base import FeatureContext


def synthetic_ohlcv(
    *,
    ticker: str = "TST",
    bars: int = 60,
    start: datetime | None = None,
    seed: int = 42,
) -> pd.DataFrame:
    """Build a deterministic OHLCV frame matching the storage schema."""
    rng = np.random.default_rng(seed)
    if start is None:
        start = datetime(2026, 1, 5, tzinfo=UTC)

    timestamps = [start + timedelta(days=i) for i in range(bars)]
    closes = 100.0 + rng.normal(0.0, 1.0, size=bars).cumsum()
    highs = closes + rng.uniform(0.5, 1.5, size=bars)
    lows = closes - rng.uniform(0.5, 1.5, size=bars)
    opens = closes - rng.normal(0.0, 0.5, size=bars)
    volumes = rng.integers(800_000, 1_200_000, size=bars).astype("int64")

    return pd.DataFrame(
        {
            "ticker":        ticker,
            "bar_timestamp": pd.to_datetime(timestamps, utc=True),
            "open":          opens.astype("float64"),
            "high":          highs.astype("float64"),
            "low":           lows.astype("float64"),
            "close":         closes.astype("float64"),
            "volume":        volumes,
            "adj_close":     closes.astype("float64"),
            "source":        "test",
            "fetched_at":    pd.Timestamp(start + timedelta(days=bars), tz="UTC"),
            "revision_at":   pd.NaT,
        }
    )


def make_ctx(
    df: pd.DataFrame,
    *,
    ticker: str = "TST",
    asof: datetime | None = None,
) -> FeatureContext:
    return FeatureContext(
        ticker=ticker,
        frame=df.reset_index(drop=True),
        asof=asof or datetime.now(UTC),
        macro_fetcher=None,
    )
