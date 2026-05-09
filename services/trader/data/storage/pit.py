"""Point-in-time-correct view logic.

Functions here filter raw row sets to what would have been publicly available
at a given `asof` timestamp. The storage adapter calls them on every read.

This is the single chokepoint that prevents look-ahead bias across all of
Mahoraga. Strategy code never bypasses these functions; the `audit-xls`
reviewer prompt treats backtest output not produced via this read path as a
fatal failure.

Contract details: `docs/superpowers/specs/phase-1-foundation/data-foundation-spec.md` §7.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pandas as pd


def pit_view_ohlcv(
    df: pd.DataFrame,
    *,
    start: datetime,
    end: datetime,
    asof: datetime | None,
) -> pd.DataFrame:
    """Return the OHLCV rows that were public at `asof`, in `[start, end]`.

    For each `(ticker, bar_timestamp)` we keep at most one row — the latest
    `revision_at` value such that `revision_at <= asof`, treating
    `revision_at IS NULL` as "original publication, always public".
    """
    if df.empty:
        return df.copy()

    asof_ts = _to_utc(asof if asof is not None else datetime.now(UTC))
    start_ts = _to_utc(start)
    end_ts = _to_utc(end)

    # 1. window filter on bar_timestamp
    mask_window = (df["bar_timestamp"] >= start_ts) & (df["bar_timestamp"] <= end_ts)

    # 2. revision filter: NULL or revision_at <= asof
    mask_revision = df["revision_at"].isna() | (df["revision_at"] <= asof_ts)

    filtered = df.loc[mask_window & mask_revision].copy()
    if filtered.empty:
        return filtered

    # 3. for each (ticker, bar_timestamp) keep the latest revision_at
    #    null sorts before non-null so `keep='last'` picks the latest revision.
    sorted_df = filtered.sort_values("revision_at", na_position="first")
    return (
        sorted_df.drop_duplicates(subset=["ticker", "bar_timestamp"], keep="last")
        .sort_values(["ticker", "bar_timestamp"])
        .reset_index(drop=True)
    )


def pit_view_macro(
    df: pd.DataFrame,
    *,
    start: datetime,
    end: datetime,
    asof: datetime | None,
) -> pd.DataFrame:
    """Return the macro rows public at `asof`, with `reference_date ∈ [start, end]`.

    Multi-source semantics: if both FRED and BLS report the same indicator + reference
    date, both rows are returned (joiners pick the conservative one downstream — see
    spec §8). Within a source, only the latest pre-`asof` `as_of_release_date` survives
    per `(indicator, reference_date, source)`.
    """
    if df.empty:
        return df.copy()

    asof_d = _to_date(asof if asof is not None else datetime.now(UTC))
    start_d = _to_date(start)
    end_d = _to_date(end)

    mask_window = (df["reference_date"] >= start_d) & (df["reference_date"] <= end_d)
    mask_release = df["as_of_release_date"] <= asof_d

    filtered = df.loc[mask_window & mask_release].copy()
    if filtered.empty:
        return filtered

    sorted_df = filtered.sort_values("as_of_release_date")
    return (
        sorted_df.drop_duplicates(
            subset=["indicator", "reference_date", "source"], keep="last"
        )
        .sort_values(["indicator", "reference_date", "source"])
        .reset_index(drop=True)
    )


# --- internals -----------------------------------------------------------


def _to_utc(value: datetime | pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _to_date(value: datetime | pd.Timestamp | date) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, date):
        return value
    raise TypeError(f"expected datetime or date, got {type(value).__name__}")
