"""Convergence report — fail-closed go/no-go for real capital (Phase-6 Task 7).

The load-bearing property under test: readiness can NEVER pass vacuously. Any
input that was not measured FAILS its criterion, so `ConvergenceInputs()` (all
None) must produce a report that is not ready with every criterion explicitly
"not yet measured".
"""

from __future__ import annotations

import dataclasses

from services.trader.ops.convergence import (
    MESO_REGIME_LABELS,
    NOT_MEASURED,
    ConvergenceInputs,
    ConvergenceReport,
    Criterion,
    evaluate,
    render_markdown,
)

_GENERATED = "2026-07-06"


def _all_pass_inputs() -> ConvergenceInputs:
    """Production-shaped inputs that clear every threshold."""
    return ConvergenceInputs(
        deployment_eligible=[
            {
                "candidate_hash": "abc123",
                "vault_holds": True,
                "deployment_eligible": True,
                "vault_sharpe": 1.4,
            },
        ],
        replay_years=5.2,
        regime_coverage={
            "trending_low_vol": 0.40,
            "trending_high_vol": 0.10,
            "ranging_low_vol": 0.35,
            "ranging_high_vol": 0.15,
        },
        kb_facts=250,
        paper_days=31,
        paper_sharpe=1.3,
    )


def _by_name(report: ConvergenceReport) -> dict[str, Criterion]:
    return {c.name: c for c in report.criteria}


# --- all-pass -----------------------------------------------------------------


def test_all_pass_inputs_are_ready() -> None:
    report = evaluate(_all_pass_inputs(), generated=_GENERATED)
    assert report.ready is True
    assert report.generated == _GENERATED
    assert len(report.criteria) == 6
    for criterion in report.criteria:
        assert criterion.passed is True, criterion.name
        assert criterion.rationale.strip() != "", criterion.name
        assert criterion.threshold.strip() != "", criterion.name
        assert criterion.measured != NOT_MEASURED, criterion.name


def test_report_dataclasses_are_frozen() -> None:
    report = evaluate(_all_pass_inputs(), generated=_GENERATED)
    assert dataclasses.is_dataclass(ConvergenceInputs)
    for obj in (report, report.criteria[0], _all_pass_inputs()):
        assert obj.__dataclass_params__.frozen  # type: ignore[attr-defined]


# --- fail-closed (the review lesson) -------------------------------------------


def test_all_none_inputs_fail_closed() -> None:
    """ConvergenceInputs() with nothing measured -> NOT ready, every criterion
    explicitly 'not yet measured'. Readiness can never pass vacuously."""
    report = evaluate(ConvergenceInputs(), generated=_GENERATED)
    assert report.ready is False
    assert len(report.criteria) == 6
    for criterion in report.criteria:
        assert criterion.passed is False, criterion.name
        assert criterion.measured == NOT_MEASURED, criterion.name


def test_missing_paper_stats_fail_their_criteria_and_block_readiness() -> None:
    inputs = dataclasses.replace(_all_pass_inputs(), paper_days=None, paper_sharpe=None)
    report = evaluate(inputs, generated=_GENERATED)
    assert report.ready is False
    by_name = _by_name(report)
    assert by_name["paper_window"].passed is False
    assert by_name["paper_window"].measured == NOT_MEASURED
    assert by_name["paper_sharpe"].passed is False
    assert by_name["paper_sharpe"].measured == NOT_MEASURED
    # Everything that WAS measured still passes — the failure is isolated.
    for name in ("deployment_eligible_strategy", "replay_depth", "regime_coverage", "kb_depth"):
        assert by_name[name].passed is True, name


# --- per-criterion thresholds ---------------------------------------------------


def test_partial_regime_coverage_fails() -> None:
    """One MESO regime at 2% of bars (< 5%) -> coverage criterion fails."""
    inputs = dataclasses.replace(
        _all_pass_inputs(),
        regime_coverage={
            "trending_low_vol": 0.50,
            "trending_high_vol": 0.02,  # under-represented
            "ranging_low_vol": 0.33,
            "ranging_high_vol": 0.15,
        },
    )
    report = evaluate(inputs, generated=_GENERATED)
    assert report.ready is False
    coverage = _by_name(report)["regime_coverage"]
    assert coverage.passed is False
    assert "trending_high_vol" in coverage.measured


def test_missing_regime_label_fails_coverage() -> None:
    """A MESO label absent from the coverage map counts as 0% -> fail."""
    inputs = dataclasses.replace(
        _all_pass_inputs(),
        regime_coverage={"trending_low_vol": 0.60, "ranging_low_vol": 0.40},
    )
    report = evaluate(inputs, generated=_GENERATED)
    assert _by_name(report)["regime_coverage"].passed is False


def test_no_vault_holding_strategy_fails() -> None:
    """Registry rows exist but none holds on the vault -> criterion fails."""
    inputs = dataclasses.replace(
        _all_pass_inputs(),
        deployment_eligible=[{"candidate_hash": "x", "vault_holds": False}],
    )
    report = evaluate(inputs, generated=_GENERATED)
    assert _by_name(report)["deployment_eligible_strategy"].passed is False
    assert report.ready is False


def test_replay_years_below_three_fails() -> None:
    inputs = dataclasses.replace(_all_pass_inputs(), replay_years=2.5)
    report = evaluate(inputs, generated=_GENERATED)
    assert _by_name(report)["replay_depth"].passed is False


def test_kb_facts_below_hundred_fails() -> None:
    inputs = dataclasses.replace(_all_pass_inputs(), kb_facts=99)
    report = evaluate(inputs, generated=_GENERATED)
    assert _by_name(report)["kb_depth"].passed is False


def test_paper_sharpe_must_strictly_exceed_one() -> None:
    """Sharpe exactly 1.0 fails: the threshold is > 1.0, not >=."""
    inputs = dataclasses.replace(_all_pass_inputs(), paper_sharpe=1.0)
    report = evaluate(inputs, generated=_GENERATED)
    assert _by_name(report)["paper_sharpe"].passed is False


def test_paper_days_below_thirty_fails() -> None:
    inputs = dataclasses.replace(_all_pass_inputs(), paper_days=29)
    report = evaluate(inputs, generated=_GENERATED)
    assert _by_name(report)["paper_window"].passed is False


# --- renderer -------------------------------------------------------------------


def test_render_markdown_contains_every_criterion_and_human_gate_note() -> None:
    report = evaluate(_all_pass_inputs(), generated=_GENERATED)
    md = render_markdown(report)
    for criterion in report.criteria:
        assert criterion.name in md
        assert criterion.threshold in md
    assert _GENERATED in md
    assert "READY" in md
    # A passing report is NECESSARY but not sufficient — the flip is human-gated.
    assert "human sign-off" in md.lower()


def test_render_markdown_not_ready_verdict() -> None:
    report = evaluate(ConvergenceInputs(), generated=_GENERATED)
    md = render_markdown(report)
    assert "NOT READY" in md
    assert NOT_MEASURED in md


def test_meso_labels_are_the_four_quadrants() -> None:
    assert set(MESO_REGIME_LABELS) == {
        "trending_low_vol",
        "trending_high_vol",
        "ranging_low_vol",
        "ranging_high_vol",
    }
