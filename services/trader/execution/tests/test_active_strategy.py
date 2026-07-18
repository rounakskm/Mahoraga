"""Tests for the conductor's auto-adopt selection over `strategies.registry`.

Fully OFFLINE by default (injected `rows` + a tmp state file); the one DSN-gated
end-to-end test skips when `MAHORAGA_DSN` is unset. A DDL cross-check asserts the
columns the selection SQL reads actually exist in 005_experiments.sql — so a
schema drift breaks a fast unit test, not a live paper cycle.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from services.trader.execution.active_strategy import (
    ActiveStrategy,
    select_active_strategy,
    write_active,
)

_PARAMS = {
    "windows": {
        "trending_low_vol": 20,
        "trending_high_vol": 150,
        "ranging_low_vol": 70,
        "ranging_high_vol": 30,
    },
    "adx_threshold": 25.0,
    "vol_threshold": 18.0,
}


def _row(
    candidate_hash: str,
    *,
    vault_sharpe: float | None,
    train_sharpe: float | None = 1.0,
    deployment_eligible: bool = True,
    params: dict | None = None,
) -> dict:
    """A registry-row-shaped dict (mirrors 005_experiments.sql columns)."""
    return {
        "candidate_hash": candidate_hash,
        "params": params if params is not None else _PARAMS,
        "train_sharpe": train_sharpe,
        "vault_sharpe": vault_sharpe,
        "deployment_eligible": deployment_eligible,
    }


# ---------------------------------------------------------------------------
# select_active_strategy — injected rows (offline)
# ---------------------------------------------------------------------------


def test_selects_highest_vault_sharpe_eligible_row() -> None:
    rows = [
        _row("aaa", vault_sharpe=1.2),
        _row("bbb", vault_sharpe=2.5),  # best vault Sharpe
        _row("ccc", vault_sharpe=0.9),
    ]
    strat = select_active_strategy(None, rows=rows)
    assert strat is not None
    assert strat == ActiveStrategy(
        candidate_hash="bbb",
        params=_PARAMS,
        train_sharpe=1.0,
        vault_sharpe=2.5,
    )


def test_skips_non_deployment_eligible_rows() -> None:
    rows = [
        _row("aaa", vault_sharpe=9.9, deployment_eligible=False),  # higher, but not eligible
        _row("bbb", vault_sharpe=1.1, deployment_eligible=True),
    ]
    strat = select_active_strategy(None, rows=rows)
    assert strat is not None
    assert strat.candidate_hash == "bbb"
    assert strat.vault_sharpe == 1.1


def test_null_vault_sharpe_sorts_last_then_train_sharpe() -> None:
    # No vault_sharpe on either eligible row -> NULLS LAST, tie broken by train_sharpe DESC.
    rows = [
        _row("aaa", vault_sharpe=None, train_sharpe=0.5),
        _row("bbb", vault_sharpe=None, train_sharpe=1.8),
    ]
    strat = select_active_strategy(None, rows=rows)
    assert strat is not None
    assert strat.candidate_hash == "bbb"
    assert strat.vault_sharpe is None
    assert strat.train_sharpe == 1.8


def test_real_vault_sharpe_beats_null_vault_sharpe() -> None:
    rows = [
        _row("aaa", vault_sharpe=None, train_sharpe=99.0),  # huge train, but no vault
        _row("bbb", vault_sharpe=0.1, train_sharpe=0.1),  # tiny, but vault-validated
    ]
    strat = select_active_strategy(None, rows=rows)
    assert strat is not None
    assert strat.candidate_hash == "bbb"


def test_empty_rows_returns_none() -> None:
    assert select_active_strategy(None, rows=[]) is None


def test_no_eligible_rows_returns_none() -> None:
    rows = [_row("aaa", vault_sharpe=5.0, deployment_eligible=False)]
    assert select_active_strategy(None, rows=rows) is None


def test_none_dsn_no_rows_is_graceful_none() -> None:
    # No DSN and no injected rows -> graceful None (never touches psycopg).
    assert select_active_strategy(None) is None


# ---------------------------------------------------------------------------
# DDL cross-check — the queried columns exist in 005_experiments.sql
# ---------------------------------------------------------------------------


def test_selected_columns_exist_in_ddl() -> None:
    ddl = (
        Path(__file__).resolve().parents[4]
        / "infra"
        / "postgres"
        / "migrations"
        / "005_experiments.sql"
    ).read_text(encoding="utf-8")
    # Scope the check to the registry table body so we don't accidentally match
    # a same-named column on experiments.iterations.
    registry_ddl = ddl.split("strategies.registry", 1)[1]
    for column in (
        "candidate_hash",
        "params",
        "train_sharpe",
        "vault_sharpe",
        "deployment_eligible",
    ):
        assert column in registry_ddl, f"{column} missing from strategies.registry DDL"


# ---------------------------------------------------------------------------
# write_active — round-trips through run_paper._load_artifact
# ---------------------------------------------------------------------------


def _load_run_paper():  # noqa: ANN202 (importlib file-path loader; scripts/ isn't a package)
    import importlib.util  # noqa: PLC0415

    run_paper_path = (
        Path(__file__).resolve().parents[4] / "scripts" / "run_paper.py"
    )
    spec = importlib.util.spec_from_file_location("run_paper_undertest", run_paper_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_write_active_round_trips_through_load_artifact(tmp_path: Path) -> None:
    strat = ActiveStrategy(
        candidate_hash="deadbeef",
        params=_PARAMS,
        train_sharpe=1.4,
        vault_sharpe=2.1,
    )
    out = tmp_path / "strategies" / "active.json"
    returned = write_active(strat, out_path=out)

    # write_active returns the params (the artifact shape).
    assert returned == _PARAMS

    # The existing artifact loader reads it as a plain dict artifact.
    run_paper = _load_run_paper()
    artifact = run_paper._load_artifact(out)
    assert artifact["windows"] == _PARAMS["windows"]
    assert artifact["adx_threshold"] == _PARAMS["adx_threshold"]
    assert artifact["vol_threshold"] == _PARAMS["vol_threshold"]

    # Provenance is carried alongside the params in the on-disk file.
    on_disk = json.loads(out.read_text(encoding="utf-8"))
    assert on_disk["candidate_hash"] == "deadbeef"
    assert on_disk["vault_sharpe"] == 2.1


# ---------------------------------------------------------------------------
# DSN-gated end-to-end select (skips locally / in CI without a seeded DB)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not os.environ.get("MAHORAGA_DSN"),
    reason="requires MAHORAGA_DSN pointing at a Postgres with a seeded registry row",
)
def test_select_active_strategy_live_dsn() -> None:
    strat = select_active_strategy(os.environ["MAHORAGA_DSN"])
    # Either there is a deployment-eligible row (well-formed) or there is none.
    if strat is not None:
        assert isinstance(strat.candidate_hash, str) and strat.candidate_hash
        assert isinstance(strat.params, dict)
        assert "windows" in strat.params


# ---------------------------------------------------------------------------
# Audit-handoff dedup — a changed candidate_hash audits once; unchanged is silent
# ---------------------------------------------------------------------------


def _strat(candidate_hash: str, vault_sharpe: float | None = 1.5) -> ActiveStrategy:
    return ActiveStrategy(
        candidate_hash=candidate_hash,
        params=_PARAMS,
        train_sharpe=1.0,
        vault_sharpe=vault_sharpe,
    )


def test_audit_adoption_records_on_change(tmp_path: Path) -> None:
    run_paper = _load_run_paper()
    state = tmp_path / "control" / "active_strategy.txt"

    # First adoption (no prior state) -> recorded; state file now holds the hash.
    recorded = run_paper._audit_adoption(_strat("hash-a"), None, state_path=state)
    assert recorded is True
    assert state.read_text(encoding="utf-8").strip() == "hash-a"


def test_audit_adoption_dedups_unchanged_hash(tmp_path: Path) -> None:
    run_paper = _load_run_paper()
    state = tmp_path / "control" / "active_strategy.txt"

    assert run_paper._audit_adoption(_strat("hash-a"), None, state_path=state) is True
    # Re-adopting the SAME hash -> no new audit event, state unchanged.
    assert run_paper._audit_adoption(_strat("hash-a"), None, state_path=state) is False
    assert state.read_text(encoding="utf-8").strip() == "hash-a"


def test_audit_adoption_records_again_on_new_hash(tmp_path: Path) -> None:
    run_paper = _load_run_paper()
    state = tmp_path / "control" / "active_strategy.txt"

    assert run_paper._audit_adoption(_strat("hash-a"), None, state_path=state) is True
    # A DIFFERENT hash -> a fresh adoption is recorded and the state advances.
    assert run_paper._audit_adoption(_strat("hash-b"), None, state_path=state) is True
    assert state.read_text(encoding="utf-8").strip() == "hash-b"
