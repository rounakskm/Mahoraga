"""Tests for the Reconciler — local vs broker, halt on material discrepancy."""

from __future__ import annotations

from pathlib import Path

from services.trader.execution.model import Portfolio, Position
from services.trader.execution.reconcile import Reconciler, ReconResult
from services.trader.ops.halt import HaltControl


class _StubBroker:
    """Tiny broker stub exposing only `.positions() -> dict[str, Position]`."""

    def __init__(self, positions: dict[str, Position]) -> None:
        self._positions = positions

    def positions(self) -> dict[str, Position]:
        return self._positions


def _pos(ticker: str, market_value: float) -> Position:
    return Position(
        ticker=ticker,
        qty=10.0,
        avg_entry=market_value / 10.0,
        market_value=market_value,
        unrealized_pl=0.0,
    )


def _portfolio(positions: dict[str, Position], equity: float = 100_000.0) -> Portfolio:
    return Portfolio(equity=equity, cash=equity, buying_power=equity, positions=positions)


def _halt(tmp_path: Path) -> HaltControl:
    return HaltControl(tmp_path / "halt.flag")


def test_identical_local_and_broker_matches_no_halt(tmp_path: Path) -> None:
    halt = _halt(tmp_path)
    local = _portfolio({"SPY": _pos("SPY", 5000.0)})
    broker = _StubBroker({"SPY": _pos("SPY", 5000.0)})

    result = Reconciler(broker, halt).reconcile(local)

    assert isinstance(result, ReconResult)
    assert result.matched is True
    assert result.mismatches == []
    assert result.halted is False
    assert halt.is_halted() is False


def test_phantom_broker_position_mismatch_and_halt(tmp_path: Path) -> None:
    halt = _halt(tmp_path)
    local = _portfolio({"SPY": _pos("SPY", 5000.0)})
    broker = _StubBroker(
        {"SPY": _pos("SPY", 5000.0), "TSLA": _pos("TSLA", 3000.0)}
    )

    result = Reconciler(broker, halt).reconcile(local)

    assert result.matched is False
    assert result.halted is True
    assert any("TSLA" in m for m in result.mismatches)
    assert halt.is_halted() is True


def test_phantom_local_position_mismatch_and_halt(tmp_path: Path) -> None:
    halt = _halt(tmp_path)
    local = _portfolio({"SPY": _pos("SPY", 5000.0), "AAPL": _pos("AAPL", 2000.0)})
    broker = _StubBroker({"SPY": _pos("SPY", 5000.0)})

    result = Reconciler(broker, halt).reconcile(local)

    assert result.matched is False
    assert result.halted is True
    assert any("AAPL" in m for m in result.mismatches)
    assert halt.is_halted() is True


def test_notional_drift_over_tolerance_halts(tmp_path: Path) -> None:
    halt = _halt(tmp_path)
    # equity 100k, 1% = 1000; drift of 2000 exceeds tolerance.
    local = _portfolio({"SPY": _pos("SPY", 5000.0)})
    broker = _StubBroker({"SPY": _pos("SPY", 7000.0)})

    result = Reconciler(broker, halt).reconcile(local)

    assert result.matched is False
    assert result.halted is True
    assert any("SPY" in m for m in result.mismatches)
    assert halt.is_halted() is True


def test_notional_drift_under_tolerance_matches(tmp_path: Path) -> None:
    halt = _halt(tmp_path)
    # equity 100k, 1% = 1000; drift of 500 is benign.
    local = _portfolio({"SPY": _pos("SPY", 5000.0)})
    broker = _StubBroker({"SPY": _pos("SPY", 5500.0)})

    result = Reconciler(broker, halt).reconcile(local)

    assert result.matched is True
    assert result.mismatches == []
    assert result.halted is False
    assert halt.is_halted() is False


def test_both_empty_matches_no_halt(tmp_path: Path) -> None:
    halt = _halt(tmp_path)
    local = _portfolio({})
    broker = _StubBroker({})

    result = Reconciler(broker, halt).reconcile(local)

    assert result.matched is True
    assert result.mismatches == []
    assert result.halted is False
    assert halt.is_halted() is False


def test_explained_phantom_does_not_halt(tmp_path) -> None:
    """A broker position explained by post-snapshot orders is logged, not halted."""
    halt = HaltControl(tmp_path / "halt.flag")
    broker = _StubBroker(
        {"SPY": Position("SPY", 3.0, 750.0, 2250.0, 0.0)}
    )
    local = Portfolio(equity=100_000.0, cash=100_000.0, buying_power=100_000.0, positions={})
    result = Reconciler(broker, halt).reconcile(
        local, explained_tickers=frozenset({"SPY"})
    )
    assert result.matched is True
    assert result.halted is False
    assert not halt.is_halted()


def test_unexplained_phantom_still_halts(tmp_path) -> None:
    """explained_tickers only exempts ITS tickers — anything else fails closed."""
    halt = HaltControl(tmp_path / "halt.flag")
    broker = _StubBroker(
        {
            "SPY": Position("SPY", 3.0, 750.0, 2250.0, 0.0),
            "TSLA": Position("TSLA", 5.0, 400.0, 2000.0, 0.0),
        }
    )
    local = Portfolio(equity=100_000.0, cash=100_000.0, buying_power=100_000.0, positions={})
    result = Reconciler(broker, halt).reconcile(
        local, explained_tickers=frozenset({"SPY"})
    )
    assert result.halted is True
    assert any("TSLA" in m for m in result.mismatches)
    assert not any("SPY" in m for m in result.mismatches)
