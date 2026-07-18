"""Phase-5 multi-symbol integration smoke — the portfolio-wide firewall over a watchlist.

End-to-end and fully OFFLINE: no network, no Alpaca key, no DSN. This proves the
Tier-3 multi-symbol cycle keeps every Phase-5 safety property while fanning the
real regime-conditional signal over a watchlist and running ONE `Executor.run_cycle`
against a single shared portfolio:

  * symbol A (SPY) signals a valid, in-limits long -> submitted (dry_run=True,
    live_orders=False);
  * symbol B (XLK) also signals long, but the seeded book already holds ~18% TECH,
    so the added ~3% breaches the 20% sector cap -> the REAL `HardLimitFirewall`
    rejects it with a sector reason and the stub broker NEVER sees a B order;
  * symbol C (IWM) is warmup-only (~100 bars) -> `compute_signal` returns None ->
    no signal, no intent, absent from the cycle;
  * the executor runs against ONE shared `Portfolio`;
  * `CycleReport(intents>=2, submitted==1, rejected>=1)`.

The pure `run_watchlist_cycle` helper is exercised directly (bars + prices injected),
so no network path is touched. A separate argparse assertion proves `cycle --help`
surfaces `--watchlist`.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import numpy as np
import pandas as pd
import pytest

from services.trader.execution.model import Order, Portfolio, Position
from services.trader.execution.trade_store import TradeStore
from services.trader.ops.halt import HaltControl

# `scripts/` is not an importable package (no __init__, and CI installs the repo
# as a wheel where scripts/ isn't shipped) — load run_paper.py by file path, the
# same pattern as test_dashboard_smoke.py.
_RUN_PAPER_PATH = Path(__file__).resolve().parents[3] / "scripts" / "run_paper.py"


def _load_run_paper() -> ModuleType:
    spec = importlib.util.spec_from_file_location("run_paper_undertest", _RUN_PAPER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


run_paper = _load_run_paper()
from services.trader.training.regime import detector_features

# ---------------------------------------------------------------------------
# Synthetic OHLCV builders (frame shape mirrors execution/tests/test_signal.py)
# ---------------------------------------------------------------------------


def _bars(closes: np.ndarray) -> pd.DataFrame:
    idx = pd.date_range("2024-01-02", periods=len(closes), freq="B", tz="UTC")
    close = pd.Series(closes.astype("float64"), index=idx)
    return pd.DataFrame(
        {
            "open": close.shift(1).fillna(close.iloc[0]),
            "high": close * 1.005,
            "low": close * 0.995,
            "close": close,
            "volume": pd.Series(1_000_000.0, index=idx),
        }
    )


def _uptrend_bars(n: int = 450, seed: int = 7) -> pd.DataFrame:
    """Steady uptrend with small deterministic noise — last bar clearly long."""
    rng = np.random.default_rng(seed)
    ramp = np.linspace(100.0, 200.0, n)
    noise = rng.normal(0.0, 0.3, n).cumsum() * 0.05
    return _bars(ramp + noise)


_WINDOWS = {
    "trending_low_vol": 20,
    "trending_high_vol": 150,
    "ranging_low_vol": 70,
    "ranging_high_vol": 30,
}


def _artifact_for(bars: pd.DataFrame) -> dict:
    """Artifact whose thresholds make the LAST bar trending_low_vol + long."""
    adx, vol = detector_features(bars)
    last_adx = float(adx.iloc[-1])
    last_vol = float(vol.iloc[-1])
    return {
        "windows": _WINDOWS,
        "adx_threshold": max(last_adx - 5.0, 1.0),
        "vol_threshold": last_vol + 10.0,
    }


# ---------------------------------------------------------------------------
# Stub broker — records every submit_order call; returns a seeded Portfolio
# ---------------------------------------------------------------------------


class _StubBroker:
    """A live-looking broker with no network: records submits, serves a seeded book."""

    def __init__(self, portfolio: Portfolio) -> None:
        self._portfolio = portfolio
        self.calls: list[tuple[Order, bool]] = []

    def is_enabled(self) -> bool:
        return True

    def account(self) -> Portfolio:
        return self._portfolio

    def positions(self) -> dict[str, Position]:
        return self._portfolio.positions

    def daily_pl_pct(self) -> float | None:
        return 0.0

    def submit_order(self, order: Order, *, dry_run: bool = True) -> Order:
        self.calls.append((order, dry_run))
        return order


def _seeded_portfolio() -> Portfolio:
    """$100k book already holding ~18% TECH via a NON-XLK tech name (AAPL).

    The 18% sits under a different ticker so XLK's book is still FLAT — XLK
    therefore produces a fresh BUY entry (a held XLK position would read as
    "already long" and yield no intent). `sector_for("XLK") == "TECH"`, so the
    added ~3% XLK entry pushes TECH exposure to ~21% > the 20% sector cap, while
    SPY (BROAD, 0% held) has ample room under both caps.
    """
    aapl = Position(
        ticker="AAPL",
        qty=180.0,
        avg_entry=100.0,
        market_value=18_000.0,  # 18% of 100k
        unrealized_pl=0.0,
        sector="TECH",  # matches watchlist.sector_for("XLK")
    )
    return Portfolio(
        equity=100_000.0,
        cash=82_000.0,
        buying_power=82_000.0,
        positions={"AAPL": aapl},
    )


# ---------------------------------------------------------------------------
# The multi-symbol cycle — portfolio-wide firewall over a 3-symbol watchlist
# ---------------------------------------------------------------------------


def test_watchlist_cycle_submits_only_the_in_limits_symbol() -> None:
    good = _uptrend_bars()  # SPY + XLK both read a valid long on the last bar
    artifact = _artifact_for(good)

    bars_by_symbol = {
        "SPY": good,
        "XLK": _uptrend_bars(seed=11),  # also long
        "IWM": _uptrend_bars(100),      # warmup-only -> compute_signal None
    }
    prices = {"SPY": 100.0, "XLK": 100.0, "IWM": 100.0}

    portfolio = _seeded_portfolio()
    broker = _StubBroker(portfolio)
    store = TradeStore(None)  # disabled -> reconcile/snapshot/monthly no-op offline
    halt = HaltControl()

    report = run_paper.run_watchlist_cycle(
        artifact,
        ["SPY", "XLK", "IWM"],
        broker,
        store,
        halt,
        live_orders=False,
        bars_by_symbol=bars_by_symbol,
        prices=prices,
    )

    submitted_tickers = [order.ticker for order, _dry in broker.calls]

    # Exactly SPY submitted, as a dry-run.
    assert submitted_tickers == ["SPY"]
    assert broker.calls[0][1] is True  # dry_run=True (live_orders=False)

    # XLK never reached the broker — the sector cap rejected it pre-submit.
    assert "XLK" not in submitted_tickers
    # IWM was warmup-only — never even became an intent.
    assert "IWM" not in submitted_tickers

    # Report shape: >=2 intents (SPY + XLK), one submitted, >=1 rejected.
    assert report.intents >= 2
    assert report.submitted == 1
    assert report.rejected >= 1
    assert report.halted is False

    # The rejection was the 20% sector cap on XLK (portfolio-wide firewall).
    sector_rejections = [r for r in report.rejections if "XLK" in r and "sector" in r.lower()]
    assert sector_rejections, f"expected an XLK sector-cap rejection, got {report.rejections}"


def test_cycle_help_shows_watchlist_flag(capsys: pytest.CaptureFixture[str]) -> None:
    """`run_paper.py cycle --help` surfaces the --watchlist flag (in-process, no network)."""
    parser = run_paper._build_parser()
    with pytest.raises(SystemExit) as exc:  # --help exits 0 after printing usage
        parser.parse_args(["cycle", "--help"])
    assert exc.value.code == 0
    assert "--watchlist" in capsys.readouterr().out
