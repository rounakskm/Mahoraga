# Phase 3 Amendment — Seven-Role Subagent Decomposition

**Status:** Approved 2026-05-03
**Type:** Phase-level amendment (extends the consolidated-assistant model to a finer-grained role split)
**Anchor specs (revised by this document):**
- [`2026-04-26-architecture-revision-consolidated-assistant.md`](2026-04-26-architecture-revision-consolidated-assistant.md) — §3 extended (3 → 7 subagents)
- [`2026-04-25-nemoclaw-autoresearch-integration.md`](2026-04-25-nemoclaw-autoresearch-integration.md) — §4.5, §6.4 partially superseded
- [`phase-3-autoresearch-loop/spec.md`](phase-3-autoresearch-loop/spec.md) — §2, §5 updated (cross-linked)

**Discovery context:** During an evaluation of [`burtenshaw/multiautoresearch`](https://github.com/burtenshaw/multiautoresearch) (frozen reference at SHA `2dbc0bb593a1fc07997f35b3ef3aaebd1e3e561f`, 2026-05-02; see [`vendor/multiautoresearch/MAHORAGA_NOTES.md`](../../vendor/multiautoresearch/MAHORAGA_NOTES.md)) we found a working production-grade decomposition of the autoresearch loop into seven scoped roles with explicit permission boundaries. Adopting this pattern resolves several Phase-3 gaps that the current 3-subagent model (Hunter / Guardian / Archivist) leaves underspecified — most notably duplicate-rejection, parallel-experiment isolation, atomic record-and-promote, and fleet observability.

This amendment formalizes the seven-role split. It does NOT change the architectural posture from the 2026-04-26 revision: still **one OpenClaw assistant inside one OpenShell sandbox**, with the new roles realized as additional **subagent definitions** under `infra/openclaw/subagents/`. No new containers, no new substrate.

---

## 1. The seven roles

| Role | Mode | Write scope | Bash | Dispatched when | Mahoraga responsibility |
|---|---|---|---|---|---|
| **Orchestrator** | primary | full sandbox | yes | always-on | Mahoraga's main OpenClaw assistant. Sole dispatcher; owns cadence selection (nightly / weekend / replay); receives Telegram `/halt`, `/resume`, `/status` from operator. Replaces the implicit "main orchestrator" in the 2026-04-26 revision §3 diagram. |
| **Planner** | subagent (read-only) | none | no | start of every cadence; on-demand | Builds a ranked queue of 1–3 fresh single-change strategy mutation hypotheses. Reads `research/notes.md`, `research/do-not-repeat.md`, `research/campaigns/`, current registry, current regime label, KB pgvector forbidden-patterns. Aggressively rejects duplicates and stale-master ideas before any compute is spent. |
| **Researcher** | subagent (read-only) | none | no | weekly cron; on-demand from Orchestrator | Paper / web-research scout. Translates external sources (FRED narrative releases, SEC EDGAR filings, paper preprints) into single-change hypotheses for Planner to consider. Subsumes the Phase 4+ "web-research" agent from integration spec §4.5 — same sandbox profile, same egress allowlist, but now a subagent rather than a separate container. |
| **Reviewer** | subagent (read-only) | none | no | after Planner emits a queue; before any Hunter run | Hard-rule check: 5 walls + 3 gates *predicted* compatible with proposal; vault-embargo respected; no multi-change patches; not a duplicate of an open or recent experiment. Cites exact rule + file when blocking. |
| **Hunter** (renamed from `experiment-worker` for Mahoraga continuity) | subagent | `train.py` analogue only inside isolated worktree | yes | one Hunter dispatch per approved Planner item | Executes exactly one strategy mutation in an isolated git worktree (`.runtime/worktrees/<experiment-id>/`), runs vectorbt backtest within budget, parses metrics, calls promote pipeline. Replaces the broad "Hunter agent service" from Phase-3 spec §2 item 1 with a tightly-scoped per-experiment worker. |
| **Guardian** | subagent | none in main checkout; veto record in `experiments.iterations` | yes (synthetic-data + walls only) | after every Hunter mutation | Synthetic-data adversarial test, 5-wall verification, 3-gate verification, regime-crowding + correlation-to-active-portfolio check. Approve / veto + reason returned to Orchestrator. Can publish `halt` event on catastrophic-loss trip (architecture revision §6 contract unchanged). |
| **Archivist + Memory-Keeper** | subagent | only writer of `services/trader/research/` markdown notebook in main checkout (Memory-Keeper aspect); Postgres KB writer (Archivist aspect) | no | after every iteration (write notes); weekly (L1→L2 synthesis); monthly (L2→L3 synthesis) | Maintains the canonical markdown notebook (`notes.md`, `do-not-repeat.md`, `paper-ideas.md`, `campaigns/<id>/`, `experiments/<id>.md`) AND the pgvector-indexed KB. Markdown is canonical, audit-friendly source-of-truth; pgvector is the regenerable retrieval index. Archivist + Memory-Keeper are the same subagent because in our model the markdown and the embeddings are two views of the same KB content — splitting them creates dual-truth drift. |
| **Reporter** | subagent | none in repo; reads observability stores | yes (read-only fleet queries) | hourly cron during nightly cadence; on-demand | Fleet status: active iterations, completed iterations, failures, current leader strategy per regime, anomalies, duplicate hypotheses in flight. Renders to Telegram `/status` and feeds Phase 6 Streamlit dashboard. Replaces the implicit observability gap noted in integration spec §10 open question #3 ("LiteLLM provider behavior under load… cost-cap enforcement"). |

## 2. How this maps onto the original 3-agent model

The Phase-3 spec §2 originally listed three always-on agents. They map onto the seven roles as follows:

| Original Phase-3 role | Becomes | Notes |
|---|---|---|
| Hunter agent service | **Orchestrator + Planner + Reviewer + Hunter** | The single "Hunter" agent in the original spec was carrying four responsibilities: cadence selection, hypothesis generation, rule check, and execution. Splitting them gives a clean permission boundary at each step. The actual mutation work stays exactly as described in integration spec §6.4. |
| Guardian agent service | **Guardian** (unchanged) | No change. Guardian's veto + halt authority survives verbatim. |
| Archivist agent service | **Archivist + Memory-Keeper** (single subagent, two aspects) | The existing Archivist responsibility for KB Levels 1/2/3 is preserved. The new aspect is sole-writer-of-markdown-notebook, which gives us the human-auditable failure ledger that pgvector alone doesn't provide. |
| (none) | **Researcher** | New. Phase-4 web-research subagent promoted to first-class. |
| (none) | **Reporter** | New. Closes integration spec §10 open question #3. |

## 3. Permission scoping (locked)

These permissions are enforced at the OpenClaw subagent definition level (`infra/openclaw/subagents/<role>.md` frontmatter) and verified by a Phase-3 CI guard. Scope creep is a substrate-portability red flag, not a convenience.

```
Orchestrator       : write=*, edit=*, bash=allow, task=allow{Planner,Reviewer,Researcher,Hunter,Guardian,Archivist,Reporter}, deny others
Planner            : write=false, edit=false, bash=false, task=deny
Researcher         : write=false, edit=false, bash=false, task=deny
Reviewer           : write=false, edit=false, bash=false, task=deny
Hunter             : write=worktree-only, edit=worktree-only, bash=allow{vectorbt,git in worktree}, task=deny
Guardian           : write=experiments.iterations only, edit=deny, bash=allow{synthetic_data, walls, gates}, task=deny
Archivist          : write=services/trader/research/** + knowledge.* schemas, edit=services/trader/research/**, bash=deny, task=deny
Reporter           : write=deny, edit=deny, bash=allow{read-only fleet queries}, task=deny
```

The Phase-3 CI guard:

```bash
# infra/ci/check-subagent-scopes.sh
grep -L 'write: .*deny' infra/openclaw/subagents/{Planner,Researcher,Reviewer,Reporter}.md && exit 1
grep -L 'task: .*deny' infra/openclaw/subagents/{Planner,Researcher,Reviewer,Hunter,Guardian,Archivist,Reporter}.md && exit 1
```

## 4. Loop kernel update (supersedes integration spec §6.4)

The kernel from integration spec §6.4 still describes the per-iteration logic, but the dispatch surface is now multi-step:

```
Orchestrator.run_cadence(cadence)
  ↓
  Planner.propose_queue(cadence, regime, kb_context)              → ranked list of N hypotheses
  ↓
  for hypothesis in queue:
      Reviewer.check(hypothesis, registry, recent_iterations)     → approve | block(reason)
      if blocked: Archivist.record_blocked(hypothesis, reason); continue

      Hunter.create_worktree(hypothesis)                          → experiment_id, worktree_path, log_path
      Hunter.run_iteration(experiment_id)                         → FitnessReport
        # (this is the original integration spec §6.4 kernel,
        #  unchanged: mutate → backtest → score)

      Guardian.review(experiment_id, FitnessReport)               → approve | veto(reason)
      if vetoed: Archivist.record_vetoed(experiment_id, reason); continue

      promote_pipeline(experiment_id, FitnessReport)              → atomic record + (conditional) promote
        # writes experiments.iterations (always)
        # writes strategies.registry + git tag (only if beats master)

      Archivist.record_iteration(experiment_id, FitnessReport)    → notes.md + pgvector embedding

  ↓
  Reporter.publish_cadence_summary(cadence)                       → Telegram + dashboard
```

The `promote_pipeline` is the atomic record-and-promote logic adapted from `multiautoresearch/pre-training/scripts/submit_patch.py`. It runs as a Python tool in the OpenClaw sandbox, NOT as a subagent — it is mechanical (parse, compare, write), not LLM-driven. Its serializer is the Postgres `experiments.iterations` table (compare-and-set on `parent_strategy_id` + `candidate_hash`), which gives us race-free parallel Hunter dispatch — a concrete answer to Phase-3 §7 open question on mutation rate.

## 5. Updated Phase-3 sub-features (supersedes Phase-3 spec §2)

Replace the original 10-item list with:

1. **Orchestrator** main-assistant cadence loop + Telegram `/halt`-`/resume`-`/status` wiring
2. **Planner** subagent — KB-grounded hypothesis queue
3. **Researcher** subagent — paper/web scout, gated egress allowlist
4. **Reviewer** subagent — hard-rule + duplicate-rejection check
5. **Hunter** subagent + isolated-worktree mechanic (`services/trader/training/worker.py`, ported from `multiautoresearch/pre-training/scripts/worker_common.py`)
6. **Guardian** subagent — vetoes via Phase 2 walls/gates + synthetic-data + Postgres-recorded reasons
7. **Archivist + Memory-Keeper** subagent — markdown notebook (canonical) + pgvector KB (derived); L1→L2 weekly, L2→L3 monthly
8. **Reporter** subagent — Telegram `/status` + Phase-6 dashboard data feed
9. **Loop kernel** (`services/trader/training/loop.py`) — implements the multi-step dispatch in §4 above
10. **`strategy_template.py` contract** — unchanged from integration spec §6.2
11. **`eval.py` (FitnessReport)** — unchanged from integration spec §6.3
12. **Compressed-history replay engine** — unchanged
13. **`promote_pipeline` tool** — atomic record + conditional promote (`services/trader/training/promote.py`, ported from `multiautoresearch/pre-training/scripts/submit_patch.py`); Postgres-serialized for parallel safety
14. **`refresh_master` tool** — workspace-restore from local promoted master (`services/trader/training/refresh_master.py`, ported from `multiautoresearch/pre-training/scripts/refresh_master.py`)
15. **`parse_metric` tool** — deterministic FitnessReport extraction from vectorbt run output (ported analogue of `parse_metric.py`)
16. **Markdown notebook layout** under `services/trader/research/` — canonical `notes.md`, `do-not-repeat.md`, `paper-ideas.md`, `campaigns/<id>/`, `experiments/<id>.md`
17. **Vault validation framework** — unchanged from original Phase-3 spec §2 item 10

Items 13–16 are the concrete mechanics that the original Phase-3 spec hand-waved as "git tag + KB Level-1 entry" / "promote candidate".

## 6. Updated timeline (supersedes Phase-3 spec §5)

Same 13-week duration, three streams, but with the new role split factored in. **Stream A is now wider but each role is smaller**, so person-week count is comparable.

| Weeks | Stream A (Subagents) | Stream B (Loop kernel + tools) | Stream C (Replay + KB) |
|---|---|---|---|
| 1–2 | Orchestrator skeleton + cadence dispatch wiring; subagent definition files committed | `loop.py` skeleton (multi-step dispatch); `Strategy` contract; mutator primitives | KB Level-1 schema + pgvector setup; markdown notebook scaffolding |
| 3–4 | Planner v1 + Reviewer v1 (read-only KB queries; structured queue output) | `eval.py` wiring Phase 2 walls + gates; `parse_metric.py` port | replay clock cursor + PIT enforcement |
| 5–6 | Hunter v1 (worktree mechanic ported); Guardian v1 (synthetic-data + walls + Postgres veto record) | `promote_pipeline` v1 (Postgres-serialized atomic record + promote); nightly cadence skeleton | compressed-replay end-to-end on 1 year |
| 7–8 | Archivist+Memory-Keeper v1 (markdown writer + L1 embedding); Reporter v1 (Telegram `/status`) | weekend cadence; race tests on parallel Hunter dispatch | replay across 3 years |
| 9–10 | Hunter v2 (multi-step mutation chains); Researcher v1 (paper-ideas pipeline) | end-to-end loop with 3 cadences; subagent permission CI guard | git registry integration; do-not-repeat.md auto-population |
| 11 | Full subagent integration | Unattended 8h test | Vault validation framework |
| 12 | Failure-mode testing (subagent crash, LLM timeout, network drop, race-on-promote) | Budget tuning | Vault-holdout pass |
| 13 | Exit-criteria sign-off | Exit-criteria sign-off | Exit-criteria sign-off |

## 7. Updated exit criteria (supersedes Phase-3 spec §3)

- All seven subagents dispatch correctly from the Orchestrator and respect their declared permission scopes (CI guard passes)
- Nightly cadence runs unattended 8h: ≥50 iterations, ≥80% within budget, no crashes
- **Race-on-promote test:** 5 Hunter dispatches with deliberately overlapping hypotheses against the same parent master complete without `experiments.iterations` corruption; only one wins promotion if multiple beat master (Postgres serializer enforced)
- Discarded candidates (Reviewer-blocked, Guardian-vetoed, no-improvement) all appear in `experiments.iterations` with `kept=false` + reason
- Promoted candidates appear as commits in the strategy registry with full provenance metadata (parent ID, mutation diff hash, FitnessReport hash, KB iteration ID)
- Compressed-replay walks ≥3 historical years end-to-end with no look-ahead-bias detection failures
- Vault validation: a strategy promoted from training is evaluated on the 6-month vault holdout and matches in-sample within tolerance
- KB pgvector similarity search returns relevant prior experiments in <500ms
- **Markdown notebook is regenerable from `experiments.iterations`** (offline reproducibility check; lets us treat pgvector as the derived index it is)
- **Reporter's Telegram `/status` returns within 2s** and accurately reflects active iterations + current leader

## 8. What this amendment does NOT change

- Architectural posture (one OpenClaw, one sandbox) — unchanged from 2026-04-26 revision
- Halt contract — unchanged from 2026-04-26 revision §6
- Hard risk limits (CLAUDE.md "Hard risk limits") — unchanged
- Vault embargo enforcement — unchanged
- Phase 0–2 exit criteria — unchanged
- License posture — unchanged (multiautoresearch is a cherry-pick reference, not a vendored dependency on the import path)
- Substrate portability — *strengthened*. The seven subagent definition files become the substrate-portability test surface: any replacement runtime (LangGraph, raw NATS, custom orchestrator) must support all seven role permission scopes.

## 9. Open questions for this amendment

1. **`promote_pipeline` Postgres isolation level.** Default `read committed` may admit anomaly under burst Hunter dispatch. Decide between `serializable` (safer, lower throughput) and `repeatable read` + explicit `SELECT … FOR UPDATE` on parent strategy. Decide before week-6 race test.
2. **Markdown notebook write contention.** Archivist + Memory-Keeper is one subagent, but it may be invoked concurrently from multiple Hunter completions. Either serialize via `flock(1)` on `notes.md` (simple) or queue writes through a single Postgres-backed worker (more correct). Decide week 7.
3. **Researcher's egress allowlist** — same allowlist as integration spec §5.4 `web-research-agent` profile (FRED, SEC EDGAR, Federal Reserve, CME, Tiingo, NewsAPI). Confirm in Phase 0 substrate config that OpenClaw + OpenShell can express the per-subagent egress scope cleanly, OR fall back to running Researcher in a separate sandbox lane.
4. **Reporter cost.** Hourly cron + Telegram + dashboard data feed adds LLM + Postgres traffic. Set a per-cadence budget cap and degrade gracefully (skip dashboard refresh, keep Telegram).
