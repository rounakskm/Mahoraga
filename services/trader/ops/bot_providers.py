"""bot_providers — the real read-only providers behind the TelegramOps extras.

`TelegramOps` (telegram.py) routes `/regime`, `/strategy <hash>`, `/kb` and
`/report daily|weekly` to injected provider callables; until now nothing built
them with real data. `build_providers` is that pure factory: it closes the four
providers over a `DashboardData` (the graceful-offline panel layer), an optional
Postgres DSN (for the `strategies.registry` lookup) and an optional Hindsight
client (for the transition predictor's learned overlay).

Graceful-offline is the load-bearing contract, same as everywhere else in ops/:
every degraded path renders a clear typed-empty message instead of raising —
an operator command must never crash the bot loop. The registry lookup takes an
injectable ``rows`` param (the repo's standard test seam) and carries real SQL
bound to the ``005_experiments.sql`` ``strategies.registry`` column names;
psycopg is imported lazily so the module works with no DB extras installed.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pandas as pd

from services.trader.intel.transition import TransitionPredictor
from services.trader.ops.dashboard_data import DashboardData

# Columns SELECTed from strategies.registry (005_experiments.sql).
REGISTRY_COLUMNS: tuple[str, ...] = (
    "candidate_hash",
    "params",
    "train_sharpe",
    "vault_sharpe",
    "vault_holds",
    "deployment_eligible",
)
# Prefix match: /strategy takes the short hash an operator sees in /status.
_REGISTRY_SQL = (
    f"SELECT {', '.join(REGISTRY_COLUMNS)} FROM strategies.registry "
    "WHERE candidate_hash LIKE %s ORDER BY ts DESC LIMIT 1"
)

# How many KB entries /kb shows and how many attribution lines /report shows.
_KB_ENTRIES = 5
_TOP_N = 3
_WEEKLY_SESSIONS = 5


def build_providers(
    data: DashboardData,
    dsn: str | None = None,
    hindsight: Any | None = None,
) -> dict[str, Callable[..., str]]:
    """Build the four TelegramOps providers over real data sources.

    The returned keys are exactly the `TelegramOps` keyword names, so the
    runner can splat them: ``TelegramOps(..., **build_providers(...))``.
    """

    def regime_provider() -> str:
        info = data.regime_now()
        if not info:
            return "regime: unavailable (no local SPY data)"
        label = info.get("label", "?")
        lines = [f"regime: {label} (as of {info.get('asof', '?')})"]
        try:  # best-effort: omit the transition line on ANY predictor error
            transition = TransitionPredictor(hindsight).predict(
                [label], pd.Series(dtype=float)
            )
            lines.append(
                f"transition risk: {transition.prob * 100:.0f}% "
                f"toward {transition.to_label} ({transition.source})"
            )
        except Exception:  # noqa: BLE001 — the regime line must still render
            pass
        return "\n".join(lines)

    def strategy_provider(candidate_hash: str) -> str:
        prefix = candidate_hash.strip()
        if not dsn:
            return "strategy registry unavailable (no DB — set MAHORAGA_DSN)"
        row = _registry_lookup(dsn, prefix)
        if row is None:
            return f"strategy {prefix}: not found in strategies.registry"
        return _render_strategy(row)

    def kb_provider() -> str:
        entries = data.kb_recent(_KB_ENTRIES)
        if not entries:
            return "KB: no recent entries (Hindsight offline?)"
        return "\n".join(f"- {_kb_line(entry)}" for entry in entries)

    def report_provider(kind: str) -> str:
        if kind == "daily":
            return _daily_report(data)
        return _weekly_report(data)

    return {
        "regime_provider": regime_provider,
        "strategy_provider": strategy_provider,
        "kb_provider": kb_provider,
        "report_provider": report_provider,
    }


# ------------------------------------------------------------------- registry


def _registry_lookup(
    dsn: str | None,
    prefix: str,
    rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """The `strategies.registry` row whose candidate_hash starts with `prefix`.

    Injected `rows` win (test seam); else query Postgres lazily; no DSN → None.
    """
    if rows is not None:
        for row in rows:
            if str(row.get("candidate_hash", "")).startswith(prefix):
                return row
        return None
    if not dsn:
        return None
    import psycopg  # noqa: PLC0415 (lazy: only when a DSN is set)
    from psycopg.rows import dict_row  # noqa: PLC0415

    with (
        psycopg.connect(dsn) as conn,
        conn.cursor(row_factory=dict_row) as cur,
    ):
        cur.execute(_REGISTRY_SQL, (prefix + "%",))
        row = cur.fetchone()
        return dict(row) if row is not None else None


def _render_strategy(row: dict[str, Any]) -> str:
    params = row.get("params")
    params_text = (
        json.dumps(params, sort_keys=True, default=str)
        if isinstance(params, (dict, list))
        else str(params)
    )
    return "\n".join(
        [
            f"strategy {row.get('candidate_hash')}",
            f"  params: {params_text}",
            f"  train_sharpe: {_fmt(row.get('train_sharpe'))}",
            f"  vault_sharpe: {_fmt(row.get('vault_sharpe'))}",
            f"  vault_holds: {row.get('vault_holds')} "
            f"deployment_eligible: {row.get('deployment_eligible')}",
        ]
    )


# ------------------------------------------------------------------------- kb


def _kb_line(entry: Any) -> str:
    """One human line per recall hit; unknown shapes fall back to JSON/str."""
    if isinstance(entry, dict):
        for key in ("text", "content", "summary"):
            value = entry.get(key)
            if value:
                return str(value)
        return json.dumps(entry, default=str)
    return str(entry)


# -------------------------------------------------------------------- reports


def _daily_report(data: DashboardData) -> str:
    pnl = data.pnl_series()
    lines = ["Daily report"]
    if pnl.empty:
        lines.append("  pnl: no pnl_daily rows (DB offline?)")
    else:
        last = pnl.iloc[-1]
        day_pl = _num(last["realized_pl"]) + _num(last["unrealized_pl"])
        lines.append(
            f"  {last['d']}: equity={_num(last['equity']):,.2f} "
            f"day P&L={day_pl:+,.2f}"
        )
    lines.append(f"  open positions: {len(data.positions())}")
    lines.append(f"  today's orders: {_orders_today(data.recent_orders())}")
    return "\n".join(lines)


def _weekly_report(data: DashboardData) -> str:
    pnl = data.pnl_series()
    report = data.attribution()
    lines = ["Weekly report"]
    if pnl.empty:
        lines.append("  pnl: no pnl_daily rows (DB offline?)")
    else:
        window = pnl.tail(_WEEKLY_SESSIONS)
        first, last = window.iloc[0], window.iloc[-1]
        delta = _num(last["equity"]) - _num(first["equity"])
        lines.append(
            f"  last {len(window)} sessions: equity "
            f"{_num(first['equity']):,.2f} -> {_num(last['equity']):,.2f} "
            f"({delta:+,.2f})"
        )
    lines.append(
        f"  realized P&L: {report.total_pl:+,.2f} "
        f"over {report.n_round_trips} round trips"
    )
    lines.append(_top_lines("by regime", report.by_regime))
    lines.append(_top_lines("by ticker", report.by_ticker))
    return "\n".join(lines)


def _orders_today(orders: pd.DataFrame) -> int:
    """Count of order rows stamped today (UTC); 0 on an empty/typed-empty frame."""
    if orders.empty:
        return 0
    ts = pd.to_datetime(orders["ts"], utc=True, errors="coerce")
    today = pd.Timestamp.now(tz="UTC").date()
    return int((ts.dt.date == today).sum())


def _top_lines(name: str, mapping: dict[str, float]) -> str:
    if not mapping:
        return f"  {name}: (none)"
    top = sorted(mapping.items(), key=lambda kv: kv[1], reverse=True)[:_TOP_N]
    return f"  {name}: " + ", ".join(f"{key} {value:+,.2f}" for key, value in top)


# -------------------------------------------------------------------- helpers


def _num(value: Any) -> float:
    """Defensive float: None / non-numeric → 0.0 (a report must never raise)."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _fmt(value: Any) -> str:
    """Two-decimal sharpe, or 'n/a' when the registry column is NULL."""
    return "n/a" if value is None else f"{float(value):.2f}"
