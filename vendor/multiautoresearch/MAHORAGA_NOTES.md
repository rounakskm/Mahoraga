# Mahoraga adaptation of burtenshaw/multiautoresearch

This file is the canonical record of (a) how this reference copy is tracked, (b) which scripts and patterns we plan to port into `services/trader/`, (c) which we explicitly reject, (d) every snapshot refresh we perform, and (e) every port we land.

See [`docs/superpowers/specs/2026-05-03-phase-3-seven-role-amendment.md`](../../docs/superpowers/specs/2026-05-03-phase-3-seven-role-amendment.md) for the architectural posture and which Phase-3 sub-features each port lands in.

## Vendored at

- Upstream: `https://github.com/burtenshaw/multiautoresearch`
- Branch: `main` at the time of pin
- Commit SHA (peeled): `2dbc0bb593a1fc07997f35b3ef3aaebd1e3e561f`
- Date pinned: `2026-05-03`
- License: MIT (only file present at `pre-training/LICENSE` © 2026 Ben Burtenshaw); root LICENSE absent; post-training and inference subprojects ship no LICENSE inline. We treat the whole repo as MIT-by-implication for the pre-training subproject only. **Before porting from `post-training/` or `inference/`, confirm license scope with the author or restrict to pre-training paths.**

## Vendoring discipline

This is a **frozen reference snapshot**, mirrored on the karpathy/autoresearch vendoring pattern (NOT live subtree like NemoClaw or tradingagents). Reasons:

- The repo is research-stage (264★, 0 releases, 1 issue) — interface stability is not promised.
- Our usage is one-way pattern extraction, not dependency consumption. Files in `services/trader/` are adaptations, not imports.
- A frozen pin makes attribution and modification tracking unambiguous.

Refresh policy:

- **Routine refresh:** quarterly at most, OR when we are about to port a new pattern and want the latest reference. Manual `git rm -rf vendor/multiautoresearch/ && cp -r <fresh-clone>/. vendor/multiautoresearch/`, then update the SHA + Refresh log entry below.
- **No `git subtree pull`.** This is intentional. We do not want auto-merging upstream changes into our reference copy.
- **Push policy:** never. We never push back.

## License obligations

- Preserve `pre-training/LICENSE` verbatim.
- Every ported file in `services/trader/` keeps the original MIT header (or adds one if the source file lacks it; MIT permits this) and adds a Mahoraga-attribution block citing source path + upstream SHA. See [Port attribution discipline](#port-attribution-discipline).
- We do NOT use the multiautoresearch name, the Autolab name, or any project branding from this repo in Mahoraga product surfaces.

## Vendoring action: pending

The vendor copy at `vendor/multiautoresearch/` has not yet been materialized. This `MAHORAGA_NOTES.md` documents the pre-pinned plan; the actual `cp -r` happens as a separate explicit step (see [Refresh log](#refresh-log)). This avoids landing a 60+-file reference clone in the same commit as the planning doc.

To materialize:

```bash
cd /tmp
git clone https://github.com/burtenshaw/multiautoresearch.git
cd multiautoresearch && git checkout 2dbc0bb593a1fc07997f35b3ef3aaebd1e3e561f && cd ..
rsync -a --exclude='.git' multiautoresearch/ /Users/rounakskm/AI-projects/Mahoraga/vendor/multiautoresearch/
# Then commit, with an entry appended to the Refresh log below.
```

## Port targets (planned, by Phase-3 sub-feature)

These are scheduled extractions per the seven-role amendment §5. Specific source paths confirmed against `2dbc0bb`. Each port lands at the listed target in `services/trader/` with adaptations applied.

### Phase-3 amendment item 5 — Hunter worktree mechanic

| Source path in `vendor/multiautoresearch/` | Target | Adaptation |
|---|---|---|
| `pre-training/scripts/worker_common.py` | `services/trader/training/worker.py` | Replace OpenCode `--agent` dispatch with OpenClaw subagent dispatch; replace `AUTOLAB_*` env-var contract with Mahoraga `MAHORAGA_EXPERIMENT_ID` / `MAHORAGA_HYPOTHESIS` / `MAHORAGA_PARENT_HASH` / `MAHORAGA_LOG_PATH`; replace `train.py`/`train_orig.py` paths with `strategy_template.py` / `strategy_orig.py` from integration spec §6.2; preserve git-worktree creation, durable-note template, frozen-master-snapshot, and reserved-log-path mechanics verbatim |
| `pre-training/scripts/opencode_worker.py` | `services/trader/training/cli/hunter_dispatch.py` | Replace `subprocess.run([opencode_bin, "run", "--agent", "experiment-worker", prompt])` with OpenClaw subagent invocation (interface TBD in Phase 3 weeks 1–2). Keep the create / run / cleanup verb structure. |

### Phase-3 amendment item 13 — `promote_pipeline` (atomic record + conditional promote)

| Source path | Target | Adaptation |
|---|---|---|
| `pre-training/scripts/submit_patch.py` | `services/trader/training/promote.py` | **Major adaptation.** Replace TSV ledger (`research/results.tsv`) with Postgres `experiments.iterations` writes serialized via `SELECT … FOR UPDATE` on `parent_strategy_id`. Replace HF Jobs metric resolution (`resolve_metrics`, `fetch_job_log`, `cache_path_for_job`) with vectorbt FitnessReport JSON load. Replace `val_bpb < master.val_bpb` keep-if-better with `composite_score > master.composite_score AND wall_results.all_pass AND gates.all_pass` (integration spec §6.3 two-stage acceptance). Preserve: parent-hash + candidate-hash provenance, atomic conditional-promote semantics, deterministic run-id construction, dry-run mode. |
| `pre-training/scripts/local_results.py` | (do NOT port) | Functionality is replaced by Postgres schemas. Reading it for reference is fine; importing or copying it is rejected (TSV truth-source conflicts with our single-DB principle). |

### Phase-3 amendment item 14 — `refresh_master` (workspace restore)

| Source path | Target | Adaptation |
|---|---|---|
| `pre-training/scripts/refresh_master.py` | `services/trader/training/refresh_master.py` | Trivial port. Replace `train.py`/`train_orig.py`/`research/live/master.json` with `strategy_template.py`/`strategy_orig.py`/`research/live/master.json` (Mahoraga's own master snapshot file). Used by Hunter at the start of every iteration to start from refreshed local master rather than stale local edits. |

### Phase-3 amendment item 15 — `parse_metric` (deterministic metric extraction)

| Source path | Target | Adaptation |
|---|---|---|
| `pre-training/scripts/parse_metric.py` | `services/trader/training/parse_metric.py` | Trivial port. Replace `SUMMARY_KEYS` (val_bpb, training_seconds, …) with Mahoraga's FitnessReport fields (composite_score, sharpe, deflated_sharpe, pbo, max_drawdown, …). Replace text-line regex with structured JSON load (vectorbt emits JSON, not key:value text). |

### Phase-3 amendment item 16 — Markdown notebook layout

| Source path | Target | Adaptation |
|---|---|---|
| `pre-training/research/notes.md` (structure) | `services/trader/research/notes.md` (template) | Layout-only port. Their content is LM-pretraining anecdotes; ours starts empty and grows from Archivist+Memory-Keeper writes. Keep the per-master-hash sectioning convention. |
| `pre-training/research/do-not-repeat.md` | `services/trader/research/do-not-repeat.md` | Same. Their **Duplicate Rule** section ("two experiments are duplicates if they share parent master hash + subsystem + hypothesis class") becomes the Reviewer subagent's check criterion verbatim. |
| `pre-training/research/paper-ideas.md` | `services/trader/research/paper-ideas.md` | Layout-only. Researcher subagent writes here. |
| `pre-training/research/campaigns/` (structure) | `services/trader/research/campaigns/` | Layout-only. One markdown file per campaign (e.g. "post-FOMC mean-reversion"). |
| `pre-training/research/experiments/` (template) | `services/trader/research/experiments/` template | Per-iteration durable note. The template generated by `worker_common.py:build_note` is the right shape; rewrite for trading-strategy fields (hypothesis → strategy mutation; val_bpb → composite_score; training_seconds → backtest_seconds). |
| `pre-training/research/templates/` | `services/trader/research/templates/` | Port verbatim then adapt for trading. |

### Phase-3 amendment items 1–4, 6–8 — Subagent definition files

| Source path | Target | Adaptation |
|---|---|---|
| `pre-training/.opencode/agent/autolab.md` | `infra/openclaw/subagents/orchestrator.md` | Adapt YAML frontmatter to OpenClaw subagent format (TBD week 1). System-prompt body is the right blueprint for our Orchestrator: dispatch policy, ground-truth file list, operating rules. |
| `pre-training/.opencode/agent/planner.md` | `infra/openclaw/subagents/planner.md` | Direct port; system prompt rewritten for strategy mutation (replace `train.py` with `strategy_template.py`, val_bpb with composite_score, GPU-hour with vectorbt-second-budget). |
| `pre-training/.opencode/agent/reviewer.md` | `infra/openclaw/subagents/reviewer.md` | Direct port + add 5-walls / 3-gates predicted-compatibility check from Phase 2. |
| `pre-training/.opencode/agent/researcher.md` | `infra/openclaw/subagents/researcher.md` | Direct port + add explicit egress allowlist mapping to integration spec §5.4 web-research-agent profile. |
| `pre-training/.opencode/agent/experiment-worker.md` | `infra/openclaw/subagents/hunter.md` | Rename to Hunter for Mahoraga continuity. System prompt body keeps the "exactly one hypothesis change in isolated worktree" discipline; replace HF Jobs commands with vectorbt + promote pipeline. |
| `pre-training/.opencode/agent/memory-keeper.md` | merged into `infra/openclaw/subagents/archivist.md` | We collapse Memory-Keeper into Archivist (amendment §1 rationale: avoid markdown/pgvector dual-truth drift). System prompt becomes "you maintain durable experiment memory in BOTH the markdown notebook (canonical) and the pgvector index (derived)." |
| `pre-training/.opencode/agent/reporter.md` | `infra/openclaw/subagents/reporter.md` | Direct port; replace Trackio + HF Jobs commands with Mahoraga's Postgres `experiments.iterations` queries + Telegram `/status` formatter. |

## Explicitly rejected

- **`pre-training/scripts/hf_job.py`** (~1000 lines) — Hugging Face Jobs orchestration. Domain-mismatch; we use vectorbt locally, not HF Jobs.
- **`pre-training/scripts/trackio_reporter.py`** (~750 lines) — Trackio observability. Not used in Phase 3; revisit when Phase 6 dashboard work lands. Pattern is informative; code is not portable.
- **`pre-training/scripts/setup_hermes_profile.py`, `print_*_kickoff.py` (5 files)** — runtime-specific kickoff helpers for OpenCode/Pi/Hermes/Codex/Claude Code. We are committed to OpenClaw; these don't transfer. The *pattern* (a tiny per-runtime printer that emits the kickoff prompt) is documented in Mahoraga's substrate-portability practice (CLAUDE.md), but no port.
- **`pre-training/scripts/sync_upstream.py`** — useful only if we want to live-track upstream multiautoresearch or karpathy/autoresearch. We are frozen on both. No port.
- **`pre-training/scripts/local_results.py`** — TSV-based ledger. Conflicts with our single-Postgres-DB principle (architecture spec §3.5). No port; functionality replaced by Postgres `experiments.iterations`.
- **`pre-training/.pi/`, `.codex/`, `.hermes.md`** — runtime-specific config trees. No port.
- **`post-training/` and `inference/` subprojects entirely** — domain mismatch (LM SFT, llama.cpp speed) AND license ambiguity (no LICENSE in those subdirectories at the time of pin). Reference-only; no copying without confirming license scope.
- **HuggingFace Hub coupling** anywhere (HF buckets, HF auth) — we are not on the HF Hub. Pure removal.
- **Their `program.md` content** — domain mismatch. Our `services/trader/training/program.md` is a Mahoraga-original adaptation of karpathy/autoresearch's `program.md.upstream` for trading-strategy mutation; multiautoresearch's variant is for LM training and has no portable content.

## Port attribution discipline

Every ported file in `services/trader/` and `infra/openclaw/subagents/`:

1. Adds an MIT-license header at the top if the source had one (preserve verbatim).
2. Adds a Mahoraga-attribution block immediately below:

   ```python
   # Adapted for Mahoraga from burtenshaw/multiautoresearch
   # Source: vendor/multiautoresearch/<original/path.py>
   # Upstream commit: 2dbc0bb593a1fc07997f35b3ef3aaebd1e3e561f
   # Modifications: <one-line summary>
   ```

3. Records an entry in the [Port log](#port-log) below.
4. Passes the substrate-portability CI guard (`grep -R "opencode\|hermes\|trackio\|huggingface_hub" services/trader/ infra/openclaw/` must return empty).

## Refresh log

| Date | Prior SHA | New SHA | Upstream summary | Notes |
|---|---|---|---|---|
| 2026-05-03 | (none) | `2dbc0bb` | Initial pin (vendor materialization pending) | Plan committed before vendor copy materializes; see "Vendoring action: pending" above |

## Port log (extractions performed)

_None yet._ Append one row per port when each Phase-3 sub-feature (amendment §5 items 1–8, 13–16) lands.

| Date | Source path | Target path | Modifications | Owner |
|---|---|---|---|---|

## Conventions for Tier-3 patches inside `vendor/multiautoresearch/`

We do NOT modify the vendored tree directly. Reasons:

- It is a frozen reference, not a dependency on the import path. There is no operational reason to patch.
- Modification would defeat the purpose of pinning a known SHA for clean attribution.

If we ever need a local fork (e.g., to apply a critical fix while waiting for upstream), the rule is:

1. Fork outside `vendor/multiautoresearch/` (a separate `vendor/multiautoresearch-fork/` directory).
2. Update this `MAHORAGA_NOTES.md` to record the fork rationale.
3. Update the architecture spec's vendor table to declare the fork.

_No Tier-3 patches contemplated._
