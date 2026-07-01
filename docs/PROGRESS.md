# Mahoraga — Progress

Single source of "where are we". Updated as work lands on `main`. Detail lives in
the per-phase specs + `docs/measurements/*-exit-verification.md`.

**Last updated:** 2026-06 (Phase-3 Layer-1 provenance slice)

## Phase status

| Phase | What | Status |
|---|---|---|
| 0 | Substrate bring-up (compose, Postgres, LiteLLM, sandbox) | ✅ complete |
| — | **Substrate migration** — OpenClaw → **Hermes**, NVIDIA Nemotron inference, **Hindsight memory** (Hermes proven using it) | ✅ complete |
| 1 | Data + features + regime detector + backtest harness | ✅ complete (`phase-1-complete`) |
| 2 | **Anti-overfitting fortress** — 4 walls + 3 gates, RiskLabAI, real-SPY calibration | ✅ complete (`phase-2-complete`) |
| 3 | **Autoresearch loop** — the self-improving core | ✅ **Layers 1–3 built & proven on real SPY** (fleet runs; replay walks ~5yr; exit-criteria sign-off pending: nightly-8h + DSN race test) |
| 4 | News / sentiment intelligence (MICRO lens) | ✅ **built & proven on live Alpaca news** — full-spec build; 169 real SPY items classified, real PIT sentiment feature; [plan](superpowers/specs/phase-4-intelligence-layer/plan.md) + [tasks](superpowers/specs/phase-4-intelligence-layer/tasks.md) |
| 5 | Broker integration (paper) | ⚪ not started |
| 6 | Live capital + ops (dashboard, Telegram) | ⚪ not started |
| 7 | Full autonomous operation | ⚪ not started |

## Phase 3 — layer detail (the heart of the system)

Spec: [`superpowers/specs/phase-3-autoresearch-loop/spec.md`](superpowers/specs/phase-3-autoresearch-loop/spec.md).
The loop learns **two coupled things**: how to read the market **regime**, and which
**regime-conditional** strategy works + how to apply it. Goal: adapt to any market
condition, year-over-year profit.

### Layer 1 — runnable headless kernel (mechanical, no LLM)
| Piece | Status | PR |
|---|---|---|
| `strategy_template` (regime-conditional) + `eval` (wall metadata contract) + `loop` (mechanical hill-climb) + runner + live progress | ✅ | #49 #50 |
| Real Phase-1 **MESO regime detector** in the loop (ADX + realized-vol) | ✅ | #52 |
| **Vault-holdout** validation (train/vault split — the deployment gate) | ✅ | #54 |
| **Provenance** — `experiments.iterations` (Postgres) + `strategies` registry | ✅ | this slice |

**Layer-1 exit:** unattended run produces ≥N candidates on real SPY, records all of
them (kept + discarded + reason + vault verdict), promotes only fortress-passers,
and the promoted best holds on the untouched vault. Run it:
`uv run python scripts/run_autoresearch.py --iterations 50`
([runbook](runbooks/autoresearch-training.md)).

### Layer 2 — LLM mutator + learnable detector ✅
- ✅ **LLM mutator** — Nemotron proposes regime-conditional mutations (`--llm`;
  `LLMMutator` calls NVIDIA Build / LiteLLM, validates the JSON, safety-falls-back
  to the mechanical mutation on any failure).
- ✅ **Detector-as-mutation-target** — the candidate carries the MESO thresholds
  (ADX, vol-pct); `--learn-detector` makes them a mutation target so the loop learns
  *both* how to detect regimes and how to trade them. Self-corrects the Phase-1
  vol-pct mis-scaling without touching Phase-1. The LLM tunes thresholds too when
  `--llm --learn-detector` are combined (thresholds clamped, not rejected).

### Layer 3 — research fleet ✅ built & proven (PRs #60–#66)
The seven-role fleet wrapping the working kernel, built in 5 parallel waves (17 tasks,
[plan.md](superpowers/specs/phase-3-autoresearch-loop/plan.md) / [tasks.md](superpowers/specs/phase-3-autoresearch-loop/tasks.md)):
- **Orchestrator** (`orchestrator.py`) — the multi-step dispatch: Planner→Reviewer→
  (Hunter eval)→Guardian→promote→Archivist→Reporter; polls the halt flag every step.
- **Planner / Reviewer / Guardian** (`roles.py`) — injectable-LLM, Hindsight-grounded,
  deterministic offline. Guardian passes the **fortress verdict** through (veto a
  non-promoted candidate); the catastrophic-loss kill-switch is a *live* concern
  (Phase 5+ on realized P&L), **not** a backtest-drawdown trip.
- **Tools** — `promote_pipeline` (SERIALIZABLE race-free atomic promote vs
  `strategies.master`), `refresh_master`, `parse_metric`, `worker` (git-worktree
  isolation), `replay` (PIT-clamped compressed-history clock + leak canary),
  `notebook` (regenerable markdown ledger), `hindsight_client` (retain/recall/reflect),
  `VaultValidator` (in-sample-vs-vault tolerance).
- **Ops** — `HaltControl` file-flag kill-switch, `Reporter` fleet status, `TelegramOps`
  `/halt`-`/resume`-`/status`.
- **Substrate** — 7 Hermes subagent defs (`infra/nemoclaw/subagents/`) + a CI
  permission-scope guard. Domain code never imports Hermes (CLAUDE.md rule 7).

**Proven end-to-end on real SPY (2,882 bars, 2015→2026):** a nightly cadence ran
8 iterations through the full fleet; a **replay cadence walked 42 steps across ~5 years**
(2020→2025), PIT-clamped. The Guardian veto-rate tracks market stress — heavy vetoes in
the 2020 COVID crash and 2022 bear, near-zero in the 2023–25 bull — i.e. the fleet is
demonstrably **regime-sensitive**, exactly the thesis. Run it:
`uv run python scripts/run_autoresearch.py --fleet --cadence replay --iterations 3`.

**Remaining for the formal Layer-3 exit sign-off** (amendment §7), not blockers to
Phase 4: an unattended nightly-8h run (≥50 iters), the DSN-backed race-on-promote test
in CI's integration-smoke (already wired, runs on the fresh CI DB), and Hindsight-recall
latency under a live bank.

## Phase 4 — intelligence layer ✅ built & proven (PRs #67–#72)

The MICRO lens + real-time intelligence, built in 5 waves (13 tasks,
[plan.md](superpowers/specs/phase-4-intelligence-layer/plan.md) / [tasks.md](superpowers/specs/phase-4-intelligence-layer/tasks.md)):
- **News pipeline** — `AlpacaNewsClient` (real archive fetch + live-stream stub),
  `NewsClassifier` (fast local lexicon → CRITICAL/MATERIAL/BACKGROUND + sentiment ∈
  [-1,1]; FinBERT optional), macro connectors (SEC EDGAR, Fed RSS, CME FedWatch).
- **Real sentiment** — `SentimentFeature` replaces the Phase-1 placeholder with a PIT
  sentiment series (leak-canary-tested); `SentimentAggregator` (15-min rolling +
  Hindsight World Facts).
- **MICRO lens** — `MicroLens` (momentum/reversal/shock) fills `CompositeRegime.micro`
  from sentiment + roc_3/roc_5 + volume_surge + realized_vol.
- **Intelligence** — `TransitionPredictor` (rules + Hindsight-learned overlay),
  `WebResearcher` (weekly macro brief → Hindsight Mental Model, egress-allowlisted),
  `ArchivistSynthesis` (Hindsight L2 weekly / L3 monthly).
- **News-shock protocol** — a CRITICAL item trips the Layer-3 kill-switch (`HaltControl`)
  + tightened stops + 10-min hold, within seconds.

**Proven on LIVE Alpaca news:** `run_intel.py ingest` classified **169 real SPY items**
(18 CRITICAL / 35 MATERIAL / 116 BACKGROUND) and the real `SentimentFeature` produced a
genuine PIT score series varying across [-1,1] over the news flow — the MICRO lens now
reads real sentiment. Run it: `uv run python scripts/run_intel.py ingest --symbols SPY --start 2024-03-01`.

**Remaining for the formal Phase-4 exit sign-off** (spec §3), not Phase-5 blockers: live
news-websocket reconnect under load, the 15-min aggregation cadence on a running clock,
and Hindsight L2/L3 entries accumulating under a live bank.

## Current focus

**Phases 1–4 built & proven.** The self-improving fleet trains on ~5 years of real SPY
regimes and now reads **real news sentiment** (live Alpaca). **Next: Phase 5** — broker
integration in **PAPER mode** (Alpaca paper account is live: ACTIVE, $100k paper) behind
the architectural hard-risk-limit firewall. Capital risk begins at Phase 5 in *paper*
only; **real-capital go-live remains a human gate** (convergence report + explicit
sign-off), per CLAUDE.md — the build will stop there for review.
