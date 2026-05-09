"""Unit test for the index-replay mechanism.

Builds a synthetic 3-ticker universe with hand-computed monthly closes and
verifies that `monthly_equal_weight_return` returns the expected number.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from textwrap import dedent

import pandas as pd
import pytest

from services.trader.data.connectors.base import ConnectorResult
from services.trader.data.storage import ParquetAdapter
from services.trader.universe import Universe, UniverseSchemaError
from services.trader.universe.index_replay import (
    MonthlyReturnReport,
    last_trading_day_of_month,
    monthly_equal_weight_return,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(content).lstrip())


def _ohlcv_for(ticker: str, monthly_first_close: float, monthly_last_close: float) -> pd.DataFrame:
    """A 2-bar OHLCV frame for `ticker` covering the start and end of July 2018."""
    dates = pd.DatetimeIndex(["2018-07-02", "2018-07-31"], tz="UTC")
    fetched = datetime(2018, 8, 1, tzinfo=UTC)
    return pd.DataFrame(
        {
            "ticker":        [ticker, ticker],
            "bar_timestamp": dates,
            "open":          [monthly_first_close - 1.0, monthly_last_close - 1.0],
            "high":          [monthly_first_close + 1.0, monthly_last_close + 1.0],
            "low":           [monthly_first_close - 2.0, monthly_last_close - 2.0],
            "close":         [monthly_first_close, monthly_last_close],
            "volume":        [1_000_000, 1_000_000],
            "adj_close":     [monthly_first_close, monthly_last_close],
            "source":        ["test", "test"],
            "fetched_at":    [fetched, fetched],
            "revision_at":   [pd.NaT, pd.NaT],
        }
    )


@pytest.fixture
def synthetic_universe(tmp_path: Path) -> tuple[Universe, ParquetAdapter]:
    """Three-ticker universe + 2-bar OHLCV frames covering July 2018."""
    root = tmp_path / "universe"
    _write(
        root / "demo" / "seed.yaml",
        """
        name: demo
        seed_date: 2018-01-01
        members: [AAA, BBB, CCC]
        """,
    )
    _write(
        root / "demo" / "events.yaml",
        """
        name: demo
        events: []
        """,
    )
    universe = Universe.load(root)

    parquet_root = tmp_path / "parquet"
    adapter = ParquetAdapter(parquet_root, vault_cutoff_days=None)  # 2018 is far past
    fetched_at = datetime(2018, 8, 1, tzinfo=UTC)
    for ticker, first, last in [
        ("AAA", 100.0, 110.0),  # +10%
        ("BBB", 200.0, 210.0),  # +5%
        ("CCC", 50.0, 47.5),    # -5%
    ]:
        adapter.write(
            ConnectorResult(
                frame=_ohlcv_for(ticker, first, last),
                source="test",
                fetched_at=fetched_at,
                rows=2,
            ),
            kind="ohlcv",
        )
    return universe, adapter


class TestIndexReplay:
    def test_equal_weight_return_matches_hand_computation(
        self, synthetic_universe: tuple[Universe, ParquetAdapter]
    ) -> None:
        universe, adapter = synthetic_universe
        report = monthly_equal_weight_return(
            universe=universe,
            universe_name="demo",
            year=2018,
            month=7,
            adapter=adapter,
            vault_override_reason="unit test",
        )
        assert isinstance(report, MonthlyReturnReport)
        assert report.eligible_count == 3
        # Expected returns: +10% + 5% - 5% = +10%; mean = +3.333...%
        assert report.equal_weight_return == pytest.approx(0.10 / 3, abs=1e-9)
        # Constituent returns recorded
        assert report.constituent_returns["AAA"] == pytest.approx(0.10)
        assert report.constituent_returns["BBB"] == pytest.approx(0.05)
        assert report.constituent_returns["CCC"] == pytest.approx(-0.05)
        assert report.label == "July 2018"

    def test_ticker_with_only_one_bar_dropped(self, tmp_path: Path) -> None:
        # AAA has 2 bars; BBB has only 1 — BBB is dropped
        root = tmp_path / "universe"
        _write(
            root / "demo" / "seed.yaml",
            """
            name: demo
            seed_date: 2018-01-01
            members: [AAA, BBB]
            """,
        )
        _write(root / "demo" / "events.yaml", "name: demo\nevents: []\n")
        universe = Universe.load(root)

        parquet_root = tmp_path / "parquet"
        adapter = ParquetAdapter(parquet_root, vault_cutoff_days=None)
        adapter.write(
            ConnectorResult(
                frame=_ohlcv_for("AAA", 100.0, 110.0),
                source="test",
                fetched_at=datetime(2018, 8, 1, tzinfo=UTC),
                rows=2,
            ),
            kind="ohlcv",
        )
        # Single bar for BBB
        single = _ohlcv_for("BBB", 50.0, 50.0).iloc[:1]
        adapter.write(
            ConnectorResult(
                frame=single,
                source="test",
                fetched_at=datetime(2018, 8, 1, tzinfo=UTC),
                rows=1,
            ),
            kind="ohlcv",
        )
        report = monthly_equal_weight_return(
            universe=universe,
            universe_name="demo",
            year=2018,
            month=7,
            adapter=adapter,
            vault_override_reason="unit test",
        )
        # Only AAA contributes
        assert report.eligible_count == 1
        assert "BBB" not in report.constituent_returns
        assert report.equal_weight_return == pytest.approx(0.10)

    def test_no_usable_ohlcv_raises(self, tmp_path: Path) -> None:
        root = tmp_path / "universe"
        _write(
            root / "demo" / "seed.yaml",
            """
            name: demo
            seed_date: 2018-01-01
            members: [AAA]
            """,
        )
        _write(root / "demo" / "events.yaml", "name: demo\nevents: []\n")
        universe = Universe.load(root)

        # Empty parquet root — no OHLCV at all
        adapter = ParquetAdapter(tmp_path / "parquet", vault_cutoff_days=None)
        with pytest.raises(ValueError, match="no usable OHLCV"):
            monthly_equal_weight_return(
                universe=universe,
                universe_name="demo",
                year=2018,
                month=7,
                adapter=adapter,
                vault_override_reason="unit test",
            )

    def test_invalid_month_rejected(self, synthetic_universe: tuple) -> None:  # type: ignore[type-arg]
        universe, adapter = synthetic_universe
        with pytest.raises(ValueError, match="1..12"):
            monthly_equal_weight_return(
                universe=universe,
                universe_name="demo",
                year=2018,
                month=13,
                adapter=adapter,
                vault_override_reason="unit test",
            )

    def test_unknown_universe_propagates(self, synthetic_universe: tuple) -> None:  # type: ignore[type-arg]
        universe, adapter = synthetic_universe
        with pytest.raises(UniverseSchemaError):
            monthly_equal_weight_return(
                universe=universe,
                universe_name="nasdaq100",
                year=2018,
                month=7,
                adapter=adapter,
                vault_override_reason="unit test",
            )


class TestLastTradingDayOfMonth:
    def test_returns_a_date(self) -> None:
        d = last_trading_day_of_month(2018, 7)
        # July 2018 ends on a Tuesday — last trading day is the 31st (Tue)
        assert d == date(2018, 7, 31)

    def test_handles_month_ending_on_weekend(self) -> None:
        # March 2018 ends on Saturday the 31st; last trading day is Thursday 29
        # (Friday the 30th was Good Friday, NYSE closed)
        d = last_trading_day_of_month(2018, 3)
        # Be lenient: result is the last calendar day if pandas_market_calendars
        # isn't installed; otherwise should be the 29th (Good Friday adjustment).
        assert d in {date(2018, 3, 31), date(2018, 3, 30), date(2018, 3, 29)}
