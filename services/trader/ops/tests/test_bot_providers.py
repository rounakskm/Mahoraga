"""Tests for bot_providers — the real read-only providers behind TelegramOps.

Everything runs offline: DB rows are injected through the ``rows`` params that
`DashboardData` already exposes, Hindsight is a stub, and the registry lookup
takes injected rows. The graceful-offline contract is asserted directly — an
all-`None` `DashboardData` must render typed-empty messages, never raise.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from services.trader.ops import bot_providers
from services.trader.ops.bot_providers import _registry_lookup, build_providers
from services.trader.ops.dashboard_data import DashboardData

# --------------------------------------------------------------------- stubs


class _StubData(DashboardData):
    """DashboardData with injectable panel data (no DB / parquet / Hindsight)."""

    def __init__(
        self,
        *,
        regime: dict[str, str] | None = None,
        kb: list[dict] | None = None,
        pnl_rows: list[dict[str, Any]] | None = None,
        order_rows: list[dict[str, Any]] | None = None,
        position_rows: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__()  # all-None constructor: offline everywhere
        self._regime = regime or {}
        self._kb = kb or []
        self._pnl_rows = pnl_rows or []
        self._order_rows = order_rows or []
        self._position_rows = position_rows or []

    def regime_now(self) -> dict[str, str]:
        return dict(self._regime)

    def kb_recent(self, k: int = 10) -> list[dict]:
        return list(self._kb)[:k]

    def pnl_series(self, rows: list[dict[str, Any]] | None = None) -> pd.DataFrame:
        return super().pnl_series(rows=self._pnl_rows)

    def recent_orders(
        self, limit: int = 50, rows: list[dict[str, Any]] | None = None
    ) -> pd.DataFrame:
        return super().recent_orders(limit=limit, rows=self._order_rows)

    def positions(self, rows: list[dict[str, Any]] | None = None) -> pd.DataFrame:
        return super().positions(rows=self._position_rows)


def _offline_data(tmp_path: Path) -> DashboardData:
    """A truly offline DashboardData: no DSN, no Hindsight, no SPY parquet."""
    data = DashboardData()
    data._spy_parquet_dir = tmp_path / "no-parquet-here"
    return data


_REGISTRY_ROWS: list[dict[str, Any]] = [
    {
        "candidate_hash": "abc123def456",
        "params": {"trend_up": {"window": 20}},
        "train_sharpe": 1.42,
        "vault_sharpe": 0.87,
        "vault_holds": True,
        "deployment_eligible": True,
    },
    {
        "candidate_hash": "ffff00001111",
        "params": {"chop": {"window": 5}},
        "train_sharpe": 0.3,
        "vault_sharpe": None,
        "vault_holds": False,
        "deployment_eligible": False,
    },
]


# ------------------------------------------------------------ build_providers


def test_build_providers_returns_the_four_telegramops_kwargs(tmp_path: Path) -> None:
    providers = build_providers(_offline_data(tmp_path))
    assert set(providers) == {
        "regime_provider",
        "strategy_provider",
        "kb_provider",
        "report_provider",
    }
    assert all(callable(p) for p in providers.values())


# ------------------------------------------------------------ regime_provider


def test_regime_provider_offline_renders_unavailable(tmp_path: Path) -> None:
    providers = build_providers(_offline_data(tmp_path))
    assert providers["regime_provider"]() == "regime: unavailable (no local SPY data)"


def test_regime_provider_renders_label_and_transition_line() -> None:
    data = _StubData(regime={"label": "trend_up", "asof": "2026-07-10T00:00:00"})
    reply = build_providers(data)["regime_provider"]()
    assert "regime: trend_up" in reply
    assert "2026-07-10" in reply
    # Empty feature row -> the predictor's middling default toward the same label.
    assert "transition risk: 40% toward trend_up (rules)" in reply


def test_regime_provider_survives_a_raising_transition_predictor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Boom:
        def __init__(self, *args: object, **kwargs: object) -> None:
            raise RuntimeError("predictor exploded")

    monkeypatch.setattr(bot_providers, "TransitionPredictor", _Boom)
    data = _StubData(regime={"label": "trend_up", "asof": "2026-07-10T00:00:00"})
    reply = build_providers(data)["regime_provider"]()
    assert "regime: trend_up" in reply  # the regime line still renders
    assert "transition risk" not in reply  # the transition line is omitted


# ---------------------------------------------------------- strategy_provider


def test_registry_lookup_matches_by_hash_prefix_with_injected_rows() -> None:
    row = _registry_lookup(None, "abc123", rows=_REGISTRY_ROWS)
    assert row is not None
    assert row["candidate_hash"] == "abc123def456"
    assert _registry_lookup(None, "zzzz", rows=_REGISTRY_ROWS) is None


def test_registry_lookup_without_dsn_or_rows_returns_none() -> None:
    assert _registry_lookup(None, "abc123") is None


def test_strategy_provider_without_dsn_says_registry_unavailable(
    tmp_path: Path,
) -> None:
    providers = build_providers(_offline_data(tmp_path), dsn=None)
    reply = providers["strategy_provider"]("abc123")
    assert "unavailable" in reply
    assert "MAHORAGA_DSN" in reply


def test_strategy_provider_renders_params_and_sharpes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        bot_providers,
        "_registry_lookup",
        lambda dsn, prefix, rows=None: _REGISTRY_ROWS[0],
    )
    providers = build_providers(_offline_data(tmp_path), dsn="postgresql://stub")
    reply = providers["strategy_provider"]("abc123")
    assert "abc123def456" in reply
    assert "trend_up" in reply  # params rendered
    assert "train_sharpe: 1.42" in reply
    assert "vault_sharpe: 0.87" in reply
    assert "deployment_eligible: True" in reply


def test_strategy_provider_not_found_is_a_clear_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        bot_providers, "_registry_lookup", lambda dsn, prefix, rows=None: None
    )
    providers = build_providers(_offline_data(tmp_path), dsn="postgresql://stub")
    reply = providers["strategy_provider"]("zzzz")
    assert "zzzz" in reply
    assert "not found" in reply


# ---------------------------------------------------------------- kb_provider


def test_kb_provider_renders_entries_one_per_line() -> None:
    data = _StubData(
        kb=[{"text": "learned about momentum"}, {"content": "vol spike observed"}]
    )
    reply = build_providers(data)["kb_provider"]()
    lines = reply.splitlines()
    assert len(lines) == 2
    assert "learned about momentum" in lines[0]
    assert "vol spike observed" in lines[1]


def test_kb_provider_empty_says_hindsight_offline(tmp_path: Path) -> None:
    providers = build_providers(_offline_data(tmp_path))
    assert providers["kb_provider"]() == "KB: no recent entries (Hindsight offline?)"


# ------------------------------------------------------------ report_provider


def test_report_daily_renders_equity_positions_and_orders() -> None:
    today = pd.Timestamp.now(tz="UTC")
    data = _StubData(
        pnl_rows=[
            {"d": "2026-07-09", "equity": 99000.0, "realized_pl": -50.0, "unrealized_pl": 0.0},
            {"d": "2026-07-10", "equity": 100250.0, "realized_pl": 200.0, "unrealized_pl": 50.0},
        ],
        position_rows=[
            {
                "ticker": "SPY",
                "qty": 10,
                "avg_entry": 500.0,
                "market_value": 5050.0,
                "unrealized_pl": 50.0,
            }
        ],
        order_rows=[
            {
                "ts": today,
                "ticker": "SPY",
                "side": "BUY",
                "qty": 10,
                "filled_qty": 10,
                "status": "FILLED",
                "filled_avg_price": 500.0,
                "reason": "signal",
            }
        ],
    )
    reply = build_providers(data)["report_provider"]("daily")
    assert "100,250.00" in reply  # last equity
    assert "+250.00" in reply  # day P&L = realized + unrealized
    assert "open positions: 1" in reply
    assert "today's orders: 1" in reply


def test_report_weekly_renders_pnl_summary_and_attribution_top_lines() -> None:
    pnl_rows = [
        {"d": f"2026-07-0{i}", "equity": 100000.0 + i * 100, "realized_pl": 0.0, "unrealized_pl": 0.0}
        for i in range(1, 7)
    ]
    order_rows = [
        {
            "ts": pd.Timestamp("2026-07-01 14:30", tz="UTC"),
            "ticker": "SPY",
            "side": "BUY",
            "qty": 10,
            "filled_qty": 10,
            "status": "FILLED",
            "filled_avg_price": 500.0,
            "reason": "signal",
        },
        {
            "ts": pd.Timestamp("2026-07-02 14:30", tz="UTC"),
            "ticker": "SPY",
            "side": "SELL",
            "qty": 10,
            "filled_qty": 10,
            "status": "FILLED",
            "filled_avg_price": 510.0,
            "reason": "signal",
        },
    ]
    data = _StubData(pnl_rows=pnl_rows, order_rows=order_rows)
    reply = build_providers(data)["report_provider"]("weekly")
    # Last-5 window: 100200 -> 100600.
    assert "100,200.00" in reply
    assert "100,600.00" in reply
    assert "+400.00" in reply
    # Attribution top-lines: one SPY long round trip, +100 realized.
    assert "by regime" in reply
    assert "by ticker" in reply
    assert "SPY" in reply
    assert "+100.00" in reply
    assert "1 round trip" in reply


def test_report_provider_offline_renders_typed_empty_never_raises(
    tmp_path: Path,
) -> None:
    providers = build_providers(_offline_data(tmp_path))
    for kind in ("daily", "weekly"):
        reply = providers["report_provider"](kind)
        assert "no pnl_daily rows" in reply
    assert "open positions: 0" in providers["report_provider"]("daily")


# ----------------------------------------------------- TelegramOps end-to-end


def test_providers_plug_into_telegramops_handle(tmp_path: Path) -> None:
    from services.trader.ops.halt import HaltControl
    from services.trader.ops.reporter import Reporter
    from services.trader.ops.telegram import TelegramOps

    data = _StubData(regime={"label": "chop", "asof": "2026-07-10T00:00:00"})
    ops = TelegramOps(
        HaltControl(tmp_path / "halt.flag"),
        Reporter(None),
        token=None,
        **build_providers(data),
    )
    assert "regime: chop" in ops.handle("/regime")
    assert "Hindsight offline" in ops.handle("/kb")
    assert "no pnl_daily rows" in ops.handle("/report daily")
