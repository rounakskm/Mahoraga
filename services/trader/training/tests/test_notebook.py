"""Notebook: the canonical markdown ledger.

`.record()` writes a per-candidate `experiments/<hash>.md` and appends a `notes.md`
line; `.mark_do_not_repeat()` appends to `do-not-repeat.md`; `.regenerate_from_postgres`
rebuilds `notes.md` deterministically from a rows source (tested with an injected
`rows` list, no live Postgres).

`parse_metric.FitnessReport` is built by a sibling task; this module forked before it
merged. `importorskip` makes this file skip cleanly in isolation and run post-merge.
The injected-rows formatter test below does NOT depend on parse_metric and always runs.
"""

from __future__ import annotations

import pytest

from services.trader.training.notebook import Notebook


def test_regenerate_from_injected_rows_is_deterministic(tmp_path):
    """The formatter is testable without a live DB: pass rows directly."""
    nb = Notebook(tmp_path)
    rows = [
        {"run_id": "r1", "iteration": 0, "candidate_hash": "aaaa",
         "fitness": 0.5, "sharpe": 1.2, "promoted": True, "reason": "promoted"},
        {"run_id": "r1", "iteration": 1, "candidate_hash": "bbbb",
         "fitness": 0.3, "sharpe": 0.8, "promoted": False, "reason": "fortress rejected"},
    ]
    nb.regenerate_from_postgres(dsn=None, rows=rows)
    out = (tmp_path / "notes.md").read_text()
    assert "aaaa" in out and "bbbb" in out
    assert "fortress rejected" in out
    # deterministic: same input -> identical file
    nb.regenerate_from_postgres(dsn=None, rows=rows)
    assert (tmp_path / "notes.md").read_text() == out


def test_mark_do_not_repeat_appends(tmp_path):
    nb = Notebook(tmp_path)
    nb.mark_do_not_repeat("deadbeef", "degenerate all-flat windows")
    out = (tmp_path / "do-not-repeat.md").read_text()
    assert "deadbeef" in out and "degenerate all-flat windows" in out


def test_record_writes_experiment_and_appends_notes(tmp_path):
    pytest.importorskip("services.trader.training.parse_metric")
    from services.trader.training.parse_metric import FitnessReport

    report = FitnessReport(
        candidate_hash="cafef00d",
        params={"trending_low_vol": 100},
        sharpe=1.5,
        fitness=0.7,
        quarterly_win_rate=0.6,
        max_drawdown=-0.08,
        promoted=True,
        reason="promoted (fitness 0.7000 > -inf)",
    )
    nb = Notebook(tmp_path)
    nb.record(report, run_id="r2", iteration=4)

    exp = (tmp_path / "experiments" / "cafef00d.md").read_text()
    assert "0.7" in exp and "promoted" in exp and "cafef00d" in exp
    notes = (tmp_path / "notes.md").read_text()
    assert "cafef00d" in notes and "r2" in notes
