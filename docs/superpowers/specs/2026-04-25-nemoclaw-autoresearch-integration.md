# NemoClaw + autoresearch Integration Spec

**Status:** Approved 2026-04-25
**Type:** First executable spec under the architecture decomposition map
**Companion spec:** [`2026-04-25-mahoraga-architecture-decomposition.md`](2026-04-25-mahoraga-architecture-decomposition.md)
**Phases unblocked:** 0 (substrate bring-up), 1 (foundation), 2 (five walls), 3 (autoresearch loop core)

> **⚠️ Substrate-layer revision (2026-04-26):** §4.5, §4.6, §5.1, §5.2, §5.4, §5.5 of this spec are superseded by [`2026-04-26-architecture-revision-consolidated-assistant.md`](2026-04-26-architecture-revision-consolidated-assistant.md). NemoClaw runs **one** OpenClaw assistant per sandbox; Hunter / Guardian / Archivist become OpenClaw subagents (shared tools, separate contexts), not separate agent containers. The `agents.yaml` / `channels.yaml` configuration model is replaced by NemoClaw's native blueprint + onboarding flow. The autoresearch loop (§6), Docker compose topology (§7 — minus heartbeat), and upstream tracking (§8) are unchanged.

---

## 1. Goal & Scope

This spec is the technical foundation for Mahoraga. It is the first executable spec under the architecture decomposition map and unblocks Phases 0 through 3.

### What this spec covers

- How NVIDIA/NemoClaw is vendored, configured, and extended
- How karpathy/autoresearch is adapted into Mahoraga's strategy-mutation training loop
- The local Docker Compose topology that brings up the entire stack
- The contracts and configurations that downstream specs (data-foundation, five-walls, etc.) build on
- Acceptance criteria that gate Phases 0–3 exits

### What this spec does NOT cover

- The actual implementation of strategy logic (deferred to per-phase specs)
- The five anti-overfitting walls' internals (deferred to `five-wall-fortress-spec.md`)
- The regime detector algorithms (deferred to `regime-detector-spec.md`)
- Broker integration, Telegram bot, dashboard (Phase 5–6 specs)
- Cloud deployment (deferred to `cloud-deployment-spec.md`)

## 2. Vendor Strategy

### 2.1 NemoClaw — live `git subtree`

**Path:** `vendor/nemoclaw/`
**Upstream:** `https://github.com/NVIDIA/NemoClaw`
**License:** Apache 2.0
**Update model:** live; pulled via `git subtree pull`

#### Setup (one-time, Phase 0)

```bash
# Add upstream remote (named locally so we can refer to it later)
git remote add nemoclaw-upstream https://github.com/NVIDIA/NemoClaw.git
git fetch nemoclaw-upstream

# Initial vendoring at a known-good tag
git subtree add --prefix=vendor/nemoclaw nemoclaw-upstream <tag-or-sha> --squash
```

#### Pull cadence

- **Routine:** monthly. Review release notes, run integration tests, pull if green.
- **Security:** within 72 hours of CVE disclosure or upstream security advisory.
- **Command:** `git subtree pull --prefix=vendor/nemoclaw nemoclaw-upstream <tag-or-sha> --squash`

#### Push policy

- **Never automatic.** `git push` from this repo only pushes to our origin.
- **Explicit upstream contributions:** if we land a fix or feature we want to upstream, we use `git subtree push --prefix=vendor/nemoclaw nemoclaw-upstream <branch>` and open a PR. This is opt-in per change, never automated.

#### License compliance

- `vendor/nemoclaw/LICENSE` is preserved verbatim. Never delete.
- Any upstream `NOTICE` file is preserved and propagated.
- Modifications to `vendor/nemoclaw/` (Tier 3 patches) are documented in `vendor/nemoclaw/MAHORAGA_CHANGES.md` with date, scope, reason.
- Mahoraga product branding does not use the NemoClaw name, NVIDIA trademarks, or NVIDIA logos.

### 2.2 autoresearch — frozen one-time copy

**Path:** `vendor/autoresearch/`
**Upstream:** `https://github.com/karpathy/autoresearch`
**License:** MIT
**Update model:** frozen; never updated after initial copy

#### Setup (one-time, Phase 0)

```bash
# Clone, copy LICENSE + reference files to vendor/, discard the rest
git clone --depth=1 https://github.com/karpathy/autoresearch /tmp/autoresearch-tmp
mkdir -p vendor/autoresearch
cp /tmp/autoresearch-tmp/LICENSE vendor/autoresearch/LICENSE
cp /tmp/autoresearch-tmp/program.md vendor/autoresearch/program.md.upstream
cp /tmp/autoresearch-tmp/README.md vendor/autoresearch/README.md.upstream
rm -rf /tmp/autoresearch-tmp
```

We adapt — not vendor — the loop pattern. Adapted files live at `training/program.md`, `training/loop.py`, `training/strategy_template.py`. The `vendor/autoresearch/` directory exists primarily to preserve the upstream LICENSE and copyright reference.

#### What we copy (and adapt)

- `program.md` — instruction template for the autonomous agent. Adapted to describe strategy-fitness optimization instead of GPT-loss minimization.
- Loop scaffolding patterns from upstream `train.py` — inform our `training/loop.py` structure (5-min iteration budget, keep-if-better discipline, single-file mutation).

#### What we do NOT copy

- Upstream's GPT model code, `prepare.py` (data prep for language modeling), nanochat-derived training scaffolding. None of these apply to a backtest-driven loop.

### 2.3 License compliance summary

| File | Must preserve | Reason |
|---|---|---|
| `vendor/nemoclaw/LICENSE` | Verbatim | Apache 2.0 §4(a) |
| `vendor/nemoclaw/NOTICE` (if upstream provides one) | Verbatim | Apache 2.0 §4(d) |
| `vendor/autoresearch/LICENSE` | Verbatim | MIT requires copyright + permission notice |
| Copyright headers in vendored source | Verbatim | Both Apache 2.0 and MIT |

`vendor/nemoclaw/MAHORAGA_CHANGES.md` is the canonical record of our modifications to NemoClaw. Maintained whenever a Tier 3 patch lands.

## 3. Three-Tier Extension Model

The core principle: extensions live OUTSIDE `vendor/nemoclaw/`. This keeps `git subtree pull` from becoming merge-conflict hell.

### 3.1 Tier 1 — Configuration (90% of extensions)

NemoClaw is config-driven for the things it is meant to be extended with. Our config lives at `infra/nemoclaw-config/`. Adding agents, channels, routes, sandbox profiles, or outbound connections is editing YAML, not editing TypeScript.

Contents detailed in §5.

**Merge risk:** zero. `git subtree pull` never touches `infra/`.

### 3.2 Tier 2 — Sibling services (where new logic lives)

New agents and connectors are new containers under `services/<role>/`, registered with NemoClaw via Tier 1 config. NemoClaw is language-agnostic at the channel boundary; sibling services can be Python, Node, Rust — whatever the role demands. Mahoraga services are Python by default.

Adding a 4th, 5th, 10th agent does not touch `vendor/nemoclaw/`. It is a new directory under `services/`, plus an entry in `infra/nemoclaw-config/agents.yaml`.

**Merge risk:** zero.

### 3.3 Tier 3 — Patches to `vendor/nemoclaw/` (last resort, painful)

Rare. Used only when we need substrate behavior that NemoClaw upstream does not support and cannot be approximated via Tier 1 or Tier 2.

Discipline:

1. Tag the diff with an in-source comment: `// MAHORAGA-PATCH(YYYY-MM-DD): <reason>`
2. Record in `vendor/nemoclaw/MAHORAGA_CHANGES.md` with date, file paths, reason, scope
3. Open an upstream PR to NVIDIA when reasonable — reduces our merge debt
4. Run the full integration test suite against the patched substrate before merging
5. Re-test after every `git subtree pull` to confirm patches still apply

**Merge risk:** real. Use sparingly.

## 4. Service Inventory & Topology

### 4.1 NemoClaw substrate

Container image built from `vendor/nemoclaw/`. Listens on internal Docker network for agent registrations and channel traffic. Mounts `infra/nemoclaw-config/` read-only and a private state volume for its own bookkeeping.

### 4.2 LiteLLM gateway

Container running LiteLLM in proxy mode. Exposes `http://litellm:4000/v1` (OpenAI-compatible) on the internal Docker network. Configured with provider keys from environment variables.

Supported provider namespaces (initial):

- `ollama/*` — routes to host Ollama via `http://host.docker.internal:11434`
- `openrouter/*` — `OPENROUTER_API_KEY`
- `gemini/*` — `GEMINI_API_KEY` (Google)
- `anthropic/*` — `ANTHROPIC_API_KEY`
- `openai/*` — `OPENAI_API_KEY`
- `xai/*` — `XAI_API_KEY` (Grok)

Per-call model identifiers are namespaced (`anthropic/claude-opus-4-7`, `ollama/gemma4:latest`, etc.). Switching providers is a config edit, not a code change.

LiteLLM features used initially:

- Provider routing
- Fallback chains (configurable per agent or per request)
- Cost logging to LiteLLM's local SQLite (separate from Mahoraga's Postgres)
- Optional response caching (toggled per call via `cache=True` header)

### 4.3 Postgres + pgvector

Single Postgres 16 container with `pgvector` extension. Persistent volume at `data/postgres/`. Logical schemas (created by migration scripts in Phase 0):

| Schema | Tables | Purpose |
|---|---|---|
| `knowledge` | `experiments`, `patterns`, `principles`, `news`, `embeddings` | KB Levels 1/2/3 + news + vector index |
| `trades` | `orders`, `fills`, `positions`, `pnl_daily` | Trade journal |
| `experiments` | `iterations`, `mutations`, `fitness_reports` | Autoresearch loop metadata |
| `strategies` | `registry`, `lifecycle_events` | Pointers into git registry; lifecycle states |
| `audit` | `events` | Append-only event log; hash-chained |

NemoClaw's internal state is NOT in this Postgres. NemoClaw uses whatever it ships with (likely SQLite). It is persisted to a dedicated host volume at `data/nemoclaw-state/` (mounted into the NemoClaw container as `/var/lib/nemoclaw`), separate from the vendored source tree at `vendor/nemoclaw/`. We do not refactor it.

### 4.4 Ollama

Runs on the **host**, not in a container. This preserves Apple Silicon Metal acceleration, which is lost when Ollama is containerized on macOS. Containers reach Ollama via `http://host.docker.internal:11434` (Docker Desktop) or the equivalent Colima host name.

Models pulled at Phase 0: Gemma 4 (per project plan) via `ollama pull gemma4`; if Gemma 4 is not yet available in Ollama, use latest Gemma release as interim. Additional local models added as needed.

### 4.5 Agent containers (Hunter / Guardian / Archivist / Web-Research)

Each agent is its own Python service under `services/<role>/`. Standard structure:

```
services/hunter/
├── Dockerfile
├── pyproject.toml
├── src/hunter/
│   ├── __init__.py
│   ├── main.py            ← agent entry point; registers with NemoClaw, subscribes to channels
│   ├── propose.py         ← LLM-driven mutation proposer
│   ├── policy.py          ← when to run nightly cadence vs. weekend
│   └── prompts/           ← prompt templates
└── tests/
```

Agents register with NemoClaw at startup, subscribe to their declared channels, and run a long-lived event loop. They use the LiteLLM gateway for any LLM call.

The fourth agent, `web-research` (Phase 4+), follows the same structural pattern but uses a *distinct sandbox profile* (`web-research-agent`) with outbound web egress to a fixed allowlist (FRED, SEC EDGAR, Federal Reserve RSS, CME FedWatch, news syndication endpoints). It runs on a Sunday cron, synthesizes macro narratives from public sources, and publishes Level-2 / Level-3 KB entries to the `kb-updates` channel. The Hunter / Guardian / Archivist sandboxes have *no* general web egress; this isolation is intentional and is enforced in §5.4.

### 4.6 Stateless workers

Same structural pattern as agents but invoked on demand rather than long-lived:

- `services/regime-detector/` — exposes RPC `compute_regime(date) → MacroMesoMicro`
- `services/data-ingest/` — runs as a daemon; ingests from free APIs first (yfinance, Alpaca free tier, FRED, Stooq, Tiingo free tier), with paid APIs (Polygon, Alpaca paid) only if free tier is insufficient. 1-minute granularity is sufficient; per-tick is not required.
- `services/execution/` — exposes RPC `submit_order(order) → result`; enforces hard limits and regulatory compliance predicates
- `services/training/` — exposes RPC `run_iteration(strategy, budget) → FitnessReport`; called by Hunter; calls `synthetic-data` library for Wall 4 perturbations
- `services/news-classifier/` — Phase 4; <2s classification SLA (CRITICAL / MATERIAL / BACKGROUND); detail in `intelligence-layer-spec.md`
- `services/synthetic-data/` (library, not container) — Phase 2; GBM with regime switching, jump-diffusion, historical analogue generation; consumed by Guardian and `training`. Detail in `synthetic-data-spec.md`.

## 5. NemoClaw Configuration

Lives at `infra/nemoclaw-config/`. Mounted read-only into the NemoClaw container. Reload behavior depends on NemoClaw's runtime — verify during Phase 0.

### 5.1 `agents.yaml`

```yaml
# Registers each agent with NemoClaw. Adding agents = appending entries.
# Each agent gets a per-role sandbox profile (defined in sandbox-policies.yaml)
# rather than a shared "research-agent" profile, since their attack surfaces
# and required capabilities differ.
agents:
  - name: hunter
    image: mahoraga/hunter:latest
    sandbox: hunter-sandbox            # write access to strategy registry; calls training
    channels:
      subscribe: [market-state, kb-updates, risk-vetoes, execution-results, halt]
      publish: [strategy-proposals, execution-orders]
    inference:
      route: default
      preferred_model: ollama/gemma4:latest    # primary local for bootstrap-economy reasons
      fallback: [anthropic/claude-opus-4-7, openrouter/x-ai/grok-2]

  - name: guardian
    image: mahoraga/guardian:latest
    sandbox: guardian-sandbox          # read-only registry; calls synthetic-data + training
    channels:
      subscribe: [strategy-proposals, market-state, execution-results, halt]
      publish: [risk-vetoes, halt]     # Guardian can trigger halt on catastrophic loss
    inference:
      route: default
      preferred_model: ollama/gemma4:latest
      fallback: [anthropic/claude-opus-4-7, openai/gpt-4o]

  - name: archivist
    image: mahoraga/archivist:latest
    sandbox: archivist-sandbox         # broad read access to KB; no web egress
    channels:
      subscribe: [execution-results, strategy-proposals, risk-vetoes, halt]
      publish: [kb-updates]
    inference:
      route: default
      preferred_model: gemini/gemini-2.0-pro       # long-context for KB synthesis
      fallback: [anthropic/claude-opus-4-7]

  # Phase 4+: web-research has a distinct sandbox with outbound web egress.
  - name: web-research
    image: mahoraga/web-research:latest
    sandbox: web-research-agent        # outbound web egress to fixed allowlist
    schedule: "0 19 * * 0"             # Sunday 7pm cron
    channels:
      subscribe: [halt]
      publish: [kb-updates]
    inference:
      route: default
      preferred_model: gemini/gemini-2.0-pro       # long-context for fundamental synthesis
      fallback: [anthropic/claude-opus-4-7]
```

### 5.2 `channels.yaml`

```yaml
channels:
  - name: market-state
    payload_schema: schemas/market_state.json
    retention: 7d
  - name: strategy-proposals
    payload_schema: schemas/strategy_proposal.json
    retention: 30d
  - name: risk-vetoes
    payload_schema: schemas/risk_veto.json
    retention: 30d
  - name: kb-updates
    payload_schema: schemas/kb_update.json
    retention: 30d
  - name: execution-orders
    payload_schema: schemas/execution_order.json
    retention: indefinite          # audit-critical
  - name: execution-results
    payload_schema: schemas/execution_result.json
    retention: indefinite          # audit-critical
  - name: halt
    payload_schema: schemas/halt_event.json
    retention: indefinite          # audit-critical; kill-switch trail
```

The `halt` channel is the kill-switch primary path (architecture spec §5.6). Any service can publish a halt event; all order-emitting services must subscribe and stop submitting orders within 1 second of receipt. Recovery requires an explicit human-issued `halt_clear` event on the same channel.

### 5.3 `inference-routes.yaml`

```yaml
routes:
  default:
    upstream: http://litellm:4000/v1
    type: openai-compatible
    timeout_s: 60
    retry: 2
```

A single `default` route covers everything; per-agent overrides go in `agents.yaml`. Adding a second route (e.g., a separate LiteLLM instance for high-cost models) is appending to this file.

### 5.4 `sandbox-policies.yaml`

```yaml
# Per-role sandbox profiles. Different agents have different attack surfaces
# and required capabilities; sharing one "research-agent" profile would over-
# permission Archivist (no need for execution egress) and under-permission
# web-research (needs internet egress). Hunter, Guardian, Archivist all have
# zero general web egress — only web-research-agent does.
sandboxes:
  - name: hunter-sandbox
    network:
      egress_allowlist:
        - http://litellm:4000
        - http://postgres:5432
        - http://regime-detector:8080
        - http://training:8080
        - http://execution:8080         # only Hunter publishes to execution-orders
    filesystem:
      mounts:
        - source: data/audit
          target: /audit
          read_only: false
        - source: data/parquet
          target: /data
          read_only: true
        - source: strategies
          target: /strategies
          read_only: false              # only Hunter writes to strategy registry
    resources:
      memory_max: 4G
      cpu_max: 2

  - name: guardian-sandbox
    network:
      egress_allowlist:
        - http://litellm:4000
        - http://postgres:5432
        - http://training:8080          # for adversarial-stress runs
    filesystem:
      mounts:
        - source: data/audit
          target: /audit
          read_only: false
        - source: data/parquet
          target: /data
          read_only: true
        - source: strategies
          target: /strategies
          read_only: true               # read-only for Guardian (vetoes, doesn't write)
    resources:
      memory_max: 4G
      cpu_max: 2

  - name: archivist-sandbox
    network:
      egress_allowlist:
        - http://litellm:4000
        - http://postgres:5432          # broad read access to KB schemas
    filesystem:
      mounts:
        - source: data/audit
          target: /audit
          read_only: false
        - source: data/parquet
          target: /data
          read_only: true
    resources:
      memory_max: 4G
      cpu_max: 2

  # Phase 4+: outbound web egress to a fixed allowlist for macro research.
  - name: web-research-agent
    network:
      egress_allowlist:
        - http://litellm:4000
        - http://postgres:5432
        - https://fred.stlouisfed.org
        - https://www.federalreserve.gov
        - https://www.sec.gov                  # EDGAR
        - https://www.cmegroup.com             # FedWatch
        - https://api.tiingo.com               # news syndication (free tier)
        - https://newsapi.org                  # news aggregation (if used)
    filesystem:
      mounts:
        - source: data/audit
          target: /audit
          read_only: false
        - source: data/research
          target: /research
          read_only: false              # cached web fetches
    resources:
      memory_max: 4G
      cpu_max: 2
```

### 5.5 `connections.yaml`

Outbound integrations consumed by `data-ingest` and `execution`. Adding new brokers, data sources, or notification targets is appending here.

```yaml
connections:
  - name: alpaca-data
    kind: alpaca
    base_url: https://data.alpaca.markets
    secret_ref: ALPACA_DATA_KEY

  - name: alpaca-paper
    kind: alpaca-broker
    base_url: https://paper-api.alpaca.markets
    secret_ref: ALPACA_PAPER_KEY

  - name: polygon
    kind: polygon
    base_url: https://api.polygon.io
    secret_ref: POLYGON_KEY

  - name: alpaca-news-ws
    kind: websocket
    url: wss://stream.data.alpaca.markets/v1beta1/news
    secret_ref: ALPACA_DATA_KEY

  # Phase 6+: telegram, hostinger deploy hooks, etc.
```

## 6. autoresearch Training-Loop Adaptation

### 6.1 Conceptual mapping

| autoresearch | Mahoraga |
|---|---|
| Agent | Hunter (with Guardian veto, Archivist memory) |
| `train.py` (mutated) | `training/strategy_template.py` (one per active strategy) |
| `program.md` (instructions) | `training/program.md` |
| 5-min training run | vectorbt backtest within configurable budget (default 5 min) |
| `val_bpb` (lower better) | `composite_score` (higher better, but only after walls + gates pass) |
| Greedy keep-if-better | Two-stage: walls + gates must pass, THEN greedy keep |
| Single sequential loop | Same kernel, run at three cadences (nightly, weekend, compressed-replay) |

### 6.2 Mutation surface

`training/strategy_template.py` is a single file with a fixed signature contract. Hunter rewrites bodies and module-level constants but not the public interface.

```python
# training/strategy_template.py — file Hunter mutates
from typing import Protocol
import pandas as pd

class Strategy(Protocol):
    REGIME_AFFINITY: list[str]                # mutable constant
    LOOKBACK_DAYS: int                        # mutable constant
    PARAMS: dict[str, float]                  # mutable constant

    def signal(self, features: pd.DataFrame) -> pd.Series:
        """Return a series in [-1, 1] indexed by symbol. Body mutable; signature locked."""
        ...

    def position_size(self, signal: float, state: dict) -> float:
        """Return target dollar size given signal and portfolio state. Body mutable; signature locked."""
        ...
```

The fixed signature prevents Hunter from accidentally bypassing risk checks, breaking the backtester, or drifting into an interface that downstream `execution/` cannot consume. This is a tighter sandbox than autoresearch's "rewrite anything in train.py" — appropriate because the artifact eventually trades real money.

### 6.3 Scoring contract

```python
# training/eval.py
from dataclasses import dataclass

@dataclass
class WallResults:
    statistical_rigor: bool         # Wall 1: DSR, PBO, Monte Carlo
    data_discipline: bool           # Wall 2: PCV, vault embargo, PIT
    complexity_control: bool        # Wall 3: sensitivity, MDL
    generalization: bool            # Wall 4: cross-asset, multi-regime
    meta_awareness: bool            # Wall 5: trial budget, KB forbidden patterns

    @property
    def all_pass(self) -> bool:
        return all([
            self.statistical_rigor, self.data_discipline,
            self.complexity_control, self.generalization, self.meta_awareness,
        ])

@dataclass
class FitnessReport:
    composite_score: float                   # the single number Hunter optimizes
    sharpe: float
    deflated_sharpe: float
    pbo: float                               # < 0.30 required (Wall 1)
    max_drawdown: float
    wall_results: WallResults
    regime_breakdown: dict[str, float]       # Sharpe per regime tested
    vault_excluded: bool                     # always True during training
    iteration_id: str                        # primary key in experiments.iterations
```

Two-stage acceptance:

1. **Hard filter:** candidate must pass `wall_results.all_pass` AND all 3 gates. Failing any → discard regardless of `composite_score`.
2. **Optimization signal:** among candidates that pass, keep if `composite_score > parent.composite_score`.

### 6.4 Loop kernel

```python
# training/loop.py
def autoresearch_iteration(
    parent_strategy: Strategy,
    *,
    time_budget_s: int = 300,
    point_in_time: date | None = None,
    cadence: Literal["nightly", "weekend", "replay"],
) -> IterationOutcome:

    # 1. Hunter LLM proposes mutation given KB context
    kb_context = archivist.recent_patterns(parent_strategy)
    mutation = hunter.propose(parent_strategy, kb_context)

    # 2. Apply mutation → candidate strategy file
    candidate = apply_mutation(parent_strategy, mutation)

    # 3. Backtest within budget; vault excluded; PIT clamp if compressed-replay
    backtest = vectorbt.run(
        candidate,
        dataset=feature_store.view(point_in_time=point_in_time, vault_excluded=True),
        timeout=time_budget_s,
    )

    # 4. Score
    report = eval.evaluate(candidate, backtest)

    # 5. Guardian veto (regime crowding, correlation to active portfolio, etc.)
    if not guardian.approve(candidate, report):
        return discard(candidate, report, reason="guardian_veto")

    # 6. Hard filter — walls + gates
    if not report.wall_results.all_pass:
        return discard(candidate, report, reason="wall_fail")
    if not gates.pass_all(report):
        return discard(candidate, report, reason="gate_fail")

    # 7. Greedy keep-if-better
    if report.composite_score > parent_strategy.fitness.composite_score:
        commit_to_registry(candidate, report)         # git tag + KB Level-1 entry
        return promote(candidate, report)
    return discard(candidate, report, reason="no_improvement")
```

Key behavior: `discard()` is not a no-op. Every discarded candidate is written to `experiments.iterations` with `kept=false` plus the `reason` and the mutation diff. This is how negative learning compounds — Archivist surfaces forbidden patterns in future Hunter prompts.

### 6.5 Three cadences, one kernel

| Cadence | Trigger | Iteration count | Time budget per iteration | Parent selection |
|---|---|---|---|---|
| **Nightly** | 5pm – 8:30am ET (outside market hours) | ~50 | 5 min | Active strategies in current regime |
| **Weekend** | Sun 6pm – 9pm ET | full sweep across all strategies × regimes | varies (longer ok) | All registry strategies |
| **Compressed-replay** (Phase 1–3 bootstrap) | continuous during bootstrap | thousands across 4–6 weeks of wall clock | 1–2 min (smaller per-iteration data) | Walks 2018 → vault boundary at accelerated clock |

**Compressed-replay** is the project plan's signature move. Implementation is the same kernel run with `point_in_time=clamp_date` cycling forward through history:

```python
for clamp_date in date_range(start="2018-01-01", end=vault_start, step=BUSINESS_DAY):
    for _ in range(experiments_per_day):
        autoresearch_iteration(
            parent_strategy=registry.current_seed(clamp_date),
            point_in_time=clamp_date,
            cadence="replay",
            time_budget_s=90,
        )
```

By the time the wall clock catches up to the vault boundary, the system has experienced 7+ years of regimes via PIT-clamped iterations.

### 6.6 Negative-learning to KB

Discarded candidates flow to `knowledge.experiments` with payload:

```sql
INSERT INTO knowledge.experiments (
    iteration_id, parent_strategy_id, mutation_diff,
    fitness_report, regime_context, kept, discard_reason,
    timestamp, embedding
) VALUES (...);
```

The `embedding` is computed from the mutation diff plus regime context, enabling Archivist to retrieve "have we tried this kind of thing before?" via pgvector similarity search at the start of every Hunter prompt construction.

### 6.7 Bootstrap LLM economics

Compressed-history replay (§6.5) projects 4–6 weeks of wall-clock to walk 2018 → vault boundary at thousands of mutations × 1 LLM call/mutation. This exceeds tier-1 cloud-provider RPM quotas under any reasonable iteration budget; the math only pencils with a primary local LLM.

**Plan:**
- **Bootstrap primary:** `ollama/gemma4:latest` on host Metal GPU. Free; rate-limited only by hardware throughput. Phase 0 acceptance criterion #5 (LiteLLM round-trip against ≥2 providers including Ollama) verifies the path; Phase 0 must additionally measure throughput and confirm it meets the schedule (target: 30–60 mutations/hour empirically; verify on actual hardware).
- **Cloud LLM reserved for:**
  - Hard mutations Hunter can't make headway on locally — escalation triggered by Archivist when KB indicates "we've been stuck on this regime for N attempts"
  - Weekend Archivist Level-2 / Level-3 synthesis (long-context reasoning, Gemini)
  - Weekly web research (long-document fundamental analysis, Gemini)
- **If Phase 0 throughput measurement fails** the bootstrap schedule, options are: extend bootstrap wall-clock, budget cloud-tier upgrade (real cost, link to Plan §27), or reduce `experiments_per_day` in compressed-replay (the §6.5 cadence is adjustable).

### 6.8 What we copy from `vendor/autoresearch/`, what we discard

**Copy (and adapt):** `program.md` → `training/program.md` (rewritten for trading-strategy mutation); loop scaffolding patterns from upstream `train.py` → inform our `training/loop.py` structure.

**Discard:** GPT model code, `prepare.py`, anything tied to language modeling.

The vendored `vendor/autoresearch/` directory exists primarily to preserve the upstream LICENSE and copyright reference. It is not on the import path.

## 7. Local Docker Compose Topology

### 7.1 `docker-compose.yml` services

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg16
    ports: ["5432:5432"]
    volumes:
      - ./data/postgres:/var/lib/postgresql/data
      - ./infra/postgres/migrations:/docker-entrypoint-initdb.d
    environment:
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]

  litellm:
    image: ghcr.io/berriai/litellm:latest
    ports: ["4000:4000"]
    volumes:
      - ./infra/litellm/config.yaml:/app/config.yaml:ro
    environment:
      OPENROUTER_API_KEY: ${OPENROUTER_API_KEY}
      GEMINI_API_KEY: ${GEMINI_API_KEY}
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY}
      OPENAI_API_KEY: ${OPENAI_API_KEY}
      XAI_API_KEY: ${XAI_API_KEY}
    extra_hosts:
      - "host.docker.internal:host-gateway"   # for Ollama on host

  nemoclaw:
    build:
      context: ./vendor/nemoclaw
      dockerfile: Dockerfile
    volumes:
      - ./infra/nemoclaw-config:/etc/nemoclaw:ro
      - ./data/nemoclaw-state:/var/lib/nemoclaw
    depends_on:
      postgres: { condition: service_healthy }
      litellm: { condition: service_started }

  hunter:
    build: { context: ./services/hunter }
    depends_on: [nemoclaw, litellm, postgres]

  guardian:
    build: { context: ./services/guardian }
    depends_on: [nemoclaw, litellm, postgres]

  archivist:
    build: { context: ./services/archivist }
    depends_on: [nemoclaw, litellm, postgres]

  data-ingest:
    build: { context: ./services/data-ingest }
    volumes: ["./data/parquet:/data/parquet"]
    depends_on: [postgres]

  regime-detector:
    build: { context: ./services/regime-detector }
    volumes: ["./data/parquet:/data/parquet:ro"]
    depends_on: [postgres]

  execution:
    build: { context: ./services/execution }
    depends_on: [postgres, nemoclaw]

  training:
    build: { context: ./services/training }
    volumes: ["./data/parquet:/data/parquet:ro"]
    depends_on: [postgres]

# Note: all persistence uses bind mounts under ./data/ (host filesystem) rather than
# named volumes, so backups, inspection, and migration to cloud are straightforward.
```

### 7.2 Volumes & networks

- Default Docker bridge network for inter-service traffic
- Named volumes for Postgres data and NemoClaw state
- Bind mount for parquet (read-only to consumers, read-write to `data-ingest`)
- Bind mount for `infra/nemoclaw-config/` (read-only)

### 7.3 Ports & host bindings

| Service | Container port | Host binding | Notes |
|---|---|---|---|
| postgres | 5432 | 5432 | dev access from host SQL clients |
| litellm | 4000 | 4000 | dev access for testing model calls |
| nemoclaw | inherits from upstream image | not exposed | internal Docker network only; verify in Phase 0 against current NemoClaw release |
| Streamlit dashboard (Phase 6) | 8501 | 8501 | local UI |

Ollama runs on the host, not in Compose. Container access via `host.docker.internal:11434`.

### 7.4 Resource limits per service (Apple Silicon RAM budget on 16 GB host)

| Service | Memory cap | Notes |
|---|---|---|
| postgres | 2 GB | grows with KB embeddings; revisit Phase 4 |
| litellm | 512 MB | thin proxy |
| nemoclaw | 1 GB | per upstream guidance |
| each agent (hunter/guardian/archivist) | 1 GB | per `sandbox-policies.yaml` |
| stateless workers | 512 MB each | bursty; vectorbt on training spikes higher |
| training (vectorbt heavy) | 4 GB cap, expect 2 GB typical | heaviest worker |

Ollama on host can use all remaining RAM for Gemma 4 inference. Memory requirement depends on Gemma 4 release variant; Phase 0 verifies sized model fits within available RAM and meets the bootstrap throughput target (see §6.8).

## 8. Upstream Tracking Workflow

### 8.1 NemoClaw subtree pull cadence

- **Routine:** monthly. First business day of the month.
- **Security:** within 72h of CVE disclosure or NVIDIA security advisory.
- **Major releases:** within 2 weeks of upstream tagging a new minor version.

### 8.2 CVE monitoring

- Subscribe to GitHub security advisories on `NVIDIA/NemoClaw`
- Subscribe to GitHub releases via RSS or Actions cron
- Phase 6+: integrate into Telegram bot as a notification target

### 8.3 Integration test gate

Before any subtree pull is merged to `main`, the following pass on a feature branch:

1. `docker compose up` brings the full stack online without errors
2. Unit tests for `services/*` pass
3. Integration smoke test: each agent registers, exchanges a heartbeat message, makes one LLM round-trip via LiteLLM, writes one row to Postgres
4. Compressed-replay smoke test: 5 iterations of the autoresearch loop on a tiny historical slice
5. All Tier 3 patches (if any) still apply cleanly

If any check fails, the pull is blocked pending investigation.

## 9. Acceptance Criteria

These gate the Phase 0–3 exits.

### Phase 0 — Substrate bring-up (2 weeks)

1. `git subtree add` succeeds; `vendor/nemoclaw/` populated at a known tag
2. `git subtree pull` exercise (no-op pull or test pull) completes without conflict
3. `docker compose up` brings all services online; healthchecks pass
4. Postgres migrations apply; all schemas exist
5. LiteLLM gateway answers an inference call against at least 2 providers (Ollama + one cloud)
6. A trivial heartbeat agent registers with NemoClaw, subscribes to a test channel, round-trips a message
7. CI pipeline runs lint + tests + integration smoke on every push

### Phase 1 — Foundation (8 weeks)

8. `data-ingest` populates `data/parquet/ohlcv/` with 8+ years for the universe
9. Vault embargo enforced at the data-access boundary; tested by attempting to read inside vault and getting a hard rejection
10. 70+ engineered features computed and persisted
11. `regime-detector` exposes `compute_regime(date)` and reports ≥75% accuracy on labeled historical sample
12. Vectorbt backtest harness wraps a `Strategy` and produces a `FitnessReport` in <30s for a typical strategy

### Phase 2 — Five-Wall Fortress (6 weeks)

13. Each of the 5 walls is a callable predicate with a deterministic test
14. A deliberately-overfit canary strategy is rejected by Wall 1 (PBO test) — automated test asserts this
15. Three-gate system implemented; passes calibration on a known-good and known-bad historical strategy

### Phase 3 — Autoresearch Loop Core (13 weeks)

16. Hunter, Guardian, Archivist register at startup and exchange messages over their declared channels
17. `autoresearch_iteration()` runs end-to-end with the kernel in §6.4
18. Nightly cadence runs unattended for 8 hours, completing ≥50 iterations, ≥80% within budget, no crashes
19. Discarded candidates appear in `knowledge.experiments` with `kept=false` and a reason
20. Promoted candidates appear as commits in the strategy registry with parent ID, mutation diff hash, and FitnessReport hash in the commit message
21. Compressed-replay walks at least 3 historical years end-to-end without look-ahead-bias detection failures
22. Vault validation: a strategy promoted from training data is evaluated on the 6-month vault holdout and the result matches in-sample within an acceptable tolerance

## 10. Open Questions & Known Unknowns

These are flagged but do not block Phases 0–3. They will be resolved in implementation or in subsequent specs. (Cross-cutting open questions affecting the whole project are in the architecture spec §9; the list below is integration-spec-scoped.)

1. **NemoClaw plugin/extension API maturity & abandonment risk.** Alpha software (released March 2026). Tier 1 config surface may shift between minor versions. NVIDIA could pause or deprecate the project. Mitigation:
   - **Routine instability:** stay in Tier 1 extensions; pin to known-good tags; review release notes before each pull; integration test gate before merging any subtree pull.
   - **Abandonment contingency:** confine our use to a minimum substrate API surface (channel pub/sub, sandbox enforcement, agent lifecycle) any orchestration substrate could provide. Do *not* depend on NemoClaw-specific routed-inference layer (LiteLLM in front already protects this). Acceptable replacements if abandoned: LangGraph, raw Docker + nats.io, custom orchestrator. Verify quarterly that agents would port to a replacement substrate within ~2 person-weeks.
2. **NemoClaw's exact channel-payload schema mechanism.** Whether NemoClaw natively validates JSON Schema on channel payloads or requires a thin wrapper in our agents. Verify Phase 0; adapt §5.2 accordingly.
3. **LiteLLM provider behavior under load.** Rate limits, fallback timing, cost-cap enforcement under burst. Empirical investigation in Phase 3 once nightly cadence is running.
4. **pgvector vs. dedicated vector DB at scale.** pgvector is the right call for tens of millions of embeddings. If KB grows past ~50M entries, a dedicated vector DB (Qdrant, Milvus) may become preferable. Decision deferred until KB size approaches that scale.
5. **Bootstrap LLM throughput on actual hardware.** §6.7 plans Gemma-4-via-Ollama as primary bootstrap LLM at 30–60 mutations/hour empirically expected. Phase 0 must measure this against the actual MacBook Pro and confirm the 4–6-week bootstrap schedule is achievable, OR fall back to cloud tier (cost link to Plan §27) or reduce `experiments_per_day`.
6. **NemoClaw internal-state portability for cloud deployment.** When we move from local DEV to cloud PROD, NemoClaw's internal state needs migration. Verify mechanism during Phase 0; revisit in `cloud-deployment-spec.md`.
7. **Vendor patch upstream-PR cadence.** When we land Tier 3 patches, how aggressively do we attempt to upstream them? Trade-off between merge debt and maintenance burden. Policy decision deferred until first patch lands.
8. **Capital-stage thresholds (Plan §27).** $5K–$15K → $15K–$50K → $50K–$200K with Sharpe > 1.0 and 6–12-month track record as Stage 1→2 trigger is the plan's proposal. Confirm or revise during `live-trading-stage-1-spec.md`.
