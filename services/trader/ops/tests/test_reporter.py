"""Reporter — fleet status from Postgres or injected rows (Task 13)."""

from __future__ import annotations

from services.trader.ops.reporter import FleetStatus, Reporter


def test_offline_reporter_returns_empty_status() -> None:
    r = Reporter(dsn=None)
    status = r.status()
    assert isinstance(status, FleetStatus)
    assert status.active == 0
    assert status.completed == 0
    assert status.failures == 0
    assert status.leader_per_regime == {}
    assert status.anomalies == []


def test_render_is_a_non_empty_string_when_offline() -> None:
    rendered = Reporter(dsn=None).status().render()
    assert isinstance(rendered, str)
    assert rendered.strip() != ""


def test_status_from_injected_rows_counts_and_picks_leaders() -> None:
    rows = [
        # regime, candidate_hash, fitness, status, reason
        {"regime": "trending_low_vol", "candidate_hash": "a", "fitness": 0.40,
         "status": "completed", "reason": "promoted"},
        {"regime": "trending_low_vol", "candidate_hash": "b", "fitness": 0.90,
         "status": "completed", "reason": "promoted"},  # leader for this regime
        {"regime": "ranging_high_vol", "candidate_hash": "c", "fitness": 0.55,
         "status": "completed", "reason": "promoted"},
        {"regime": "ranging_high_vol", "candidate_hash": "d", "fitness": 0.10,
         "status": "failed", "reason": "fortress rejected"},
        {"regime": "trending_low_vol", "candidate_hash": "e", "fitness": 0.20,
         "status": "active", "reason": "running"},
    ]
    status = Reporter(dsn=None).status(rows=rows)
    assert status.completed == 3  # three completed rows
    assert status.failures == 1  # one failed row
    assert status.active == 1  # one active row
    # leader_per_regime: best fitness candidate per regime
    assert status.leader_per_regime["trending_low_vol"] == "b"
    assert status.leader_per_regime["ranging_high_vol"] == "c"


def test_status_render_includes_counts() -> None:
    rows = [
        {"regime": "trending_low_vol", "candidate_hash": "a", "fitness": 0.4,
         "status": "completed", "reason": "promoted"},
    ]
    rendered = Reporter(dsn=None).status(rows=rows).render()
    assert "completed" in rendered.lower()
    assert "trending_low_vol" in rendered
