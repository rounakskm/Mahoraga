#!/usr/bin/env python3
"""Mahoraga ops dashboard — Streamlit shell over `DashboardData` (Phase-6 Task 6).

Run:

    uv run --with streamlit streamlit run scripts/dashboard.py

Layout:
    sidebar   — the kill switch: a big red HALT button (trips
                `HaltControl.halt("dashboard operator halt")`) and a RESUME
                button (clears it). Streamlit reruns the script on click, so
                the new halt state is visible on the very next render —
                comfortably inside the <10s kill-switch contract.
    main area — halt banner (when halted), MESO regime metric, positions
                table, recent orders table, P&L equity line chart
                (`trades.pnl_daily`), fleet activity table, KB recent list,
                and realized-P&L attribution tables.

Structure: ALL panel data comes from `DashboardData` (the pure, graceful-
offline data layer — nothing under services/ imports streamlit); the pure
builders here (`build_panels`, `attribution_tables`) are importable and
testable WITHOUT streamlit installed, because `import streamlit` happens
lazily inside `main()`. Each panel is built inside its own try/except so one
failing panel renders as an inline error instead of blanking the page.

Env (read via `os.environ.get`, never required — every panel degrades):
    ALPACA_API_KEY / ALPACA_SECRET_KEY — live paper positions via the broker.
    ALPACA_PAPER_ENDPOINT — paper trading REST base (default paper-api).
    MAHORAGA_DSN — Postgres DSN for trades/experiments panels.
    MAHORAGA_HINDSIGHT_URL — Hindsight memory endpoint for the KB panel.
    MAHORAGA_HALT_FLAG — kill-switch flag path override (see ops/halt.py).
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from pathlib import Path

import pandas as pd

# scripts/ is not a package; when launched via `streamlit run` the repo root
# may not be on sys.path, so anchor it here before the services imports.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from services.trader.ops.attribution import AttributionReport  # noqa: E402
from services.trader.ops.dashboard_data import DashboardData  # noqa: E402

_DEFAULT_ENDPOINT = "https://paper-api.alpaca.markets/v2"

# Panel name -> DashboardData method, in render order.
PANEL_KEYS: tuple[str, ...] = (
    "halt",
    "regime",
    "positions",
    "orders",
    "pnl",
    "fleet",
    "kb",
    "attribution",
)


# ------------------------------------------------------------- pure builders


def build_panels(data: DashboardData) -> dict[str, object]:
    """One entry per dashboard panel, keyed by `PANEL_KEYS`.

    Every panel is built inside its own try/except: a failing panel yields
    `{"error": str}` for that key and leaves every other panel intact — one
    bad data source must never blank the whole page.
    """
    builders: dict[str, Callable[[], object]] = {
        "halt": data.halt_status,
        "regime": data.regime_now,
        "positions": data.positions,
        "orders": data.recent_orders,
        "pnl": data.pnl_series,
        "fleet": data.fleet_activity,
        "kb": data.kb_recent,
        "attribution": data.attribution,
    }
    panels: dict[str, object] = {}
    for name, build in builders.items():
        try:
            panels[name] = build()
        except Exception as exc:  # panel isolation — see docstring
            panels[name] = {"error": str(exc)}
    return panels


def attribution_tables(report: AttributionReport) -> dict[str, pd.DataFrame]:
    """One small two-column DataFrame per attribution breakdown."""
    breakdowns: dict[str, dict[str, float]] = {
        "by_regime": report.by_regime,
        "by_ticker": report.by_ticker,
        "by_side": report.by_side,
        "by_holding_period": report.by_holding_period,
    }
    return {
        name: pd.DataFrame(
            [{"bucket": bucket, "realized_pl": pl} for bucket, pl in mapping.items()],
            columns=["bucket", "realized_pl"],
        )
        for name, mapping in breakdowns.items()
    }


# ------------------------------------------------------------------- wiring


def _build_data() -> DashboardData:
    """One `DashboardData` from env: Alpaca broker when both keys are present
    (mirrors `scripts/run_paper.py::_broker`), Hindsight when its URL is set
    (mirrors `scripts/run_intel.py::_hindsight`), DSN when configured. Heavy
    imports stay lazy so the pure builders import without those extras."""
    broker = None
    key = os.environ.get("ALPACA_API_KEY")
    secret = os.environ.get("ALPACA_SECRET_KEY")
    if key and secret:
        from services.trader.execution.alpaca_broker import AlpacaBrokerClient

        broker = AlpacaBrokerClient(
            key=key,
            secret=secret,
            endpoint=os.environ.get("ALPACA_PAPER_ENDPOINT", _DEFAULT_ENDPOINT),
        )
    hindsight = None
    hindsight_url = os.environ.get("MAHORAGA_HINDSIGHT_URL")
    if hindsight_url:
        from services.trader.training.hindsight_client import HindsightClient

        hindsight = HindsightClient(hindsight_url)
    return DashboardData(
        dsn=os.environ.get("MAHORAGA_DSN"),
        broker=broker,
        hindsight=hindsight,
    )


# ---------------------------------------------------------------- app shell


def main() -> None:
    """The Streamlit app. The ONLY place streamlit is imported (lazily), so
    everything above stays importable and testable without it."""
    import streamlit as st

    st.set_page_config(page_title="Mahoraga Ops", layout="wide")

    data = _build_data()
    halt = data.halt

    # Sidebar — the kill switch. type="primary" renders streamlit's red
    # accent (#FF4B4B by default): the big red HALT button.
    with st.sidebar:
        st.header("Kill switch")
        if st.button("HALT", type="primary", use_container_width=True):
            halt.halt("dashboard operator halt")
        if st.button("RESUME", use_container_width=True):
            halt.resume()
        st.caption(f"flag: {halt.flag_path}")

    panels = build_panels(data)

    def errored(name: str) -> bool:
        panel = panels[name]
        if isinstance(panel, dict) and "error" in panel:
            st.warning(f"{name} panel unavailable: {panel['error']}")
            return True
        return False

    # Halt banner — always first, above the title.
    if not errored("halt") and panels["halt"]["halted"]:
        reason = panels["halt"]["reason"] or "no reason recorded"
        st.error(f"TRADING HALTED — {reason}")

    st.title("Mahoraga Ops")

    if not errored("regime"):
        regime = panels["regime"]
        label = regime.get("label", "unavailable") if regime else "unavailable"
        asof = regime.get("asof", "") if regime else ""
        st.metric("MESO regime", label, help=f"as of {asof}" if asof else None)

    st.subheader("Positions")
    if not errored("positions"):
        st.dataframe(panels["positions"], use_container_width=True)

    st.subheader("Recent orders")
    if not errored("orders"):
        st.dataframe(panels["orders"], use_container_width=True)

    st.subheader("P&L (daily equity)")
    if not errored("pnl"):
        pnl = panels["pnl"]
        if pnl.empty:
            st.caption("no pnl_daily rows yet")
        else:
            st.line_chart(pnl.set_index("d")["equity"])

    st.subheader("Fleet activity")
    if not errored("fleet"):
        st.dataframe(panels["fleet"], use_container_width=True)

    st.subheader("KB recent")
    if not errored("kb"):
        kb = panels["kb"]
        if not kb:
            st.caption("no Hindsight results (set MAHORAGA_HINDSIGHT_URL)")
        for item in kb:
            st.write(item)

    st.subheader("Attribution (realized P&L)")
    if not errored("attribution"):
        report = panels["attribution"]
        st.metric("Total realized P&L", f"{report.total_pl:,.2f}")
        st.caption(f"{report.n_round_trips} round trips")
        tables = attribution_tables(report)
        for column, (name, frame) in zip(st.columns(len(tables)), tables.items(), strict=True):
            with column:
                st.caption(name)
                st.dataframe(frame, use_container_width=True)


if __name__ == "__main__":
    main()
