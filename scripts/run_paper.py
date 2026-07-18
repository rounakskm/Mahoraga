#!/usr/bin/env python3
"""Run the Phase-5 paper-trading smokes (graceful-offline, dry-run by default).

Four subcommands, each degrading to a clear no-op skip (exit 0) when its external
dependency is absent — no Alpaca key, no network:

    uv run python scripts/run_paper.py account
    uv run python scripts/run_paper.py positions
    uv run python scripts/run_paper.py cycle --strategy strategies/seed1-<run>.json
    uv run python scripts/run_paper.py eod

- `account`   — build an `AlpacaBrokerClient` from env and print the paper Portfolio
                (equity / cash / buying_power / positions). Read-only GET. No key ->
                "Alpaca key not set" + exit 0.
- `positions` — print open positions (read-only GET). No key -> informative skip.
- `cycle`     — run ONE execution cycle for a promoted strategy artifact through the
                REAL production wiring: live quote from the Alpaca data API, daily P&L
                from the broker account, monthly P&L from the trailing-30-day
                `trades.pnl_daily` baseline vs live equity (arms the 10% catastrophic
                halt), `build_firewall_context` (the ONE ctx factory),
                `HardLimitFirewall` with a live `EconCalendarGate`, `ComplianceEngine`
                fed by `TradeStore.recent_trades`, reconciliation against the last
                position snapshot, and order/position persistence to `trades.*`.
                With `--signal` the intent comes from the REAL regime-conditional
                daily signal (artifact windows/thresholds over ~450 daily bars);
                without it the old fixed illustrative BUY remains (for smokes).
- `eod`       — record the end-of-day state: `trades.pnl_daily` (equity, day P&L
                vs `last_equity`, summed unrealized) + a position snapshot.

SAFETY — dry-run by default. `cycle` submits nothing live unless `--live-orders` is
passed; that flag defaults FALSE and, when set, prints a bold confirmation banner
before running. A live cycle REQUIRES a real market quote: with no key/quote the
runner refuses `--live-orders` and downgrades to a dry-run priced by `--price`.
`account` / `positions` are read-only GETs and always safe.

Env (read via `os.environ.get`, never required):
    ALPACA_API_KEY / ALPACA_SECRET_KEY — Alpaca paper trading auth.
    ALPACA_PAPER_ENDPOINT — paper trading REST base (default paper-api.alpaca.markets/v2).
    ALPACA_DATA_ENDPOINT  — market data REST base (default data.alpaca.markets).
    MAHORAGA_DSN          — Postgres DSN for the trade store (disabled when unset).
    FRED_API_KEY          — enables the CPI/NFP release calendar in the blackout gate.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path

import httpx
import pandas as pd

from services.trader.execution.active_strategy import (
    ActiveStrategy,
    select_active_strategy,
    write_active,
)
from services.trader.execution.alpaca_broker import AlpacaBrokerClient
from services.trader.execution.calendar_gate import EconCalendarGate
from services.trader.execution.compliance import ComplianceEngine
from services.trader.execution.context import build_firewall_context
from services.trader.execution.executor import CtxBuilder, CycleReport, Executor
from services.trader.execution.firewall import FirewallContext, HardLimitFirewall
from services.trader.execution.model import Order, OrderIntent, Portfolio, Side
from services.trader.execution.reconcile import Reconciler
from services.trader.execution.signal import compute_signal, intent_from_signal
from services.trader.execution.stops import atr as compute_atr
from services.trader.execution.trade_store import TradeStore
from services.trader.execution.watchlist import (
    DEFAULT_WATCHLIST,
    intents_for,
    sector_for,
    signals_for,
)
from services.trader.ops.audit import AuditLog
from services.trader.ops.halt import HaltControl

logger = logging.getLogger("run_paper")

_DEFAULT_ENDPOINT = "https://paper-api.alpaca.markets/v2"
_DEFAULT_DATA_ENDPOINT = "https://data.alpaca.markets"

# The single symbol this Phase-5 smoke trades, and its sector for the 20% cap.
_SECTOR_MAP = {"SPY": "ETF"}

# The conductor writes the adopted artifact here (read by `_load_artifact`), and
# tracks the last-adopted candidate_hash so a re-adopt of the SAME strategy does
# NOT spam the audit chain.
_ACTIVE_ARTIFACT_PATH = Path("strategies/active.json")
_ACTIVE_STATE_PATH = Path("data/control/active_strategy.txt")


def _adopt_from_registry(
    dsn: str | None,
    *,
    artifact_path: Path = _ACTIVE_ARTIFACT_PATH,
    state_path: Path = _ACTIVE_STATE_PATH,
) -> Path | None:
    """Select + deploy the best vault-validated registry strategy.

    Returns the written artifact path (ready for `_load_artifact`), or None when
    there is no deployment-eligible strategy — the caller then skips gracefully.

    The train->promote->deploy handoff is audited ONCE per change: the selected
    `candidate_hash` is compared against `state_path` (the last adopted one); on
    a change we append a `strategy_adopted` event and rewrite the state file, on
    an unchanged hash we proceed silently (no audit spam). `AuditLog` with no DSN
    is already a graceful no-op, so the audit line just doesn't persist offline.
    """
    strat = select_active_strategy(dsn)
    if strat is None:
        return None
    write_active(strat, out_path=artifact_path)
    _audit_adoption(strat, dsn, state_path=state_path)
    return artifact_path


def _audit_adoption(
    strat: ActiveStrategy, dsn: str | None, *, state_path: Path = _ACTIVE_STATE_PATH
) -> bool:
    """Audit a strategy adoption iff its candidate_hash changed since last time.

    Reads the previous hash from `state_path`, compares, and on a change writes
    an `AuditLog.append("strategy_adopted", ...)` event + rewrites the state
    file + prints the adopt line. Same hash -> no-op, returns False. Returns True
    when a (new) adoption was recorded.
    """
    previous = state_path.read_text(encoding="utf-8").strip() if state_path.exists() else None
    if previous == strat.candidate_hash:
        return False

    AuditLog(dsn).append(
        "strategy_adopted",
        {"candidate_hash": strat.candidate_hash, "vault_sharpe": strat.vault_sharpe},
    )
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(strat.candidate_hash, encoding="utf-8")
    sharpe = "n/a" if strat.vault_sharpe is None else f"{strat.vault_sharpe:.3f}"
    print(f"adopted {strat.candidate_hash} (vault Sharpe {sharpe})")
    return True


def _broker() -> AlpacaBrokerClient:
    """Build an `AlpacaBrokerClient` from env; no key -> disabled (safe no-op)."""
    return AlpacaBrokerClient(
        key=os.environ.get("ALPACA_API_KEY"),
        secret=os.environ.get("ALPACA_SECRET_KEY"),
        endpoint=os.environ.get("ALPACA_PAPER_ENDPOINT", _DEFAULT_ENDPOINT),
    )


def _latest_trade_price(symbol: str) -> float | None:
    """Latest REAL trade price from the Alpaca data API; None when unavailable.

    GET {ALPACA_DATA_ENDPOINT}/v2/stocks/{symbol}/trades/latest with the same
    key headers as `alpaca_news.py`. Graceful-offline: no key, network failure
    or a malformed payload all return None — the caller decides what a missing
    quote means (dry-run may fall back to --price; live may NOT).
    """
    key = os.environ.get("ALPACA_API_KEY")
    secret = os.environ.get("ALPACA_SECRET_KEY")
    if not (key and secret):
        return None
    base = os.environ.get("ALPACA_DATA_ENDPOINT", _DEFAULT_DATA_ENDPOINT).rstrip("/")
    try:
        resp = httpx.get(
            f"{base}/v2/stocks/{symbol}/trades/latest",
            headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret},
            timeout=30,
        )
        resp.raise_for_status()
        price = float(resp.json()["trade"]["p"])
    except Exception:
        logger.warning("latest-trade quote fetch failed for %s", symbol, exc_info=True)
        return None
    return price if price > 0 else None


def _daily_bars(symbol: str, limit: int = 450) -> pd.DataFrame | None:
    """~450 daily OHLCV bars from the Alpaca data API; None when unavailable.

    GET {ALPACA_DATA_ENDPOINT}/v2/stocks/{symbol}/bars with the same key headers
    as `_latest_trade_price`. 450 bars comfortably covers the detector warmup
    (~312 bars for realized_vol_pct_60). `adjustment=split` keeps close/SMA
    comparisons consistent across splits without dividend-smearing the OHLC.
    Graceful-offline: no key, network failure or a malformed/empty payload all
    return None — the caller runs NO orders without bars.
    """
    key = os.environ.get("ALPACA_API_KEY")
    secret = os.environ.get("ALPACA_SECRET_KEY")
    if not (key and secret):
        return None
    base = os.environ.get("ALPACA_DATA_ENDPOINT", _DEFAULT_DATA_ENDPOINT).rstrip("/")
    try:
        # Alpaca defaults `start` to TODAY (one bar), and `limit` returns the
        # FIRST N bars after `start`, not the most recent — so request a ~700
        # calendar-day window (covers 450 trading days) and keep the tail.
        start = (pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=700)).date().isoformat()
        resp = httpx.get(
            f"{base}/v2/stocks/{symbol}/bars",
            params={
                "timeframe": "1Day",
                "start": start,
                "limit": 10_000,
                "adjustment": "split",
            },
            headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret},
            timeout=30,
        )
        resp.raise_for_status()
        raw = (resp.json().get("bars") or [])[-limit:]
        if not raw:
            return None
        frame = pd.DataFrame(
            {
                "open": [float(b["o"]) for b in raw],
                "high": [float(b["h"]) for b in raw],
                "low": [float(b["l"]) for b in raw],
                "close": [float(b["c"]) for b in raw],
                "volume": [float(b["v"]) for b in raw],
            },
            index=pd.to_datetime([b["t"] for b in raw], utc=True),
        ).sort_index()
    except Exception:
        logger.warning("daily bars fetch failed for %s", symbol, exc_info=True)
        return None
    return frame


def _calendar_gate() -> EconCalendarGate:
    """The production FOMC/CPI/NFP blackout gate.

    With FRED_API_KEY a real `ReleaseCalendar` backs the CPI/NFP check; without
    it the gate still enforces the committed FOMC constants AND the C5
    fail-closed behaviors (schedule-exhausted guard, consecutive-failure
    blackout), so it is ALWAYS wired into the firewall.
    """
    fred_key = os.environ.get("FRED_API_KEY")
    if not fred_key:
        logger.warning(
            "FRED_API_KEY not set — CPI/NFP release-day blackout disabled "
            "(FOMC constants still enforced)"
        )
        return EconCalendarGate(release_calendar=None)
    from services.trader.data.connectors.fred import HttpxFetcher  # noqa: PLC0415
    from services.trader.data.connectors.release_calendar import (  # noqa: PLC0415
        ReleaseCalendar,
    )

    return EconCalendarGate(release_calendar=ReleaseCalendar(HttpxFetcher(), api_key=fred_key))


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


def _reconcile_if_stateful(
    broker: AlpacaBrokerClient,
    store: TradeStore,
    halt: HaltControl,
    portfolio: Portfolio,
) -> None:
    """Reconcile the last persisted position snapshot against the broker (C7).

    Reconciling a fresh broker snapshot against itself is vacuous, so the local
    book comes from the latest `trades.positions` snapshot instead — the value
    lands from the SECOND run onward, once the store holds state. Skipped (with
    a note) when the store is disabled, the broker is disabled, or no fresh
    snapshot exists (first run). A material mismatch trips the kill-switch,
    which the executor's halt-first check then honors.
    """
    if not (store.is_enabled() and broker.is_enabled()):
        print("reconcile: skipped (trade store or broker disabled)")
        return
    local_positions = store.latest_positions()
    if local_positions is None:
        print("reconcile: skipped (no fresh position snapshot yet — first run)")
        return
    local = Portfolio(
        equity=portfolio.equity,
        cash=portfolio.cash,
        buying_power=portfolio.buying_power,
        positions=local_positions,
    )
    # Orders recorded after the snapshot EXPLAIN a divergence (e.g. an entry
    # submitted post-snapshot filled at the open) — log, don't false-halt.
    explained = store.tickers_ordered_since_snapshot()
    result = Reconciler(broker, halt).reconcile(local, explained_tickers=explained)
    print(f"reconcile: matched={result.matched} halted={result.halted}")
    for m in result.mismatches:
        print(f"  mismatch: {m}")


def _run_executor(
    intents: list[OrderIntent],
    portfolio: Portfolio,
    prices: dict[str, float],
    ctx_for: CtxBuilder,
    broker: AlpacaBrokerClient,
    store: TradeStore,
    halt: HaltControl,
    *,
    live_orders: bool,
) -> CycleReport:
    """The shared safety-critical flow: reconcile -> executor -> snapshot -> close.

    Identical for the single-symbol and multi-symbol paths — reconcile the
    persisted book against the broker (C7), run ONE firewall/compliance-gated
    `Executor.run_cycle`, persist the post-cycle snapshot, and close the store.
    Returns the `CycleReport` (both callers print their own summary around it).
    """
    # C7 — reconcile the persisted book against the broker BEFORE trading.
    _reconcile_if_stateful(broker, store, halt, portfolio)

    executor = Executor(
        broker=broker,
        firewall=HardLimitFirewall(calendar_gate=_calendar_gate()),
        compliance=ComplianceEngine(),
        halt=halt,
        live_orders=live_orders,
        recent_trades=store.recent_trades,  # C3 — compliance sees real history.
        on_submit=lambda submitted_intent, returned_order: store.record_order(
            returned_order, reason=submitted_intent.reason
        ),
        # Alpaca rejects fractional qty on OTO/bracket orders -> whole shares.
        allow_fractional=False,
    )
    report = executor.run_cycle(intents, portfolio, prices=prices, ctx_for=ctx_for)

    # C7 — persist the post-cycle position snapshot (no-op when disabled).
    if broker.is_enabled():
        store.snapshot_positions(broker.account())
    store.close()
    return report


def run_watchlist_cycle(
    artifact: dict,
    symbols: list[str],
    broker: AlpacaBrokerClient,
    store: TradeStore,
    halt: HaltControl,
    *,
    live_orders: bool,
    bars_by_symbol: dict[str, pd.DataFrame],
    prices: dict[str, float],
    weight: float = 0.03,
) -> CycleReport:
    """Run ONE portfolio-wide execution cycle over a watchlist (pure — no I/O).

    The runner (`cmd_cycle --watchlist`) gathers `bars_by_symbol` and `prices`
    from the network and hands them here; this helper owns the deterministic
    part so it is unit-testable offline. Every Phase-5 safety property is
    preserved: it fans the real regime-conditional signal over the watchlist,
    then runs ONE `Executor.run_cycle` against the single shared `Portfolio`, so
    the firewall aggregates the 5% position / 20% sector caps portfolio-wide.

    `ctx_for` sets `sector=sector_for(intent.ticker)` and derives `order_notional`
    from the intent's UN-clamped target weight (via `build_firewall_context`), so
    the firewall judges the strategy's true requested exposure per symbol.
    """
    portfolio = (
        broker.account()
        if broker.is_enabled()
        else Portfolio(equity=100_000.0, cash=100_000.0, buying_power=100_000.0, positions={})
    )

    # Per-symbol signals (undecidable / warmup-only symbols are dropped) and the
    # matching per-symbol ATR(14) — used both for the stop and the firewall's
    # 2xATR stop-distance check.
    signals = signals_for(artifact, bars_by_symbol)
    atr_by_symbol: dict[str, float | None] = {}
    for symbol, bars in bars_by_symbol.items():
        last_atr = compute_atr(bars).iloc[-1]
        atr_by_symbol[symbol] = float(last_atr) if pd.notna(last_atr) else None
    intents = intents_for(signals, portfolio, prices, atr_by_symbol, weight=weight)

    now = pd.Timestamp.now(tz="UTC")
    daily_pl_pct = broker.daily_pl_pct()
    monthly_pl_pct = store.monthly_pl_pct(current_equity=portfolio.equity)
    sector_map = {sym: sector_for(sym) for sym in symbols}

    def ctx_for(order_intent: OrderIntent, order: Order) -> FirewallContext:
        return build_firewall_context(
            order_intent,
            order,
            portfolio,
            now=now,
            price=prices[order_intent.ticker],
            atr_value=atr_by_symbol.get(order_intent.ticker),
            daily_pl_pct=daily_pl_pct,
            monthly_pl_pct=monthly_pl_pct,
            sector_map=sector_map,
        )

    report = _run_executor(
        intents, portfolio, prices, ctx_for, broker, store, halt, live_orders=live_orders
    )

    for symbol, sig in sorted(signals.items()):
        print(
            f"signal {symbol}: regime={sig.regime} want_long={sig.want_long} "
            f"close={sig.close:.2f} sma={sig.sma:.2f} confidence={sig.confidence:.2f}"
        )
    return report


def _cmd_cycle_watchlist(args: argparse.Namespace, artifact: dict, path: Path) -> int:
    """Multi-symbol cycle: gather bars/prices over `DEFAULT_WATCHLIST`, then run.

    Fetches ~450 daily bars + a latest-trade quote per watchlist symbol (each
    graceful-offline: symbols with no bars or no quote are skipped with a log),
    then delegates to the pure `run_watchlist_cycle`. Dry-run default; live
    orders still require a per-symbol quote (a symbol with no quote is dropped,
    never sized off a fallback price).
    """
    live_orders = bool(args.live_orders)

    bars_by_symbol: dict[str, pd.DataFrame] = {}
    prices: dict[str, float] = {}
    for symbol in DEFAULT_WATCHLIST:
        bars = _daily_bars(symbol)
        if bars is None:
            print(f"watchlist {symbol}: no daily bars (no key / fetch failed) — skipped")
            continue
        quote = _latest_trade_price(symbol)
        if quote is None:
            print(f"watchlist {symbol}: no market quote — skipped (cannot size live)")
            continue
        bars_by_symbol[symbol] = bars
        prices[symbol] = quote

    if not bars_by_symbol:
        print("watchlist: no symbols with both bars and a quote — no orders this cycle")

    if live_orders and bars_by_symbol:
        print("=" * 64)
        print("\033[1m⚠️  LIVE PAPER ORDERS ENABLED — submitting to Alpaca paper account\033[0m")
        print("=" * 64)

    broker = _broker()
    store = TradeStore(os.environ.get("MAHORAGA_DSN"))
    halt = HaltControl()  # C8 — the DEFAULT repo-wide kill-switch flag.

    report = run_watchlist_cycle(
        artifact,
        list(bars_by_symbol),
        broker,
        store,
        halt,
        live_orders=live_orders,
        bars_by_symbol=bars_by_symbol,
        prices=prices,
        weight=args.weight,
    )

    mode = "LIVE PAPER" if live_orders else "dry-run"
    keyed = "enabled" if broker.is_enabled() else "disabled (no key)"
    stored = "enabled" if store.is_enabled() else "disabled (no MAHORAGA_DSN)"
    print(
        f"strategy {artifact.get('run_id', path.stem)} — {mode} watchlist cycle "
        f"on {len(bars_by_symbol)} symbol(s): {', '.join(bars_by_symbol) or '-'}"
    )
    print(f"broker: {keyed}")
    print(f"store:  {stored}")
    print(
        f"CycleReport(intents={report.intents}, submitted={report.submitted}, "
        f"rejected={report.rejected}, errors={report.errors}, halted={report.halted})"
    )
    for r in report.rejections:
        print(f"  rejected: {r}")
    return 0


def cmd_cycle(args: argparse.Namespace) -> int:
    """Run ONE execution cycle for a strategy artifact; print the CycleReport.

    The artifact comes either from an explicit `--strategy PATH` (manual pin) or,
    with `--from-registry`, from the conductor's auto-adopt: the best
    deployment-eligible `strategies.registry` strategy is written to
    `strategies/active.json` and used as the artifact. Exactly one source is
    given (enforced by the parser); `--from-registry` with no eligible strategy
    is a graceful exit 0. Both sources then flow through the identical
    single-symbol / `--watchlist` path below.
    """
    if args.from_registry:
        path = _adopt_from_registry(os.environ.get("MAHORAGA_DSN"))
        if path is None:
            print("no deployment-eligible strategy in registry; nothing to trade")
            return 0
    else:
        path = Path(args.strategy)
    if not path.exists():
        print(f"strategy artifact not found: {path}; nothing to run")
        return 0
    artifact = _load_artifact(path)

    if args.watchlist:
        return _cmd_cycle_watchlist(args, artifact, path)

    symbol = "SPY"
    live_orders = bool(args.live_orders)

    # C2 — a REAL market quote. Live cycles refuse to run without one; dry-run
    # falls back to the illustrative --price.
    quote = _latest_trade_price(symbol)
    if quote is None:
        if live_orders:
            print(
                "no market quote available; refusing --live-orders, "
                "running dry-run with --price"
            )
            live_orders = False
        price = float(args.price)
        price_source = f"--price (no quote; illustrative {price})"
    else:
        price = quote
        price_source = f"Alpaca latest trade ({price})"

    if live_orders:
        print("=" * 64)
        print("\033[1m⚠️  LIVE PAPER ORDERS ENABLED — submitting to Alpaca paper account\033[0m")
        print("=" * 64)

    broker = _broker()
    store = TradeStore(os.environ.get("MAHORAGA_DSN"))
    halt = HaltControl()  # C8 — the DEFAULT repo-wide kill-switch flag.
    now = pd.Timestamp.now(tz="UTC")

    # Read-only account snapshot when keyed; else an illustrative $100k paper book.
    portfolio = (
        broker.account()
        if broker.is_enabled()
        else Portfolio(equity=100_000.0, cash=100_000.0, buying_power=100_000.0, positions={})
    )

    # Intent source: the REAL regime-conditional daily signal with --signal;
    # the fixed illustrative BUY otherwise (kept for smokes). A missing signal
    # or an already-aligned book runs NO orders — reconcile + snapshot still run.
    atr_value: float | None = None
    intents: list[OrderIntent] = []
    if args.signal:
        bars = _daily_bars(symbol)
        if bars is None:
            print("signal: no daily bars available (no key / fetch failed) — no orders this cycle")
        else:
            last_atr = compute_atr(bars).iloc[-1]
            atr_value = float(last_atr) if pd.notna(last_atr) else None
            sig = compute_signal(artifact, bars)
            if sig is None:
                print("signal: undefined regime (warmup / NaN inputs) — no orders this cycle")
            else:
                print(
                    f"signal: regime={sig.regime} want_long={sig.want_long} "
                    f"close={sig.close:.2f} sma={sig.sma:.2f} confidence={sig.confidence:.2f}"
                )
                intent = intent_from_signal(
                    sig, portfolio, symbol, price, atr_value, entry_weight=args.weight
                )
                if intent is None:
                    print("signal: book already aligned with signal — no orders this cycle")
                else:
                    intents.append(intent)
    else:
        intents.append(_illustrative_intent(symbol, price))

    # C2 — REAL P&L context. Daily from the broker account (equity vs
    # last_equity); monthly from the trailing-30-day `trades.pnl_daily`
    # baseline (recorded by `eod`) vs the live account equity — this is what
    # arms the 10% monthly-catastrophic halt. A disabled store or an empty
    # window yields None, which `build_firewall_context` maps to 0.0 WITH a
    # WARNING — that warning is the signal the monthly halt cannot trip.
    daily_pl_pct = broker.daily_pl_pct()
    monthly_pl_pct = store.monthly_pl_pct(current_equity=portfolio.equity)

    def ctx_for(order_intent: OrderIntent, order: Order) -> FirewallContext:
        return build_firewall_context(
            order_intent,
            order,
            portfolio,
            now=now,
            price=price,
            atr_value=atr_value,  # real ATR(14) from the daily bars in --signal mode.
            daily_pl_pct=daily_pl_pct,
            monthly_pl_pct=monthly_pl_pct,
            sector_map=_SECTOR_MAP,
        )

    report = _run_executor(
        intents, portfolio, {symbol: price}, ctx_for, broker, store, halt,
        live_orders=live_orders,
    )

    mode = "LIVE PAPER" if live_orders else "dry-run"
    keyed = "enabled" if broker.is_enabled() else "disabled (no key)"
    stored = "enabled" if store.is_enabled() else "disabled (no MAHORAGA_DSN)"
    print(f"strategy {artifact.get('run_id', path.stem)} — {mode} cycle on {symbol}")
    print(f"price:  {price_source}")
    print(f"broker: {keyed}")
    print(f"store:  {stored}")
    print(
        f"CycleReport(intents={report.intents}, submitted={report.submitted}, "
        f"rejected={report.rejected}, errors={report.errors}, halted={report.halted})"
    )
    for r in report.rejections:
        print(f"  rejected: {r}")
    return 0


def cmd_eod(args: argparse.Namespace) -> int:
    """Record end-of-day state: `trades.pnl_daily` + a position snapshot.

    Read-only against the broker (two GETs); writes only to Postgres. Graceful:
    no key -> informative skip; no MAHORAGA_DSN -> the store no-ops (still
    prints what WOULD have been recorded).
    """
    broker = _broker()
    if not broker.is_enabled():
        print("Alpaca key not set; skipping eod record")
        return 0

    portfolio = broker.account()

    # Day P&L the same way `daily_pl_pct` derives it: the raw /account payload
    # carries `last_equity` (previous trading day's close), so equity minus
    # last_equity is today's total P&L. Recorded in the `realized_pl` column of
    # `trades.pnl_daily` per the Phase-5 ops convention (exact tax-lot realized
    # P&L lands with the ops/pnl wiring).
    realized = 0.0
    try:
        raw = broker._get("/account")  # the same raw read daily_pl_pct uses
        last_equity = float(raw.get("last_equity") or 0.0) if isinstance(raw, dict) else 0.0
        if last_equity > 0:
            realized = portfolio.equity - last_equity
        else:
            logger.warning("eod: last_equity missing/non-positive — recording realized_pl=0.0")
    except Exception:
        logger.warning("eod: raw account fetch failed — recording realized_pl=0.0", exc_info=True)

    unrealized = sum(pos.unrealized_pl for pos in portfolio.positions.values())
    d = pd.Timestamp.now(tz="America/New_York").date()  # US/Eastern trading date

    with TradeStore(os.environ.get("MAHORAGA_DSN")) as store:
        store.record_daily_pnl(d, equity=portfolio.equity, realized=realized, unrealized=unrealized)
        store.snapshot_positions(portfolio)
        stored = "recorded to trades.*" if store.is_enabled() else "NOT recorded (no MAHORAGA_DSN)"

    print(f"eod {d} — {stored}")
    print(f"equity        {portfolio.equity:,.2f}")
    print(f"realized_pl   {realized:,.2f} (equity - last_equity)")
    print(f"unrealized_pl {unrealized:,.2f} (sum of open-position unrealized)")
    print(f"positions     {len(portfolio.positions)} snapshotted")
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ap = _build_parser()
    args = ap.parse_args()
    return int(args.func(args))


def _build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser (extracted so tests can introspect it in-process)."""
    ap = argparse.ArgumentParser(
        description="Phase-5 paper-trading runner (graceful-offline, dry-run default)"
    )
    sub = ap.add_subparsers(dest="command", required=True)

    p_account = sub.add_parser("account", help="print the paper Portfolio (read-only GET)")
    p_account.set_defaults(func=cmd_account)

    p_positions = sub.add_parser("positions", help="print open positions (read-only GET)")
    p_positions.set_defaults(func=cmd_positions)

    p_cycle = sub.add_parser("cycle", help="run ONE execution cycle for a strategy")
    # Exactly one strategy source: an explicit artifact PATH, or auto-adopt the
    # best vault-validated registry strategy. The mutually-exclusive group is
    # `required`, so `cycle` with neither errors clearly (as `--strategy` did).
    src = p_cycle.add_mutually_exclusive_group(required=True)
    src.add_argument(
        "--strategy", help="path to a promoted strategy artifact (JSON)"
    )
    src.add_argument(
        "--from-registry",
        action="store_true",
        default=False,
        help="AUTO-ADOPT: deploy the best deployment-eligible strategies.registry "
        "strategy (vault_sharpe DESC NULLS LAST, train_sharpe DESC) written to "
        "strategies/active.json; audits the handoff when the adopted candidate "
        "changes. No eligible strategy -> graceful skip (exit 0)",
    )
    p_cycle.add_argument(
        "--price",
        type=float,
        default=100.0,
        help="illustrative fallback price — used ONLY when no real quote is "
        "available, and never for --live-orders",
    )
    p_cycle.add_argument(
        "--live-orders",
        action="store_true",
        default=False,
        help="submit REAL paper orders to Alpaca (default OFF — everything dry-run; "
        "requires a real market quote)",
    )
    p_cycle.add_argument(
        "--signal",
        action="store_true",
        default=False,
        help="derive the intent from the REAL regime-conditional daily signal "
        "(artifact windows/thresholds over ~450 Alpaca daily bars); without it "
        "the fixed illustrative BUY runs (smoke mode)",
    )
    p_cycle.add_argument(
        "--weight",
        type=float,
        default=0.03,
        help="entry target weight for --signal BUY entries (default 0.03; the "
        "firewall still enforces the 5%% position cap)",
    )
    p_cycle.add_argument(
        "--watchlist",
        action="store_true",
        default=False,
        help="run a PORTFOLIO-WIDE cycle over DEFAULT_WATCHLIST (multi-symbol): "
        "fan the real regime-conditional signal over every watchlist symbol and "
        "run ONE Executor.run_cycle against the shared portfolio, so the 5%% "
        "position / 20%% sector caps aggregate portfolio-wide. Same safety as the "
        "single-symbol path (dry-run default; --live-orders + a per-symbol quote "
        "required)",
    )
    p_cycle.set_defaults(func=cmd_cycle)

    p_eod = sub.add_parser(
        "eod", help="record end-of-day equity/P&L + a position snapshot to trades.*"
    )
    p_eod.set_defaults(func=cmd_eod)

    return ap


if __name__ == "__main__":
    raise SystemExit(main())
