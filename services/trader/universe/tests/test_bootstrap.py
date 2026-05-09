"""Tests for the universe bootstrap parsers + back-derivation.

Pure-unit: feeds fixture DataFrames into the parser functions in
`services.trader.universe.bootstrap`. No HTTP, no filesystem.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from services.trader.universe.bootstrap import (
    back_derive_seed,
    filter_and_sort_events,
    parse_sp500_changes,
    parse_sp500_members,
)

# --- parse_sp500_members --------------------------------------------------


class TestParseMembers:
    def test_extracts_symbol_column(self) -> None:
        df = pd.DataFrame(
            {
                "Symbol":   ["AAPL", "MSFT", "GOOG"],
                "Security": ["Apple", "Microsoft", "Alphabet"],
            }
        )
        members = parse_sp500_members(df)
        assert members == {"AAPL", "MSFT", "GOOG"}

    def test_falls_back_to_ticker_alias(self) -> None:
        df = pd.DataFrame({"Ticker": ["SPY", "QQQ"]})
        members = parse_sp500_members(df)
        assert members == {"SPY", "QQQ"}

    def test_strips_whitespace_and_drops_empties(self) -> None:
        df = pd.DataFrame({"Symbol": [" AAPL ", "", "MSFT", None]})
        members = parse_sp500_members(df)
        assert members == {"AAPL", "MSFT"}

    def test_no_symbol_column_raises(self) -> None:
        df = pd.DataFrame({"Name": ["Apple"]})
        with pytest.raises(ValueError, match="Symbol/Ticker"):
            parse_sp500_members(df)


# --- parse_sp500_changes --------------------------------------------------


def _changes_table_with_multiindex() -> pd.DataFrame:
    """Mimics Wikipedia's two-level header on the changes table."""
    return pd.DataFrame(
        [
            ["September 19, 2014", "BABA", "",     "IPO entered S&P 500"],
            ["June 26, 2018",      "WBA",  "GE",   "GE replaced by WBA"],
            ["October 21, 2020",   "TSLA", "AAP",  "Auto Parts swap"],
        ],
        columns=pd.MultiIndex.from_tuples(
            [
                ("Date", "Date"),
                ("Added", "Ticker"),
                ("Removed", "Ticker"),
                ("Reason", ""),
            ]
        ),
    )


class TestParseChanges:
    def test_multiindex_table_parses_to_events(self) -> None:
        df = _changes_table_with_multiindex()
        events = parse_sp500_changes(df)
        # 1 add (BABA) + 1 add+1 remove on 2018-06-26 + 1 add+1 remove on 2020-10-21
        assert len(events) == 5
        kinds = {(e["date"], e["ticker"], e["action"]) for e in events}
        assert (date(2014, 9, 19),  "BABA", "add")    in kinds
        assert (date(2018, 6, 26),  "WBA",  "add")    in kinds
        assert (date(2018, 6, 26),  "GE",   "remove") in kinds
        assert (date(2020, 10, 21), "TSLA", "add")    in kinds
        assert (date(2020, 10, 21), "AAP",  "remove") in kinds

    def test_single_level_header_table(self) -> None:
        df = pd.DataFrame(
            [
                {"Date": "2018-06-26", "Added": "WBA", "Removed": "GE"},
            ]
        )
        events = parse_sp500_changes(df)
        actions = {(e["ticker"], e["action"]) for e in events}
        assert ("WBA", "add") in actions
        assert ("GE",  "remove") in actions

    def test_unparseable_dates_skipped(self) -> None:
        df = pd.DataFrame(
            [
                {"Date": "Recent",       "Added": "X", "Removed": ""},
                {"Date": "2019-04-01",   "Added": "", "Removed": "Y"},
            ]
        )
        events = parse_sp500_changes(df)
        # Only the parseable row produces events
        assert events == [{"date": date(2019, 4, 1), "ticker": "Y", "action": "remove"}]

    def test_no_date_column_raises(self) -> None:
        df = pd.DataFrame({"Foo": [1, 2]})
        with pytest.raises(ValueError, match="Date"):
            parse_sp500_changes(df)


# --- back_derive_seed -----------------------------------------------------


class TestBackDeriveSeed:
    def test_replays_changes_backward(self) -> None:
        # Today: {AAPL, BABA, WBA}
        # Events:
        #   2014-09-19  BABA add
        #   2018-06-26  GE remove + WBA add
        # seed_date = 2014-01-01 → seed should be {AAPL, GE} (BABA not yet, WBA not yet, GE still in)
        current = {"AAPL", "BABA", "WBA"}
        changes = [
            {"date": date(2014, 9, 19), "ticker": "BABA", "action": "add"},
            {"date": date(2018, 6, 26), "ticker": "WBA",  "action": "add"},
            {"date": date(2018, 6, 26), "ticker": "GE",   "action": "remove"},
        ]
        seed = back_derive_seed(current, changes, date(2014, 1, 1))
        assert seed == {"AAPL", "GE"}

    def test_changes_at_or_before_seed_kept_in_seed(self) -> None:
        # If a change happens ON the seed_date, treat it as already applied
        current = {"AAPL", "BABA"}
        changes = [
            {"date": date(2014, 1, 1), "ticker": "BABA", "action": "add"},
        ]
        seed = back_derive_seed(current, changes, date(2014, 1, 1))
        # Change on seed_date is "already applied" — BABA stays
        assert seed == {"AAPL", "BABA"}

    def test_empty_changes_returns_current(self) -> None:
        current = {"AAPL", "MSFT"}
        seed = back_derive_seed(current, [], date(2010, 1, 1))
        assert seed == current


# --- filter_and_sort_events ----------------------------------------------


class TestFilterAndSortEvents:
    def test_drops_pre_seed_events_and_sorts(self) -> None:
        events = [
            {"date": date(2014, 9, 19), "ticker": "BABA", "action": "add"},
            {"date": date(2018, 6, 26), "ticker": "WBA",  "action": "add"},
            {"date": date(2014, 1, 1),  "ticker": "GOOG", "action": "add"},  # filtered (≤ seed)
            {"date": date(2018, 6, 26), "ticker": "GE",   "action": "remove"},
        ]
        forward = filter_and_sort_events(events, date(2014, 1, 1))
        assert len(forward) == 3
        # Sorted by date, then action, then ticker
        assert forward[0]["ticker"] == "BABA"
        assert forward[1]["ticker"] == "WBA"
        assert forward[2]["ticker"] == "GE"
