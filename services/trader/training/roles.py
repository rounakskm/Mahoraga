"""Research-fleet roles (Phase-3 Layer-3): Planner / Reviewer / Guardian.

Three substrate-independent roles that wrap the kernel's search. Each follows the
injectable-LLM + deterministic-fallback contract of `llm.LLMMutator`: constructors
take `llm=None` / `hindsight=None`, and with `None` they run pure deterministic
logic and never raise. The Hermes `.md` defs (infra/nemoclaw/subagents/) call these
classes — the domain code itself never imports Hermes (CLAUDE.md rule 7).

- Planner proposes a queue of distinct single-change hypotheses, grounded in
  Hindsight's `do-not-repeat` memory (recall drops already-failed candidates).
- Reviewer is the pure hard-rule gate before any compute is spent: exactly one
  change vs the master, no duplicate, windows in range.
- Guardian is the fortress's veto authority for the training loop: it passes the
  fortress verdict through (veto a non-promoted candidate, approve a promoted one).
  It does NOT halt on a candidate's *backtest* drawdown — a backtested strategy
  drawing down 10% over years is normal (SPY itself drew down ~34% in 2020), not a
  live catastrophe. The catastrophic-loss kill-switch (CLAUDE.md hard limit: 10%
  *monthly realized* drawdown -> human review) is a LIVE-execution concern
  (Phase 5+), fired by the execution monitor on realized P&L via `ops.halt`, not by
  a backtest metric here. This matches spec §0 re-grounding 3 (Guardian's checks are
  the metadata-driven walls, not a separate drawdown trip).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from services.trader.training.parse_metric import FitnessReport
from services.trader.training.provenance import candidate_hash
from services.trader.training.strategy_template import (
    WINDOW_MAX,
    WINDOW_MIN,
    RegimeConditionalStrategy,
)


@dataclass(frozen=True)
class Decision:
    """A role's verdict on a hypothesis or a report."""

    approved: bool
    reason: str
    halt: bool = False


def strategy_params(s: RegimeConditionalStrategy) -> dict:
    """Full mutation surface of a candidate as a flat hashable dict (windows +
    detector thresholds), so a window OR a threshold change yields a distinct
    `candidate_hash`."""
    return {
        **s.windows,
        "adx_threshold": s.adx_threshold,
        "vol_threshold": s.vol_threshold,
    }


def _forbidden_hashes(hindsight, regime_label: str, k: int) -> set[str]:
    """Candidate hashes Hindsight has already filed under `do-not-repeat`."""
    if hindsight is None or not hindsight.is_enabled():
        return set()
    results = hindsight.recall(f"do-not-repeat {regime_label}", k=k)
    return {
        r["candidate_hash"]
        for r in results
        if isinstance(r, dict) and "candidate_hash" in r
    }


class Planner:
    """Proposes the next batch of hypotheses. Mechanical `mutate` fallback when
    `llm=None`; Hindsight `do-not-repeat` recall prunes known-dead candidates."""

    def __init__(self, hindsight=None, llm=None) -> None:
        self.hindsight = hindsight
        self.llm = llm

    def propose_queue(
        self,
        current: RegimeConditionalStrategy,
        regime_label: str,
        n: int = 3,
        seed: int = 0,
    ) -> list[RegimeConditionalStrategy]:
        """`n` DISTINCT single-change hypotheses, each differing from `current` by
        exactly one window/threshold, none in the `do-not-repeat` set."""
        forbidden = _forbidden_hashes(self.hindsight, regime_label, k=max(n * 4, 5))
        rng = np.random.default_rng(seed)
        seen = {candidate_hash(strategy_params(current))}
        queue: list[RegimeConditionalStrategy] = []
        # Bounded attempts: the mutation surface is small but finite; cap so a
        # saturated surface (everything forbidden/seen) returns what it can.
        for _ in range(n * 64):
            if len(queue) >= n:
                break
            cand = self._mutate(current, rng)
            h = candidate_hash(strategy_params(cand))
            if h in seen or h in forbidden:
                continue
            seen.add(h)
            queue.append(cand)
        return queue

    def _mutate(
        self, current: RegimeConditionalStrategy, rng: np.random.Generator
    ) -> RegimeConditionalStrategy:
        if self.llm is not None:
            return self.llm(current, rng)
        return current.mutate(rng)


class Reviewer:
    """Pure hard-rule gate on a hypothesis — runs before any compute is spent."""

    def check(
        self,
        hypothesis: RegimeConditionalStrategy,
        current: RegimeConditionalStrategy,
        recent_hashes: set[str],
    ) -> Decision:
        changes = sum(
            1
            for r in current.windows
            if hypothesis.windows.get(r) != current.windows.get(r)
        )
        changes += int(hypothesis.adx_threshold != current.adx_threshold)
        changes += int(hypothesis.vol_threshold != current.vol_threshold)
        if changes != 1:
            return Decision(False, f"reject: expected exactly one change, got {changes}")
        if any(
            not (WINDOW_MIN <= w <= WINDOW_MAX) for w in hypothesis.windows.values()
        ):
            return Decision(
                False, f"reject: a window is outside [{WINDOW_MIN},{WINDOW_MAX}]"
            )
        h = candidate_hash(strategy_params(hypothesis))
        if h in recent_hashes:
            return Decision(False, f"reject: duplicate of a recent candidate ({h})")
        return Decision(True, "approved: single in-range change, not a duplicate")


class Guardian:
    """Fortress veto authority for the training loop. Passes the fortress verdict
    through: veto a non-promoted candidate, approve a promoted one. `gates` is
    accepted for parity with the rest of the fleet but the verdict (incl. the Risk
    gate's drawdown check) is already baked into the report. Guardian does NOT halt
    on backtest drawdown — the live catastrophic-loss kill-switch is fired by the
    Phase-5+ execution monitor on realized P&L, not here. The `Decision.halt` field
    stays so an operator/live path can still set it."""

    def __init__(self, gates=None) -> None:
        self.gates = gates

    def review(self, report: FitnessReport) -> Decision:
        if not report.promoted:
            return Decision(False, f"veto: {report.reason}")
        return Decision(True, report.reason)
