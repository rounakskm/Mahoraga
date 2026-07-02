#!/usr/bin/env python3
"""Run the Phase-5 paper-trading smokes (graceful-offline, dry-run by default).

Three subcommands, each degrading to a clear no-op skip (exit 0) when its external
dependency is absent — no Alpaca key, no network:

    uv run python scripts/run_paper.py account
    uv run python scripts/run_paper.py positions
    uv run python scripts/run_paper.py cycle --strategy strategies/seed1-<run>.json

- `account`   — build an `AlpacaBrokerClient` from env and print the paper Portfolio
                (equity / cash / buying_power / positions). Read-only GET. No key ->
                "Alpaca key not set" + exit 0.
- `positions` — print open positions (read-only GET). No key -> informative skip.
- `cycle`     — run ONE dry-run execution cycle for a promoted strategy artifact:
                load its params, derive a single illustrative `OrderIntent` for its
                symbol (SPY), and route it through the REAL `HardLimitFirewall` +
                `ComplianceEngine` + `Executor` with an isolated `HaltControl`, then
                print the `CycleReport`. Wiring a full live-signal pipeline is out of
                scope for this task, so the intent is a minimal illustrative entry.

SAFETY — dry-run by default. `cycle` submits nothing live unless `--live-orders` is
passed; that flag defaults FALSE and, when set, prints a bold confirmation banner
before running. `account` / `positions` are read-only GETs and always safe.

Env (read via `os.environ.get`, never required):
    ALPACA_API_KEY / ALPACA_SECRET_KEY — Alpaca paper trading auth.
    ALPACA_PAPER_ENDPOINT — paper trading REST base (default paper-api.alpaca.markets/v2).
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import pandas as pd

from services.trader.execution.alpaca_broker import AlpacaBrokerClient
from services.trader.execution.compliance import ComplianceEngine
from services.trader.execution.executor import Executor
from services.trader.execution.firewall import FirewallContext, HardLimitFirewall
from services.trader.execution.model import Order, OrderIntent, Portfolio, Side
from services.trader.ops.halt import HaltControl

_DEFAULT_ENDPOINT = "https://paper-api.alpaca.markets/v2"
_HALT_FLAG = "data/control/run_paper.halt.flag"


def _broker() -> AlpacaBrokerClient:
    """Build an `AlpacaBrokerClient` from env; no key -> disabled (safe no-op)."""
    return AlpacaBrokerClient(
        key=os.environ.get("ALPACA_API_KEY"),
        secret=os.environ.get("ALPACA_SECRET_KEY"),
        endpoint=os.environ.get("ALPACA_PAPER_ENDPOINT", _DEFAULT_ENDPOINT),
    )


def _print_portfolio(portfolio: Portfolio) -> None:
    """Pretty-print a Portfolio snapshot."""
    print(f"equity        {portfolio.equity:,.2f}")
    print(f"cash          {portfolio.cash:,.2f}")
    print(f"buying_power  {portfolio.buying_power:,.2f}")
    print(f"day_trades    {portfolio.day_trade_count}")
    print(f"positions ({len(portfolio.positions)}):")
    for ticker, pos in sorted(portfolio.positions.items()):
        print(
            f"  {ticker:<8} qty={pos.qty:<12g} "
            f"mv={pos.market_value:,.2f} upl={pos.unrealized_pl:,.2f}"
        )


def cmd_account(args: argparse.Namespace) -> int:
    """Print the paper Portfolio. Read-only GET. No key -> informative skip."""
    broker = _broker()
    if not broker.is_enabled():
        print("Alpaca key not set; skipping account read")
        return 0
    _print_portfolio(broker.account())
    return 0


def cmd_positions(args: argparse.Namespace) -> int:
    """Print open positions. Read-only GET. No key -> informative skip."""
    broker = _broker()
    if not broker.is_enabled():
        print("Alpaca key not set; skipping positions read")
        return 0
    positions = broker.positions()
    print(f"open positions ({len(positions)}):")
    for ticker, pos in sorted(positions.items()):
        print(
            f"  {ticker:<8} qty={pos.qty:<12g} "
            f"mv={pos.market_value:,.2f} upl={pos.unrealized_pl:,.2f}"
        )
    return 0


def _load_artifact(path: Path) -> dict:
    """Load a promoted strategy artifact (strategies/<run>.json)."""
    return json.loads(path.read_text(encoding="utf-8"))


def _illustrative_intent(symbol: str, price: float) -> OrderIntent:
    """A minimal illustrative BUY intent — a small target weight with an ATR-style stop.

    Wiring a full live-signal pipeline is out of scope for this task; this is a
    plausible small entry so the firewall/compliance/executor flow can be exercised
    end-to-end and its `CycleReport` printed.
    """
    return OrderIntent(
        ticker=symbol,
        side=Side.BUY,
        target_weight=0.03,          # ~3% of equity — under the 5% hard limit.
        reason="illustrative Phase-5 dry-run entry",
        regime_confidence=0.65,      # plausible, above the 40% floor.
        stop_price=round(price * 0.96, 2),  # ~2xATR-style stop below entry.
    )


def cmd_cycle(args: argparse.Namespace) -> int:
    """Run ONE dry-run execution cycle for a strategy artifact; print the CycleReport."""
    path = Path(args.strategy)
    if not path.exists():
        print(f"strategy artifact not found: {path}; nothing to run")
        return 0
    artifact = _load_artifact(path)

    symbol = "SPY"
    price = float(args.price)

    if args.live_orders:
        print("=" * 64)
        print("\033[1m⚠️  LIVE PAPER ORDERS ENABLED — submitting to Alpaca paper account\033[0m")
        print("=" * 64)

    broker = _broker()
    now = pd.Timestamp.now(tz="UTC")
    intent = _illustrative_intent(symbol, price)

    def ctx_for(order_intent: OrderIntent, order: Order) -> FirewallContext:
        return FirewallContext(
            now=now,
            regime_confidence=order_intent.regime_confidence,
            daily_pl_pct=0.0,
            monthly_pl_pct=0.0,
            has_stop=order_intent.stop_price is not None,
            sector="ETF",
            order_notional=abs(order.qty) * price,
        )

    # Read-only account snapshot when keyed; else an illustrative $100k paper book.
    portfolio = (
        broker.account()
        if broker.is_enabled()
        else Portfolio(equity=100_000.0, cash=100_000.0, buying_power=100_000.0, positions={})
    )

    executor = Executor(
        broker=broker,
        firewall=HardLimitFirewall(),
        compliance=ComplianceEngine(),
        halt=HaltControl(flag_path=_HALT_FLAG),
        live_orders=args.live_orders,
    )
    report = executor.run_cycle(
        [intent], portfolio, prices={symbol: price}, ctx_for=ctx_for
    )

    mode = "LIVE PAPER" if args.live_orders else "dry-run"
    keyed = "enabled" if broker.is_enabled() else "disabled (no key)"
    print(f"strategy {artifact.get('run_id', path.stem)} — {mode} cycle on {symbol} @ {price}")
    print(f"broker: {keyed}")
    print(
        f"CycleReport(intents={report.intents}, submitted={report.submitted}, "
        f"rejected={report.rejected}, halted={report.halted})"
    )
    for r in report.rejections:
        print(f"  rejected: {r}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Phase-5 paper-trading runner (graceful-offline, dry-run default)"
    )
    sub = ap.add_subparsers(dest="command", required=True)

    p_account = sub.add_parser("account", help="print the paper Portfolio (read-only GET)")
    p_account.set_defaults(func=cmd_account)

    p_positions = sub.add_parser("positions", help="print open positions (read-only GET)")
    p_positions.set_defaults(func=cmd_positions)

    p_cycle = sub.add_parser("cycle", help="run ONE dry-run execution cycle for a strategy")
    p_cycle.add_argument(
        "--strategy", required=True, help="path to a promoted strategy artifact (JSON)"
    )
    p_cycle.add_argument(
        "--price", type=float, default=100.0, help="illustrative price for the symbol"
    )
    p_cycle.add_argument(
        "--live-orders",
        action="store_true",
        default=False,
        help="submit REAL paper orders to Alpaca (default OFF — everything dry-run)",
    )
    p_cycle.set_defaults(func=cmd_cycle)

    args = ap.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
