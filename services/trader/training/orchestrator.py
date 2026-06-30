"""orchestrator.py — the seven-role multi-step dispatch loop (Phase-3 Layer-3, Task 12).

Headless Python realization of the seven-role amendment §4 dispatch surface:

    Planner.propose_queue
      for each hypothesis:
        halt.is_halted()        -> stop, halted=True
        Reviewer.check          -> blocked? reviewed_out++, do-not-repeat, continue
        (Hunter) eval.evaluate  -> FitnessReport
        Guardian.review         -> vetoed? vetoed++, (catastrophic -> halt+break), continue
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

from dataclasses import dataclass

import pandas as pd

from services.trader.ops.halt import HaltControl
from services.trader.training import eval as kernel_eval
from services.trader.training.parse_metric import FitnessReport, report_from_eval
from services.trader.training.promote import promote_pipeline
from services.trader.training.provenance import candidate_hash
from services.trader.training.roles import (
    Guardian,
    Planner,
    Reviewer,
    strategy_params,
)
from services.trader.training.strategy_template import RegimeConditionalStrategy


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
        current = RegimeConditionalStrategy.seed()
        proposed = reviewed_out = vetoed = recorded = promoted = 0
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
                reviewed_out += 1
                if self.notebook is not None:
                    self.notebook.mark_do_not_repeat(h, decision.reason)
                continue

            # Hunter step (in-process eval — see module ponytail note).
            ev = kernel_eval.evaluate(hypothesis, self.price, self.regimes)
            report: FitnessReport = report_from_eval(ev, strategy_params(hypothesis))

            verdict = self.guardian.review(report)
            if not verdict.approved:
                vetoed += 1
                if verdict.halt:
                    self.halt.halt(verdict.reason)
                    halted = True
                    break
                continue

            # promote: real Postgres compare-and-set when a DSN is set; otherwise the
            # iteration is still counted as recorded (the summary tallies in-memory).
            if self.dsn is not None:
                result = promote_pipeline(self.dsn, self.run_id, recorded, report)
                if result.promoted:
                    promoted += 1
            elif report.promoted:
                promoted += 1
            recorded += 1

            # Archivist: notebook + Hindsight (both optional / graceful-offline).
            if self.notebook is not None:
                self.notebook.record(report, self.run_id, recorded - 1)
            if self.hindsight is not None:
                self.hindsight.retain(
                    f"iteration {h}: fitness={report.fitness:.4f} "
                    f"promoted={report.promoted} reason={report.reason}",
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
