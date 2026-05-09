"""Tests for the universe loader + membership replay."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from textwrap import dedent

import pytest

from services.trader.universe import (
    Universe,
    UniverseAction,
    UniverseSchemaError,
)


@pytest.fixture
def repo_universe_root() -> Path:
    """Use the in-tree YAML files committed with this PR."""
    # __file__ -> services/trader/universe/tests/test_loader.py; root is repo/data/universe
    here = Path(__file__).resolve()
    repo_root = here.parents[4]
    return repo_root / "data" / "universe"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(content).lstrip())


# --- happy paths against the in-tree YAML --------------------------------


class TestRepoYAML:
    def test_load_succeeds(self, repo_universe_root: Path) -> None:
        u = Universe.load(repo_universe_root)
        assert "sp500" in u.known_universes()
        assert "russell1000" in u.known_universes()
        assert "etfs" in u.known_universes()

    def test_sp500_seed_members_at_seed_date(self, repo_universe_root: Path) -> None:
        u = Universe.load(repo_universe_root)
        members = u.members(name="sp500", asof=date(2014, 1, 1))
        assert "AAPL" in members
        assert "GE" in members
        assert "BABA" not in members  # added later

    def test_sp500_baba_added_after_ipo(self, repo_universe_root: Path) -> None:
        u = Universe.load(repo_universe_root)
        before = u.members(name="sp500", asof=date(2014, 9, 18))
        on_or_after = u.members(name="sp500", asof=date(2014, 9, 19))
        assert "BABA" not in before
        assert "BABA" in on_or_after

    def test_sp500_ge_removed_in_2018(self, repo_universe_root: Path) -> None:
        u = Universe.load(repo_universe_root)
        before = u.members(name="sp500", asof=date(2018, 6, 25))
        after = u.members(name="sp500", asof=date(2018, 6, 26))
        assert "GE" in before
        assert "GE" not in after
        assert "WBA" in after

    def test_etf_allowlist_filters_by_listed_at(self, repo_universe_root: Path) -> None:
        u = Universe.load(repo_universe_root)
        # XLC was listed 2018-06-19; check both sides
        before = {e.ticker for e in u.etf_allowlist(asof=date(2018, 6, 18))}
        after = {e.ticker for e in u.etf_allowlist(asof=date(2018, 6, 19))}
        assert "XLC" not in before
        assert "XLC" in after
        assert "SPY" in before  # always active

    def test_history_lists_only_target_ticker(self, repo_universe_root: Path) -> None:
        u = Universe.load(repo_universe_root)
        ge_history = u.history(name="sp500", ticker="GE")
        assert len(ge_history) == 1
        assert ge_history[0].action is UniverseAction.REMOVE


# --- schema-validation rejection tests via a synthetic root --------------


class TestSchemaValidation:
    def _root(self, tmp_path: Path) -> Path:
        return tmp_path / "uni"

    def test_seed_name_mismatch_rejected(self, tmp_path: Path) -> None:
        root = self._root(tmp_path)
        _write(
            root / "demo" / "seed.yaml",
            """
            name: wrong
            seed_date: 2020-01-01
            members: [AAPL]
            """,
        )
        with pytest.raises(UniverseSchemaError, match="disagrees"):
            Universe.load(root)

    def test_event_before_seed_date_rejected(self, tmp_path: Path) -> None:
        root = self._root(tmp_path)
        _write(
            root / "demo" / "seed.yaml",
            """
            name: demo
            seed_date: 2020-01-01
            members: [AAPL]
            """,
        )
        _write(
            root / "demo" / "events.yaml",
            """
            name: demo
            events:
              - {date: 2019-12-15, ticker: MSFT, action: add}
            """,
        )
        with pytest.raises(UniverseSchemaError, match="predates seed_date"):
            Universe.load(root)

    def test_unsorted_events_rejected(self, tmp_path: Path) -> None:
        root = self._root(tmp_path)
        _write(
            root / "demo" / "seed.yaml",
            """
            name: demo
            seed_date: 2020-01-01
            members: []
            """,
        )
        _write(
            root / "demo" / "events.yaml",
            """
            name: demo
            events:
              - {date: 2021-06-01, ticker: AAPL, action: add}
              - {date: 2020-06-01, ticker: MSFT, action: add}
            """,
        )
        with pytest.raises(UniverseSchemaError, match="precedes prior event"):
            Universe.load(root)

    def test_double_add_rejected(self, tmp_path: Path) -> None:
        root = self._root(tmp_path)
        _write(
            root / "demo" / "seed.yaml",
            """
            name: demo
            seed_date: 2020-01-01
            members: [AAPL]
            """,
        )
        _write(
            root / "demo" / "events.yaml",
            """
            name: demo
            events:
              - {date: 2020-06-01, ticker: AAPL, action: add}
            """,
        )
        with pytest.raises(UniverseSchemaError, match="already a member"):
            Universe.load(root)

    def test_remove_before_add_rejected(self, tmp_path: Path) -> None:
        root = self._root(tmp_path)
        _write(
            root / "demo" / "seed.yaml",
            """
            name: demo
            seed_date: 2020-01-01
            members: [AAPL]
            """,
        )
        _write(
            root / "demo" / "events.yaml",
            """
            name: demo
            events:
              - {date: 2020-06-01, ticker: MSFT, action: remove}
            """,
        )
        with pytest.raises(UniverseSchemaError, match="not a member"):
            Universe.load(root)

    def test_missing_root_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(UniverseSchemaError, match="does not exist"):
            Universe.load(tmp_path / "nonexistent")

    def test_unknown_universe_query_rejected(self, repo_universe_root: Path) -> None:
        u = Universe.load(repo_universe_root)
        with pytest.raises(UniverseSchemaError, match="unknown universe"):
            u.members(name="nasdaq100", asof=date(2020, 1, 1))

    def test_query_before_seed_date_rejected(self, repo_universe_root: Path) -> None:
        u = Universe.load(repo_universe_root)
        with pytest.raises(UniverseSchemaError, match="before"):
            u.members(name="sp500", asof=date(2010, 1, 1))


# --- ETF allowlist edge cases --------------------------------------------


class TestEtfBoundary:
    def test_delisted_filter(self, tmp_path: Path) -> None:
        root = tmp_path / "uni"
        _write(
            root / "etfs.yaml",
            """
            tickers:
              - {ticker: SPY, listed_at: 1993-01-22}
              - {ticker: ZZZD, listed_at: 2010-01-01, delisted_at: 2020-12-31}
            """,
        )
        u = Universe.load(root)
        active_during = {e.ticker for e in u.etf_allowlist(asof=date(2015, 6, 15))}
        active_after = {e.ticker for e in u.etf_allowlist(asof=date(2021, 1, 1))}
        assert "ZZZD" in active_during
        assert "ZZZD" not in active_after

    def test_duplicate_ticker_rejected(self, tmp_path: Path) -> None:
        root = tmp_path / "uni"
        _write(
            root / "etfs.yaml",
            """
            tickers:
              - {ticker: SPY, listed_at: 1993-01-22}
              - {ticker: SPY, listed_at: 1993-01-22}
            """,
        )
        with pytest.raises(UniverseSchemaError, match="duplicate"):
            Universe.load(root)

    def test_is_member_for_etfs(self, repo_universe_root: Path) -> None:
        u = Universe.load(repo_universe_root)
        assert u.is_member(name="etfs", asof=date(2025, 1, 1), ticker="SPY")
        assert not u.is_member(name="etfs", asof=date(1990, 1, 1), ticker="SPY")
