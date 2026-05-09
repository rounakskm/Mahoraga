"""Shared fixtures for storage tests."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from services.trader.data.storage import ParquetAdapter
from services.trader.data.storage.schema import OHLCV_ARROW_SCHEMA


@pytest.fixture
def adapter(tmp_path: Path) -> ParquetAdapter:
    return ParquetAdapter(tmp_path)


def make_ohlcv_frame(
    ticker: str = "SPY",
    start: datetime | None = None,
    bars: int = 5,
    *,
    revision_at: datetime | None = None,
    base_close: float = 100.0,
) -> pd.DataFrame:
    """Build a synthetic OHLCV frame matching the Mahoraga schema."""
    if start is None:
        start = datetime(2026, 1, 5, tzinfo=UTC)
    fetched = datetime(2026, 1, 5, 23, 0, tzinfo=UTC)
    rows = []
    for i in range(bars):
        ts = start + timedelta(days=i)
        rows.append(
            {
                "ticker": ticker,
                "bar_timestamp": ts,
                "open": base_close + i,
                "high": base_close + i + 1.0,
                "low":  base_close + i - 1.0,
                "close": base_close + i + 0.5,
                "volume": 1_000_000 + i,
                "adj_close": base_close + i + 0.4,
                "source": "yfinance",
                "fetched_at": fetched,
                "revision_at": revision_at,
            }
        )
    df = pd.DataFrame(rows)
    df["bar_timestamp"] = pd.to_datetime(df["bar_timestamp"], utc=True)
    df["fetched_at"] = pd.to_datetime(df["fetched_at"], utc=True)
    df["revision_at"] = pd.to_datetime(df["revision_at"], utc=True)
    # Ensure all schema columns are present and in order
    return df.loc[:, list(OHLCV_ARROW_SCHEMA.names)]


def make_macro_frame(
    indicator: str = "CPIAUCSL",
    reference: date | None = None,
    *,
    release: date | None = None,
    value: float = 320.0,
    source: str = "fred",
) -> pd.DataFrame:
    if reference is None:
        reference = date(2026, 1, 1)
    if release is None:
        release = date(2026, 2, 13)
    fetched = datetime(2026, 2, 13, 12, 0, tzinfo=UTC)
    df = pd.DataFrame(
        [
            {
                "indicator": indicator,
                "reference_date": reference,
                "as_of_release_date": release,
                "value": value,
                "unit": "Index",
                "source": source,
                "fetched_at": fetched,
            }
        ]
    )
    df["fetched_at"] = pd.to_datetime(df["fetched_at"], utc=True)
    return df
