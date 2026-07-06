"""Convergence report (Phase-6 Task 7) — the real-capital go/no-go artifact.

Evaluates the Phase-7 gate criteria (vault-holding strategy, replay depth, MESO
regime coverage, KB depth, paper-trading window + Sharpe) into a per-criterion
pass/fail report with documented rationale.

FAIL-CLOSED is the load-bearing rule (review lesson): every field on
`ConvergenceInputs` is optional, and a `None` input means "not yet measured" —
which FAILS that criterion. Readiness can never pass vacuously because a data
source was down or a measurement was skipped.

This module is pure: no I/O, no clocks. `generated` is caller-supplied (the
repo's replay-safe convention — library code never reads wall-clock time, so
the same inputs always produce byte-identical reports and the evaluator is
usable inside replayed history). Input gathering lives in
`scripts/convergence_report.py`.

A PASSING report is NECESSARY but NOT SUFFICIENT for live capital: the final
flip to real money is a human sign-off (CLAUDE.md critical sequencing rule).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

# The four MESO quadrants (trending/ranging x low/high vol) from
# `services/trader/regime/meso.py`; `undefined` warmup bars are excluded from
# coverage on purpose — they carry no regime information.
MESO_REGIME_LABELS: Final[tuple[str, ...]] = (
    "trending_low_vol",
    "trending_high_vol",
    "ranging_low_vol",
    "ranging_high_vol",
)

# Sentinel for an input that was never gathered. Fail-closed: it fails the criterion.
NOT_MEASURED: Final[str] = "not yet measured"

# --- DEFAULT_THRESHOLDS ---------------------------------------------------------
# Each threshold carries its rationale; together they resolve the phase-6 open
# question "what is good enough to gate Phase 7?" (spec §7).

# >=1 strategy that is deployment-eligible AND holds on the vault holdout. The
# vault (last-6-months embargo) is the only data the loop has never seen; a
# strategy that survives it is the minimum proof the edge is not overfit.
MIN_VAULT_HOLDING_STRATEGIES: Final[int] = 1

# >=3 years of replayed history. Covers at least one full market cycle segment
# with multiple regime transitions; less than that and the loop has only
# "experienced" a single environment.
MIN_REPLAY_YEARS: Final[float] = 3.0

# Every MESO quadrant >=5% of bars. Below ~5% a regime contributes too few bars
# for its conditional parameters to be anything but noise — the system would be
# flying blind the next time that regime shows up live.
MIN_REGIME_FRACTION: Final[float] = 0.05

# >=100 Hindsight facts. A KB thinner than this hasn't accumulated enough
# Experience/World Facts for recall to shape decisions; 100 is roughly one
# fact per replayed week over the minimum 3-year span.
MIN_KB_FACTS: Final[int] = 100

# >=30 calendar days of paper trading. One full options-expiry/monthly cycle of
# live-market microstructure (halts, gaps, partial fills) through the real
# broker path — the Phase-5 operational window.
MIN_PAPER_DAYS: Final[int] = 30

# Paper Sharpe strictly >1.0. Risk-adjusted return must beat a naive
# buy-and-hold-grade baseline before real capital; 1.0 exactly is not enough —
# transaction costs and slippage at real size only subtract from here.
MIN_PAPER_SHARPE: Final[float] = 1.0

DEFAULT_THRESHOLDS: Final[dict[str, float | int]] = {
    "min_vault_holding_strategies": MIN_VAULT_HOLDING_STRATEGIES,
    "min_replay_years": MIN_REPLAY_YEARS,
    "min_regime_fraction": MIN_REGIME_FRACTION,
    "min_kb_facts": MIN_KB_FACTS,
    "min_paper_days": MIN_PAPER_DAYS,
    "min_paper_sharpe": MIN_PAPER_SHARPE,
}


@dataclass(frozen=True)
class ConvergenceInputs:
    """Everything the gate measures. All fields optional: `None` = not yet
    measured, which fails that criterion (fail-closed)."""

    # `strategies.registry` rows (dicts with at least `vault_holds`).
    deployment_eligible: list[dict] | None = None
    # Span of replayed history, in years.
    replay_years: float | None = None
    # MESO label -> fraction of bars carrying that label (0..1).
    regime_coverage: dict[str, float] | None = None
    # Hindsight fact count (or a documented proxy for it).
    kb_facts: int | None = None
    # Paper-trading window length (calendar days) and its Sharpe.
    paper_days: int | None = None
    paper_sharpe: float | None = None


@dataclass(frozen=True)
class Criterion:
    name: str
    passed: bool
    measured: str
    threshold: str
    rationale: str


@dataclass(frozen=True)
class ConvergenceReport:
    criteria: list[Criterion] = field(default_factory=list)
    ready: bool = False
    generated: str = ""  # caller-supplied date string; the library never reads a clock


def _strategy_criterion(rows: list[dict] | None) -> Criterion:
    threshold = f">={MIN_VAULT_HOLDING_STRATEGIES} deployment-eligible strategy with vault_holds"
    rationale = (
        "The vault holdout is the only never-seen data; surviving it is the "
        "minimum evidence the edge is not overfit to the training window."
    )
    if rows is None:
        return Criterion("deployment_eligible_strategy", False, NOT_MEASURED, threshold, rationale)
    holding = sum(1 for r in rows if r.get("vault_holds"))
    return Criterion(
        "deployment_eligible_strategy",
        holding >= MIN_VAULT_HOLDING_STRATEGIES,
        f"{holding} vault-holding of {len(rows)} registry rows",
        threshold,
        rationale,
    )


def _replay_criterion(years: float | None) -> Criterion:
    threshold = f">={MIN_REPLAY_YEARS:g} years"
    rationale = (
        "Fewer than ~3 replayed years means the loop has experienced only a "
        "single market environment and too few regime transitions."
    )
    if years is None:
        return Criterion("replay_depth", False, NOT_MEASURED, threshold, rationale)
    return Criterion(
        "replay_depth", years >= MIN_REPLAY_YEARS, f"{years:.1f} years", threshold, rationale
    )


def _coverage_criterion(coverage: dict[str, float] | None) -> Criterion:
    threshold = f"all 4 MESO regimes each >={MIN_REGIME_FRACTION:.0%} of bars"
    rationale = (
        "A regime under ~5% of bars has too few observations for its "
        "conditional parameters to be signal rather than noise."
    )
    if coverage is None:
        return Criterion("regime_coverage", False, NOT_MEASURED, threshold, rationale)
    fractions = {label: float(coverage.get(label, 0.0)) for label in MESO_REGIME_LABELS}
    measured = ", ".join(f"{label}={frac:.1%}" for label, frac in fractions.items())
    passed = all(frac >= MIN_REGIME_FRACTION for frac in fractions.values())
    return Criterion("regime_coverage", passed, measured, threshold, rationale)


def _kb_criterion(facts: int | None) -> Criterion:
    threshold = f">={MIN_KB_FACTS} facts"
    rationale = (
        "Below ~100 facts the KB is too thin for recall to meaningfully shape "
        "decisions; ~one fact per replayed week over the minimum span."
    )
    if facts is None:
        return Criterion("kb_depth", False, NOT_MEASURED, threshold, rationale)
    return Criterion("kb_depth", facts >= MIN_KB_FACTS, f"{facts} facts", threshold, rationale)


def _paper_window_criterion(days: int | None) -> Criterion:
    threshold = f">={MIN_PAPER_DAYS} days"
    rationale = (
        "One full monthly cycle of live-market microstructure through the real "
        "broker path (the Phase-5 operational window)."
    )
    if days is None:
        return Criterion("paper_window", False, NOT_MEASURED, threshold, rationale)
    return Criterion(
        "paper_window", days >= MIN_PAPER_DAYS, f"{days} days", threshold, rationale
    )


def _paper_sharpe_criterion(sharpe: float | None) -> Criterion:
    threshold = f">{MIN_PAPER_SHARPE:g} (strict)"
    rationale = (
        "Costs and slippage at real size only subtract from paper performance, "
        "so exactly 1.0 is not enough margin."
    )
    if sharpe is None:
        return Criterion("paper_sharpe", False, NOT_MEASURED, threshold, rationale)
    return Criterion(
        "paper_sharpe", sharpe > MIN_PAPER_SHARPE, f"{sharpe:.2f}", threshold, rationale
    )


def evaluate(inputs: ConvergenceInputs, *, generated: str) -> ConvergenceReport:
    """Evaluate every gate criterion. Fail-closed: any `None` input fails its
    criterion with `measured="not yet measured"`; `ready` requires ALL passes."""
    criteria = [
        _strategy_criterion(inputs.deployment_eligible),
        _replay_criterion(inputs.replay_years),
        _coverage_criterion(inputs.regime_coverage),
        _kb_criterion(inputs.kb_facts),
        _paper_window_criterion(inputs.paper_days),
        _paper_sharpe_criterion(inputs.paper_sharpe),
    ]
    return ConvergenceReport(
        criteria=criteria,
        ready=all(c.passed for c in criteria),
        generated=generated,
    )


def render_markdown(report: ConvergenceReport) -> str:
    """Render the report as Markdown: criteria table, verdict, and the human-gate
    note (a passing report is necessary, never sufficient, for real capital)."""
    verdict = "READY" if report.ready else "NOT READY"
    lines = [
        f"# Convergence Report — {report.generated}",
        "",
        f"**Verdict: {verdict}** — real-capital gate "
        f"({sum(c.passed for c in report.criteria)}/{len(report.criteria)} criteria passed)",
        "",
        "> **A passing report is NECESSARY but NOT SUFFICIENT.** The final flip to",
        "> real capital is a **human sign-off** (CLAUDE.md critical sequencing rule).",
        "> No automated process may act on this verdict alone.",
        "",
        "| Criterion | Measured | Threshold | Pass |",
        "|---|---|---|---|",
    ]
    for c in report.criteria:
        mark = "PASS" if c.passed else "FAIL"
        lines.append(f"| {c.name} | {c.measured} | {c.threshold} | {mark} |")
    lines += ["", "## Rationale", ""]
    lines += [f"- **{c.name}** — {c.rationale}" for c in report.criteria]
    lines += [
        "",
        "Unmeasured inputs fail closed: a criterion marked "
        f'"{NOT_MEASURED}" counts as a FAIL, never a skip.',
        "",
    ]
    return "\n".join(lines)
