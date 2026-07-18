"""orchestrator.py — the seven-role multi-step dispatch loop (Phase-3 Layer-3, Task 12).

Headless Python realization of the seven-role amendment §4 dispatch surface:

    (refresh_master -> starting strategy, seed() fallback)
    Planner.propose_queue
      for each hypothesis:
        halt.is_halted()        -> stop, halted=True
        Reviewer.check          -> blocked? reviewed_out++, do-not-repeat, continue
        (Hunter) eval.evaluate  -> FitnessReport
        Guardian.review         -> vetoed? vetoed++, RECORD the iteration
                                   (promote_pipeline + notebook) + do-not-repeat,
                                   (catastrophic -> halt+break), continue
        promote_pipeline / count-as-recorded   recorded++ (+promoted++ if promoted)
        Archivist: notebook.record + hindsight.retain

Every role is injectable (the defaults construct the real ones) so the loop runs
deterministically offline. Every external dependency degrades gracefully — the
substrate-portability + graceful-offline contracts from CLAUDE.md:

- `dsn=None`   -> skip the Postgres promote write, but STILL count the iteration as
  recorded (the CadenceSummary tallies in-memory; promoted stays False without a DB).
- `hindsight=None` -> no grounding / no retain.
- `notebook=None`  -> no markdown writes.
- `halt` is the file-flag kill-switch, polled at the top of EVERY hypothesis so a
  halt takes effect within one iteration (<10s).

The domain code never imports Hermes (CLAUDE.md rule 7); the Hermes subagent `.md`
defs call this Orchestrator from the substrate side.

# ponytail: the per-hypothesis Hunter step calls `eval.evaluate` in-process rather
# than `worker.run_in_worktree`. The worktree gives FILESYSTEM isolation for parallel
# Hunter dispatch; the unit orchestrator is single-threaded, so in-process eval is
# deterministic and fast. Swap in `run_in_worktree` only when this loop fans out to
# parallel workers (then the worktree isolation actually buys something).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import pandas as pd

from services.trader.ops.halt import HaltControl
from services.trader.training import eval as kernel_eval
from services.trader.training.parse_metric import FitnessReport, report_from_eval
from services.trader.training.promote import promote_pipeline
from services.trader.training.provenance import candidate_hash
from services.trader.training.refresh_master import refresh_master
from services.trader.training.roles import (
    Guardian,
    Planner,
    Reviewer,
    strategy_params,
)
from services.trader.training.strategy_template import RegimeConditionalStrategy

logger = logging.getLogger(__name__)

_REGIME_KEYS = (
    "trending_low_vol",
    "trending_high_vol",
    "ranging_low_vol",
    "ranging_high_vol",
)


def _strategy_from_params(params: dict) -> RegimeConditionalStrategy:
    """Reconstruct a strategy from registry params. Accepts both shapes the
    registry has stored: nested (`{"windows": {...}, "adx_threshold": ...}`, the
    run_autoresearch artifact shape) and flat (`strategy_params`-style: the 4
    regime keys + thresholds at the top level)."""
    raw = params.get("windows") or {k: params[k] for k in _REGIME_KEYS if k in params}
    if not raw:
        raise ValueError(f"no regime windows in master params: {sorted(params)}")
    windows = {k: int(v) for k, v in raw.items()}
    kwargs: dict = {}
    if "adx_threshold" in params:
        kwargs["adx_threshold"] = float(params["adx_threshold"])
    if "vol_threshold" in params:
        kwargs["vol_threshold"] = float(params["vol_threshold"])
    return RegimeConditionalStrategy(windows, **kwargs)


@dataclass(frozen=True)
class CadenceSummary:
    """The tally of one cadence run — what the Reporter renders to Telegram."""

    cadence: str
    proposed: int
    reviewed_out: int
    vetoed: int
    recorded: int
    promoted: int
    halted: bool


class Orchestrator:
    """Mahoraga's primary assistant: drives one cadence of the seven-role loop."""

    def __init__(
        self,
        price: pd.Series,
        regimes: pd.Series,
        *,
        dsn: str | None = None,
        run_id: str = "cadence",
        hindsight=None,
        planner=None,
        reviewer=None,
        guardian=None,
        notebook=None,
        halt=None,
    ) -> None:
        self.price = price
        self.regimes = regimes
        self.dsn = dsn
        self.run_id = run_id
        self.hindsight = hindsight
        self.planner = planner or Planner(hindsight)
        self.reviewer = reviewer or Reviewer()
        self.guardian = guardian or Guardian()
        self.notebook = notebook
        self.halt = halt or HaltControl()

    def run_cadence(
        self,
        cadence: str,
        iterations: int = 3,
        seed: int = 0,
        *,
        regime_label: str = "trending_low_vol",
    ) -> CadenceSummary:
        """Run one cadence: Planner queue -> per-hypothesis dispatch -> summary.

        Aborts the moment `halt.is_halted()` (checked at the top of each hypothesis)
        or when Guardian trips its catastrophic-drawdown halt; both return a summary
        with `halted=True`.
        """
        current = self._starting_strategy()
        proposed = reviewed_out = vetoed = recorded = promoted = 0
        iteration_idx = 0  # every persisted row (recorded OR vetoed) gets its own
        halted = False
        recent_hashes: set[str] = set()

        queue = self.planner.propose_queue(
            current, regime_label, iterations, seed=seed
        )
        proposed = len(queue)

        for hypothesis in queue:
            # Kill-switch: polled FIRST every hypothesis (<10s halt).
            if self.halt.is_halted():
                halted = True
                break

            h = candidate_hash(strategy_params(hypothesis))

            decision = self.reviewer.check(hypothesis, current, recent_hashes)
            recent_hashes.add(h)
            if not decision.approved:
                # Pre-eval rejection: no FitnessReport to record, but the
                # do-not-repeat loop still closes (notebook + Hindsight fact).
                reviewed_out += 1
                self._mark_do_not_repeat(h, decision.reason, cadence)
                continue

            # Hunter step (in-process eval — see module ponytail note).
            ev = kernel_eval.evaluate(hypothesis, self.price, self.regimes)
            report: FitnessReport = report_from_eval(ev, strategy_params(hypothesis))

            verdict = self.guardian.review(report)
            if not verdict.approved:
                # A discarded candidate is still evidence: record the iteration
                # (Postgres + notebook) AND close the do-not-repeat loop.
                vetoed += 1
                self._persist(report, iteration_idx)
                iteration_idx += 1
                self._mark_do_not_repeat(h, verdict.reason, cadence)
                if verdict.halt:
                    self.halt.halt(verdict.reason)
                    halted = True
                    break
                continue

            if self._persist(report, iteration_idx):
                promoted += 1
            iteration_idx += 1
            recorded += 1

            # Archivist: Hindsight Experience Fact (optional / graceful-offline).
            # NOTE: the text MUST be a natural-language sentence — Hindsight's
            # fact-extractor yields 0 facts from terse "key=value" strings, so a
            # cryptic summary would store but never become recallable knowledge
            # (verified 2026-07-18). Write it the way a human analyst would.
            if self.hindsight is not None:
                verdict = "was promoted" if report.promoted else "was rejected"
                self.hindsight.retain(
                    f"During the {cadence} autoresearch cadence, strategy candidate "
                    f"{h} {verdict} with a fitness score of {report.fitness:.4f}. "
                    f"The evaluation verdict was: {report.reason}.",
                    {"candidate_hash": h, "run_id": self.run_id, "cadence": cadence},
                )

        return CadenceSummary(
            cadence=cadence,
            proposed=proposed,
            reviewed_out=reviewed_out,
            vetoed=vetoed,
            recorded=recorded,
            promoted=promoted,
            halted=halted,
        )

    # --- helpers -------------------------------------------------------------

    def _starting_strategy(self) -> RegimeConditionalStrategy:
        """The promoted master from the registry when a DSN is set (so a cadence
        continues from the deployment-best, not from scratch); `seed()` when there
        is no DSN, no master yet, or the refresh fails (graceful-offline)."""
        if self.dsn is not None:
            try:
                params = refresh_master(self.dsn)
                if params:
                    return _strategy_from_params(params)
            except Exception as exc:
                logger.warning("refresh_master failed; starting from seed(): %s", exc)
        return RegimeConditionalStrategy.seed()

    def _persist(self, report: FitnessReport, iteration: int) -> bool:
        """Record one evaluated candidate: Postgres promote_pipeline (when a DSN
        is set) + notebook. Returns whether the candidate was promoted.

        A provenance-write failure (Postgres down, exhausted serialization
        retries) degrades gracefully: the iteration stays counted in-memory, the
        failure is logged, and the cadence never crashes.
        """
        promoted = False
        if self.dsn is not None:
            try:
                result = promote_pipeline(self.dsn, self.run_id, iteration, report)
                promoted = result.promoted
            except Exception as exc:
                logger.warning(
                    "provenance write failed (iteration recorded in-memory only): %s",
                    exc,
                )
        elif report.promoted:
            promoted = True
        if self.notebook is not None:
            self.notebook.record(report, self.run_id, iteration)
        return promoted

    def _mark_do_not_repeat(self, h: str, reason: str, cadence: str) -> None:
        """Close the do-not-repeat loop for a rejected/vetoed candidate: notebook
        entry + a Hindsight fact the Planner's `_forbidden_hashes` recall matches
        (text starts with "do-not-repeat"; `candidate_hash` in the metadata)."""
        if self.notebook is not None:
            self.notebook.mark_do_not_repeat(h, reason)
        if self.hindsight is not None:
            self.hindsight.retain(
                f"do-not-repeat {h}: {reason}",
                {"candidate_hash": h, "run_id": self.run_id, "cadence": cadence},
            )
