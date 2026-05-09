"""Wikipedia/HTML parsers + back-derivation for universe bootstrap scripts.

Operator-run scripts at `scripts/build_*_universe.py` invoke this module.
The functions here are pure (no HTTP, no filesystem) so unit tests can
inject fixture DataFrames.

See `docs/superpowers/specs/phase-1-foundation/universe-spec.md` §4.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


SP500_WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"


def parse_sp500_members(constituents: pd.DataFrame) -> set[str]:
    """Extract the current member tickers from Wikipedia's "Constituents" table.

    The table's symbol column has historically been "Symbol"; this function
    is tolerant to that exact spelling and to a "Ticker" alias.
    """
    col = _first_present_column(constituents, ["Symbol", "Ticker"])
    if col is None:
        raise ValueError(
            f"could not find Symbol/Ticker column in constituents; got {list(constituents.columns)}"
        )
    return {str(t).strip() for t in constituents[col].dropna() if str(t).strip()}


def parse_sp500_changes(changes: pd.DataFrame) -> list[dict[str, Any]]:
    """Extract `[{date, ticker, action}]` rows from Wikipedia's "Selected changes" table.

    Wikipedia uses a two-level header: top row is `("Date", "Added", "Removed", "Reason")`,
    second row carries the ticker/security under each side. After flattening,
    we expect columns like `Date_Date`, `Added_Ticker`, `Removed_Ticker`. The
    parser is tolerant to single-level headers too.
    """
    df = _flatten_columns(changes)

    date_col = _first_present_column(df, ["Date_Date", "Date"])
    added_col = _first_present_column(
        df, ["Added_Ticker", "Added_Symbol", "Added"]
    )
    removed_col = _first_present_column(
        df, ["Removed_Ticker", "Removed_Symbol", "Removed"]
    )
    if date_col is None:
        raise ValueError(f"changes table missing a Date column; got {list(df.columns)}")

    events: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        ev_date = _parse_date(row[date_col])
        if ev_date is None:
            continue
        if added_col is not None:
            added = _clean_ticker(row.get(added_col))
            if added:
                events.append({"date": ev_date, "ticker": added, "action": "add"})
        if removed_col is not None:
            removed = _clean_ticker(row.get(removed_col))
            if removed:
                events.append(
                    {"date": ev_date, "ticker": removed, "action": "remove"}
                )
    return events


def back_derive_seed(
    current_members: set[str],
    changes: list[dict[str, Any]],
    seed_date: date,
) -> set[str]:
    """Compute the membership at `seed_date` by walking changes back from today.

    For each change with `date > seed_date`:
    - an `add` event means the ticker was NOT in the universe before that date,
      so it is removed from the seed
    - a `remove` event means the ticker WAS in the universe before that date,
      so it is added to the seed
    """
    seed = set(current_members)
    for ev in changes:
        if ev["date"] <= seed_date:
            continue
        if ev["action"] == "add":
            seed.discard(ev["ticker"])
        else:  # remove
            seed.add(ev["ticker"])
    return seed


def filter_and_sort_events(
    changes: list[dict[str, Any]], seed_date: date
) -> list[dict[str, Any]]:
    """Keep only events strictly after `seed_date`, sorted by date."""
    forward = [ev for ev in changes if ev["date"] > seed_date]
    forward.sort(key=lambda e: (e["date"], e["action"], e["ticker"]))
    return forward


# --- internals -----------------------------------------------------------


def _first_present_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    for c in candidates:
        if c in df.columns:
            return c
    return None


def _flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(df.columns, pd.MultiIndex):
        return df.copy()
    return pd.DataFrame(df.values, columns=[_flatten_one(c) for c in df.columns])


def _flatten_one(tup: tuple) -> str:
    parts = [str(p) for p in tup if str(p) and not str(p).startswith("Unnamed")]
    if not parts:
        return "Unnamed"
    return "_".join(parts) if len(parts) > 1 else parts[0]


def _parse_date(value: Any) -> date | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        ts = pd.to_datetime(value, errors="raise")
    except (ValueError, TypeError):
        return None
    if pd.isna(ts):
        return None
    return ts.date()


def _clean_ticker(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    s = str(value).strip()
    if not s or s.lower() == "nan":
        return None
    # Wikipedia occasionally appends notes like "[1]"; keep just the leading word/symbol
    # whose chars are letters / digits / dots.
    out = []
    for ch in s:
        if ch.isalnum() or ch in ".-/":
            out.append(ch)
        else:
            break
    cleaned = "".join(out)
    return cleaned or None
