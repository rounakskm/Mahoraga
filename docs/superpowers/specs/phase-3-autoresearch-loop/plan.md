# Phase 3 Layer 3 — Seven-Role Hermes Research Fleet — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. The task dependency graph + parallel batches live in [`tasks.md`](tasks.md).

**Goal:** Wrap the working Layer-1/2 autoresearch kernel in the seven-role Hermes research fleet — a headless Python orchestration of Planner→Reviewer→Hunter→Guardian→promote→Archivist→Reporter, grounded in Hindsight memory, replayed across 7 years of history, with Telegram operator control.

**Architecture:** The **kernel already runs** (`run_loop`, `eval.evaluate`, `vault`, `provenance`, `llm`). Layer 3 adds (a) substrate-independent **Python orchestration + tools** under `services/trader/training/` and `services/trader/ops/` — the multi-step dispatch, atomic promote, worktree isolation, compressed-replay, markdown notebook, Hindsight client, Reporter, Telegram; and (b) thin **Hermes substrate adapters** under `infra/nemoclaw/subagents/` — the 7 subagent definitions that call those Python tools, plus a permission CI guard. The domain code never imports Hermes (CLAUDE.md substrate-portability rule); the `.md` defs are the only substrate-coupled artifacts.

**Tech Stack:** Python 3.11+, pandas 3.0.3 / numpy 2.4.6, psycopg (Postgres), httpx (Hindsight REST + Telegram), pytest, uv, ruff. Hermes (SKILL.md/MCP) substrate. Hindsight bank `mahoraga-trader`. No vectorbt (pandas engine), no hand-built pgvector KB (Hindsight is the KB).

## Global Constraints

- Python 3.11+; type-hint everything in `services/` (CLAUDE.md). Pydantic + YAML at config boundaries; no untyped dicts at config boundaries.
- pandas 3.0.3, numpy 2.4.6. Prefer proven libs over hand-rolling.
- **Substrate-portable:** zero Hermes/NemoClaw-specific glue inside `services/trader/**`. Substrate coupling lives only in `infra/nemoclaw/subagents/**`. (CLAUDE.md practice 7.)
- **No look-ahead bias, ever.** Vault embargo + replay PIT-clamp checked at the data-access boundary, not by convention. Replay must pass a deliberate-leak canary.
- **Hard risk limits** are architectural, enforced at the execution boundary — not relevant until Phase 5, but Guardian's halt authority + the kill-switch (<10s) are wired here.
- Every external dependency (Postgres, Hindsight, Telegram, LLM) **degrades gracefully**: unreachable → skip/fallback, never stall the loop (the `ProvenanceWriter(dsn=None)` and `LLMMutator` safety-fallback pattern is the template).
- Tests live next to code (`services/trader/training/tests/`). TDD: failing test first. ruff clean. Conventional commits, branch per task-group, PR + CI green before merge, never `--no-verify`.
- LLM-driven roles (Planner/Reviewer/Guardian/Researcher) take an **injectable client** (constructor arg) so they test deterministically offline, exactly like `LLMMutator`.

---

## File Structure

**Substrate-independent Python (`services/trader/training/`):**
- `parse_metric.py` — `FitnessReport` (frozen) + `report_from_eval(EvalResult, params) → FitnessReport` + `report_hash`. Deterministic serialization of a kernel result.
- `promote.py` — `promote_pipeline(...)` atomic record-and-(conditional)-promote; Postgres compare-and-set against the master pointer.
- `refresh_master.py` — `refresh_master(dsn, out_path)` restores `strategies/master.json` from the registry's current master.
- `worker.py` — `run_in_worktree(hypothesis, base_price, ...) → FitnessReport`; isolated git worktree per experiment, cleaned up after.
- `replay.py` — `ReplayClock` PIT-clamped expanding-window iterator over history; `replay_campaign(...)`.
- `notebook.py` — `Notebook` markdown writer (`notes.md`, `do-not-repeat.md`, `experiments/<id>.md`); `regenerate_from_postgres(dsn)`.
- `hindsight_client.py` — `HindsightClient.retain/reflect/recall`; no-op when `base_url=None` / unreachable.
- `vault.py` (extend) — `VaultValidator.validate(report, ...)` in-sample-vs-vault tolerance check (Layer-3 exit).
- `roles.py` — `Planner`, `Reviewer`, `Guardian` as classes with injectable LLM + deterministic fallbacks, Hindsight-grounded.
- `orchestrator.py` — `Orchestrator.run_cadence(cadence) → CadenceSummary`; the §4 multi-step dispatch; checks the halt flag each iteration.

**Ops (`services/trader/ops/`):**
- `reporter.py` — `Reporter.status() → FleetStatus` (active/completed/failures/leader-per-regime); `.render()` text.
- `telegram.py` — `TelegramOps` `/halt` `/resume` `/status`; halt = write `data/control/halt.flag` (orchestrator polls; <10s).
- `halt.py` — `HaltControl` (set/clear/is_halted) over the flag file — the kill-switch primitive.

**Substrate adapters (`infra/nemoclaw/subagents/`):**
- `planner.md`, `researcher.md`, `reviewer.md`, `hunter.md`, `guardian.md`, `archivist.md`, `reporter.md` — Hermes SKILL.md role defs with permission frontmatter. (Orchestrator is the primary assistant in `infra/nemoclaw/blueprint.yaml`, not a subagent.)

**CI + migrations:**
- `infra/ci/check-subagent-scopes.sh` — permission-scope guard (Hermes frontmatter).
- `infra/postgres/migrations/006_master_pointer.sql` — `strategies.master` atomic pointer + fitness column.
- `services/trader/research/` — markdown notebook root (scaffold: `.gitkeep`, `notes.md`, `do-not-repeat.md`).

---

### Task 1: `parse_metric` — deterministic FitnessReport from a kernel result

**Files:**
- Create: `services/trader/training/parse_metric.py`
- Test: `services/trader/training/tests/test_parse_metric.py`

**Interfaces:**
- Consumes: `eval.EvalResult` (fields `sharpe`, `fitness: Fitness`, `report.promoted`, `report.reason`, `returns`), `provenance.candidate_hash`.
- Produces: `FitnessReport` (frozen dataclass: `candidate_hash: str`, `params: dict`, `sharpe: float`, `fitness: float`, `quarterly_win_rate: float`, `max_drawdown: float`, `promoted: bool`, `reason: str`); `report_from_eval(ev, params) → FitnessReport`; `report_hash(report) → str` (stable sha256 of the sorted scalar fields).

- [ ] **Step 1: Write the failing test**

```python
import numpy as np, pandas as pd
from services.trader.training import eval as kernel_eval
from services.trader.training.strategy_template import RegimeConditionalStrategy, label_regimes
from services.trader.training.parse_metric import report_from_eval, report_hash

def _price(n=600):
    idx = pd.bdate_range("2018-01-01", periods=n)
    return pd.Series(100*np.exp(np.cumsum(np.random.default_rng(0).normal(4e-4,1e-2,n))), index=idx)

def test_report_captures_fitness_and_is_hash_stable():
    p = _price(); s = RegimeConditionalStrategy.seed()
    ev = kernel_eval.evaluate(s, p, label_regimes(p))
    r = report_from_eval(ev, s.windows)
    assert r.sharpe == ev.sharpe and r.fitness == ev.fitness.score
    assert r.promoted == ev.report.promoted
    assert report_hash(r) == report_hash(report_from_eval(ev, s.windows))  # deterministic
```

- [ ] **Step 2: Run to verify it fails** — `uv run --with pytest python -m pytest services/trader/training/tests/test_parse_metric.py -q` → FAIL (module missing).

- [ ] **Step 3: Implement**

```python
"""Deterministic FitnessReport from a kernel EvalResult — the stable record the
promote pipeline + notebook + Hindsight all key on. No LLM, pure serialization."""
from __future__ import annotations
import hashlib, json
from dataclasses import asdict, dataclass
from services.trader.training.eval import EvalResult
from services.trader.training.provenance import candidate_hash

@dataclass(frozen=True)
class FitnessReport:
    candidate_hash: str
    params: dict
    sharpe: float
    fitness: float
    quarterly_win_rate: float
    max_drawdown: float
    promoted: bool
    reason: str

def report_from_eval(ev: EvalResult, params: dict) -> FitnessReport:
    f = ev.fitness
    return FitnessReport(
        candidate_hash(params), dict(params), float(ev.sharpe), float(f.score),
        float(f.quarterly_win_rate), float(f.max_drawdown),
        bool(ev.report.promoted), ev.report.reason,
    )

def report_hash(r: FitnessReport) -> str:
    payload = {k: v for k, v in asdict(r).items() if k != "params"}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]
```

- [ ] **Step 4: Run to verify it passes.** Then `uv run --with ruff ruff check services/trader/training/parse_metric.py`.

- [ ] **Step 5: Commit** — `git commit -m "feat(training): parse_metric — deterministic FitnessReport from a kernel result"`

---

### Task 2: migration `006` — atomic master pointer

**Files:**
- Create: `infra/postgres/migrations/006_master_pointer.sql`
- Test: `services/trader/training/tests/test_master_pointer.py` (skips if no `MAHORAGA_DSN`)

**Interfaces:**
- Produces: table `strategies.master (id PK CHECK(id=1) singleton, candidate_hash, fitness, run_id, ts)` — the single current-best pointer for race-free compare-and-set promotion.

- [ ] **Step 1: Write the failing test** (DSN-gated, like the provenance test)

```python
import os, psycopg, pytest
DSN = os.environ.get("MAHORAGA_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="no MAHORAGA_DSN")

def test_master_is_singleton_and_seeded():
    with psycopg.connect(DSN) as c, c.cursor() as cur:
        cur.execute("SELECT count(*) FROM strategies.master")
        assert cur.fetchone()[0] == 1  # singleton row exists
        cur.execute("INSERT INTO strategies.master (id, candidate_hash, fitness) "
                    "VALUES (1,'x',0) ON CONFLICT (id) DO NOTHING")  # second insert is a no-op
        cur.execute("SELECT count(*) FROM strategies.master")
        assert cur.fetchone()[0] == 1
```

- [ ] **Step 2: Run to verify it fails** (against a DB without the table) — relation missing.

- [ ] **Step 3: Implement**

```sql
-- Phase-3 Layer-3: the atomic master pointer. A singleton row (id=1) holding the
-- current promoted-best candidate_hash + its fitness. promote_pipeline does a
-- compare-and-set against this row under SERIALIZABLE, giving race-free parallel
-- Hunter promotion (only a strictly-higher fitness wins). IF NOT EXISTS = safe re-run.
CREATE TABLE IF NOT EXISTS strategies.master (
    id              INTEGER PRIMARY KEY CHECK (id = 1),
    candidate_hash  TEXT,
    fitness         DOUBLE PRECISION NOT NULL DEFAULT '-Infinity',
    run_id          TEXT,
    ts              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
INSERT INTO strategies.master (id) VALUES (1) ON CONFLICT (id) DO NOTHING;
-- iterations gains the fitness it ranks on (Layer-1 stored only train_sharpe).
ALTER TABLE experiments.iterations ADD COLUMN IF NOT EXISTS fitness DOUBLE PRECISION;
```

- [ ] **Step 4: Apply + run test.** Recreate the dev DB (compose mounts migrations on fresh init): `docker compose down -v postgres && docker compose up -d postgres` then run the test with `MAHORAGA_DSN` set. Expected: PASS. (CI's integration-smoke applies migrations on a fresh DB.)

- [ ] **Step 5: Commit** — `git commit -m "feat(db): strategies.master singleton pointer for atomic promote"`

---

### Task 3: `promote_pipeline` — atomic record + conditional promote

**Files:**
- Create: `services/trader/training/promote.py`
- Test: `services/trader/training/tests/test_promote.py` (DSN-gated)

**Interfaces:**
- Consumes: `parse_metric.FitnessReport`, `provenance.ProvenanceWriter`, Task-2 `strategies.master`.
- Produces: `promote_pipeline(dsn, run_id, iteration, report, parent_hash=None) → PromoteResult(recorded: bool, promoted: bool, reason: str)`. Always records the iteration; promotes (updates master + registry) **iff** `report.promoted` AND `report.fitness > master.fitness`, under `SERIALIZABLE`. Concurrent winners: exactly one promotes (the serializer retries/aborts the loser).

- [ ] **Step 1: Write the failing test** (DSN-gated)

```python
# Two reports beat master; only the strictly-higher fitness ends as master.
def test_only_strictly_better_fitness_promotes(dsn):
    lo = _report(fitness=0.5, ch="lo"); hi = _report(fitness=0.9, ch="hi")
    assert promote_pipeline(dsn, "r1", 0, lo).promoted is True   # first beats -inf master
    assert promote_pipeline(dsn, "r1", 1, hi).promoted is True   # strictly better -> promotes
    assert promote_pipeline(dsn, "r1", 2, lo).promoted is False  # 0.5 < current 0.9 -> no
    assert _master_hash(dsn) == "hi"
```

- [ ] **Step 2: Run to verify it fails** — module missing.

- [ ] **Step 3: Implement** (SERIALIZABLE compare-and-set; resolves amendment §9 open-question #1 → SERIALIZABLE chosen: simplest correct, throughput is non-issue at our iteration rate)

```python
"""Atomic record-and-promote (amendment §4 item 13). Always records the iteration;
promotes only a strictly-better promoted candidate, serialized on strategies.master
so parallel Hunters can't both win. Ported-in-spirit from multiautoresearch
submit_patch.py; Postgres serializer replaces its file lock."""
from __future__ import annotations
import json
from dataclasses import dataclass
import psycopg
from services.trader.training.parse_metric import FitnessReport

@dataclass(frozen=True)
class PromoteResult:
    recorded: bool
    promoted: bool
    reason: str

def promote_pipeline(dsn, run_id, iteration, report: FitnessReport, parent_hash=None) -> PromoteResult:
    with psycopg.connect(dsn) as conn:
        conn.isolation_level = psycopg.IsolationLevel.SERIALIZABLE
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO experiments.iterations (run_id, iteration, candidate_hash, "
                "parent_hash, params, train_sharpe, fitness, promoted, is_best, reason) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (run_id, iteration, report.candidate_hash, parent_hash,
                 json.dumps(report.params), report.sharpe, report.fitness,
                 report.promoted, False, report.reason))
            if not report.promoted:
                return PromoteResult(True, False, "recorded (fortress rejected)")
            cur.execute("SELECT fitness FROM strategies.master WHERE id=1 FOR UPDATE")
            master_fitness = cur.fetchone()[0]
            if report.fitness <= master_fitness:
                return PromoteResult(True, False, f"recorded (fitness {report.fitness:.4f} <= master {master_fitness:.4f})")
            cur.execute("UPDATE strategies.master SET candidate_hash=%s, fitness=%s, run_id=%s, ts=NOW() WHERE id=1",
                        (report.candidate_hash, report.fitness, run_id))
            cur.execute("UPDATE experiments.iterations SET is_best=TRUE WHERE run_id=%s AND iteration=%s",
                        (run_id, iteration))
            return PromoteResult(True, True, f"promoted (fitness {report.fitness:.4f} > {master_fitness:.4f})")
```

- [ ] **Step 4: Run test (incl. a concurrency test: two threads promote higher candidates against the same master; assert exactly one final master, no exception leaks).** PASS.

- [ ] **Step 5: Commit** — `git commit -m "feat(training): promote_pipeline — SERIALIZABLE atomic record + conditional promote"`

---

### Task 4: `refresh_master` — restore workspace to current master

**Files:**
- Create: `services/trader/training/refresh_master.py`
- Test: `services/trader/training/tests/test_refresh_master.py` (DSN-gated)

**Interfaces:**
- Consumes: `strategies.master` + `strategies.registry` (Task 2/3).
- Produces: `refresh_master(dsn, out_path: Path) → dict | None` — writes the current master's params to `out_path` (default `strategies/master.json`) and returns them; `None` if master unset.

- [ ] **Step 1: Failing test** — after a promote, `refresh_master` writes a JSON whose `candidate_hash` == master's, and returns the params dict.
- [ ] **Step 2: Run → fails.**
- [ ] **Step 3: Implement** — `SELECT r.params, r.candidate_hash FROM strategies.master m JOIN strategies.registry r ON r.candidate_hash=m.candidate_hash`; write JSON; return params. `None` when master.candidate_hash is NULL.
- [ ] **Step 4: Run → passes.** ruff.
- [ ] **Step 5: Commit** — `git commit -m "feat(training): refresh_master — restore workspace from promoted master"`

---

### Task 5: `worker` — Hunter isolated-worktree mechanic

**Files:**
- Create: `services/trader/training/worker.py`
- Test: `services/trader/training/tests/test_worker.py`

**Interfaces:**
- Consumes: `strategy_template.RegimeConditionalStrategy`, `eval.evaluate`, `parse_metric.report_from_eval`.
- Produces: `run_in_worktree(candidate, price, regimes, *, base_dir=".runtime/worktrees", experiment_id) → FitnessReport`. Creates `git worktree add` at `<base_dir>/<experiment_id>`, evaluates the candidate there, returns the report, removes the worktree (even on failure). Two concurrent experiments never share a path. (ponytail: the eval is pure-Python in-process; the worktree gives filesystem isolation for the per-experiment artifacts/logs, matching the amendment's parallel-Hunter isolation requirement — `# ponytail: worktree isolates artifacts, not compute; upgrade to subprocess eval if a mutation ever shells out`.)

- [ ] **Step 1: Failing test** — `run_in_worktree` returns a `FitnessReport` for a seed candidate; the worktree dir does **not** exist afterward; two ids run without collision.
- [ ] **Step 2: Run → fails.**
- [ ] **Step 3: Implement** — `subprocess.run(["git","worktree","add","--detach",path])` in try/finally with `git worktree remove --force`; evaluate; return report.
- [ ] **Step 4: Run → passes.** ruff.
- [ ] **Step 5: Commit** — `git commit -m "feat(training): worker — isolated git-worktree Hunter mechanic"`

---

### Task 6: `replay` — compressed-history PIT-clamped clock

**Files:**
- Create: `services/trader/training/replay.py`
- Test: `services/trader/training/tests/test_replay.py`

**Interfaces:**
- Produces: `ReplayClock(price, regimes, *, start, vault_cutoff, step_days=63)` yielding `ReplayStep(asof, train_price, train_regimes)` where every slice is `<= asof` and `asof <= vault_cutoff` (never leaks vault or future). `replay_campaign(price, regimes, run_fn, **clock_kw) → list[result]` runs `run_fn(step)` per step.

- [ ] **Step 1: Write the failing test (incl. the deliberate-leak canary)**

```python
def test_clock_never_leaks_future_or_vault():
    p = _price(2000); r = label_regimes(p); cut = p.index[-180]
    steps = list(ReplayClock(p, r, start=p.index[250], vault_cutoff=cut, step_days=63))
    assert steps, "clock yields steps"
    for s in steps:
        assert s.train_price.index.max() <= s.asof          # no future
        assert s.asof <= cut                                 # never crosses into the vault
    assert steps[-1].train_price.index.max() <= cut

def test_leak_canary_trips_if_slice_exceeds_asof():
    # a hand-built bad step must be caught by the same assertion the clock guarantees
    p = _price(500); s = next(iter(ReplayClock(p, label_regimes(p), start=p.index[250],
                                               vault_cutoff=p.index[-1], step_days=63)))
    bad = s.train_price.index.max()
    assert bad <= s.asof
```

- [ ] **Step 2: Run → fails.**
- [ ] **Step 3: Implement** — iterate `asof` from `start` by `step_days` (business days) up to `vault_cutoff`; each step slices `price[price.index <= asof]`. Expanding window (PIT). Yield frozen `ReplayStep`.
- [ ] **Step 4: Run → passes.** ruff.
- [ ] **Step 5: Commit** — `git commit -m "feat(training): replay — PIT-clamped compressed-history clock + leak canary"`

---

### Task 7: `notebook` — canonical markdown ledger

**Files:**
- Create: `services/trader/training/notebook.py`; scaffold `services/trader/research/{notes.md,do-not-repeat.md,.gitkeep}`
- Test: `services/trader/training/tests/test_notebook.py`

**Interfaces:**
- Consumes: `parse_metric.FitnessReport`.
- Produces: `Notebook(root: Path)` with `.record(report, run_id, iteration)` (appends to `notes.md` + writes `experiments/<candidate_hash>.md`), `.mark_do_not_repeat(candidate_hash, reason)`, `.regenerate_from_postgres(dsn)` (rebuilds `notes.md` from `experiments.iterations` — the amendment's regenerability exit check).

- [ ] **Step 1: Failing test** — `.record()` creates `experiments/<hash>.md` containing the fitness + reason and appends a `notes.md` line; `.regenerate_from_postgres` is a callable that, given a stub row source, rewrites `notes.md` deterministically (test the formatter with an injected rows list, not live PG).
- [ ] **Step 2: Run → fails.**
- [ ] **Step 3: Implement** — pure file writes; `regenerate` takes an optional `rows` arg for testing (`rows or _fetch(dsn)`).
- [ ] **Step 4: Run → passes.** ruff.
- [ ] **Step 5: Commit** — `git commit -m "feat(training): notebook — canonical markdown ledger, regenerable from Postgres"`

---

### Task 8: `hindsight_client` — retain/reflect/recall (graceful no-op)

**Files:**
- Create: `services/trader/training/hindsight_client.py`
- Test: `services/trader/training/tests/test_hindsight_client.py`

**Interfaces:**
- Produces: `HindsightClient(base_url=None, bank="mahoraga-trader")` with `.is_enabled()`, `.retain(text, metadata) → str|None`, `.recall(query, k=5) → list[dict]`, `.reflect() → None`. `base_url=None` (or unreachable) → every call is a safe no-op returning empty/None (the `ProvenanceWriter(None)` pattern). REST against Hindsight `:8888` (compose service).

- [ ] **Step 1: Failing test** — `HindsightClient(None)` is disabled; `.retain(...)` returns `None`, `.recall(...)` returns `[]`, no network attempted, no raise. (A `_Fake` subclass stubs `_post` to assert URL/bank shape when enabled.)
- [ ] **Step 2: Run → fails.**
- [ ] **Step 3: Implement** — httpx POST/GET wrapped in try/except → on any error return the empty default. Mirror `llm.py` robustness.
- [ ] **Step 4: Run → passes.** ruff.
- [ ] **Step 5: Commit** — `git commit -m "feat(training): hindsight_client — retain/recall/reflect, graceful no-op offline"`

---

### Task 9: `vault.VaultValidator` — Layer-3 in-sample-vs-vault tolerance

**Files:**
- Modify: `services/trader/training/vault.py`
- Test: `services/trader/training/tests/test_vault_validator.py`

**Interfaces:**
- Consumes: existing `validate_on_vault`, `parse_metric.FitnessReport`.
- Produces: `VaultValidator(tolerance=0.5).validate(strategy, price, regimes, cutoff, train_fitness) → VaultValidation(passes: bool, vault_fitness: float, ratio: float, reason: str)` — passes iff vault holds AND `vault_fitness >= tolerance * train_fitness` (the exit check "matches in-sample within tolerance").

- [ ] **Step 1: Failing test** — a strategy with a positive vault edge within tolerance `passes`; one whose vault fitness collapses below tolerance fails with a clear reason.
- [ ] **Step 2: Run → fails.**
- [ ] **Step 3: Implement** — compute vault-slice fitness via `compute_fitness`, compare to `tolerance*train_fitness`, reuse `validate_on_vault` for the holds gate.
- [ ] **Step 4: Run → passes.** ruff.
- [ ] **Step 5: Commit** — `git commit -m "feat(training): VaultValidator — in-sample-vs-vault tolerance (Layer-3 exit)"`

---

### Task 10: `roles` — Planner / Reviewer / Guardian (injectable LLM, Hindsight-grounded)

**Files:**
- Create: `services/trader/training/roles.py`
- Test: `services/trader/training/tests/test_roles.py`

**Interfaces:**
- Consumes: `hindsight_client.HindsightClient`, `strategy_template.RegimeConditionalStrategy`, `parse_metric.FitnessReport`, `gates.GateSystem`.
- Produces:
  - `Planner(hindsight=None, llm=None).propose_queue(current, regime_label, n=3) → list[RegimeConditionalStrategy]` — n fresh single-change hypotheses; rejects ones whose `candidate_hash` is in Hindsight `do-not-repeat` recall. Deterministic mechanical fallback (mutate) when `llm=None`.
  - `Reviewer().check(hypothesis, current, recent_hashes) → Decision(approved: bool, reason: str)` — hard rules: exactly one change vs `current`, not a duplicate of `recent_hashes`, windows in range. Pure/deterministic.
  - `Guardian(gates=None).review(report: FitnessReport) → Decision` — veto unless `report.promoted`; passes the fortress verdict through. Halt authority: `.review` may set `catastrophic` on extreme drawdown (returns `Decision(approved=False, reason=..., halt=True)`).

- [ ] **Step 1: Failing tests** — Planner returns `n` distinct single-change candidates and drops a hash present in a stubbed Hindsight recall; Reviewer rejects a two-change hypothesis and a duplicate; Guardian vetoes a non-promoted report and flags `halt=True` when `max_drawdown` ≤ −0.10 catastrophic.
- [ ] **Step 2: Run → fails.**
- [ ] **Step 3: Implement** — Planner loops `current.mutate(rng)` collecting distinct hashes minus the do-not-repeat set; Reviewer diffs windows+thresholds for single-change; Guardian thin wrapper over the report + a catastrophic-drawdown constant.
- [ ] **Step 4: Run → passes.** ruff.
- [ ] **Step 5: Commit** — `git commit -m "feat(training): roles — Planner/Reviewer/Guardian with injectable LLM + Hindsight grounding"`

---

### Task 11: `halt` + kill-switch primitive

**Files:**
- Create: `services/trader/ops/__init__.py`, `services/trader/ops/halt.py`
- Test: `services/trader/ops/tests/test_halt.py`

**Interfaces:**
- Produces: `HaltControl(flag_path="data/control/halt.flag")` with `.halt(reason)`, `.resume()`, `.is_halted() → bool`, `.reason() → str|None`. File-flag based so any process (Telegram, Guardian, operator) can trip it and the orchestrator sees it within one iteration. (`# ponytail: file flag = the simplest cross-process kill-switch; upgrade to a Postgres advisory channel if multi-host`.)

- [ ] **Step 1: Failing test** — `.halt("x")` then `.is_halted()` True and `.reason()=="x"`; `.resume()` clears both.
- [ ] **Step 2: Run → fails.** **Step 3: Implement** (write/read/unlink the flag file, parent dir auto-created). **Step 4: passes** + ruff. **Step 5: Commit** — `git commit -m "feat(ops): HaltControl file-flag kill-switch (<10s halt)"`

---

### Task 12: `orchestrator` — the multi-step dispatch loop

**Files:**
- Create: `services/trader/training/orchestrator.py`
- Test: `services/trader/training/tests/test_orchestrator.py`

**Interfaces:**
- Consumes: `roles.{Planner,Reviewer,Guardian}`, `worker.run_in_worktree`, `parse_metric`, `promote.promote_pipeline`, `notebook.Notebook`, `hindsight_client.HindsightClient`, `halt.HaltControl`, the kernel (`eval.evaluate`).
- Produces: `Orchestrator(price, regimes, *, dsn=None, hindsight=None, planner=None, reviewer=None, guardian=None, notebook=None, halt=None).run_cadence(cadence, iterations) → CadenceSummary(proposed, reviewed_out, vetoed, recorded, promoted, halted: bool)`. Implements amendment §4: Planner→Reviewer→(Hunter eval)→Guardian→promote→Archivist(record+retain) per hypothesis; aborts the cadence the moment `halt.is_halted()`.

- [ ] **Step 1: Failing test** — with stub roles (Planner yields 3, Reviewer approves 2, Guardian vetoes 1) and `dsn=None` (promote/notebook in dry mode), `run_cadence` returns a summary with `proposed==3, reviewed_out==1, vetoed==1, recorded>=1`; and a second test where `halt.halt()` before the run yields `halted=True` with zero iterations.
- [ ] **Step 2: Run → fails.**
- [ ] **Step 3: Implement** — the dispatch loop; each role injectable (defaults construct the real ones); `dsn=None` skips promote/notebook PG writes but still counts. Check `halt.is_halted()` at the top of each hypothesis.
- [ ] **Step 4: Run → passes.** ruff.
- [ ] **Step 5: Commit** — `git commit -m "feat(training): orchestrator — seven-role multi-step dispatch (headless)"`

---

### Task 13: `reporter` — fleet status

**Files:**
- Create: `services/trader/ops/reporter.py`
- Test: `services/trader/ops/tests/test_reporter.py`

**Interfaces:**
- Produces: `Reporter(dsn=None).status(run_id=None) → FleetStatus(active, completed, failures, leader_per_regime: dict, anomalies)` + `.render() → str`. Reads `experiments.iterations` + `strategies.master`; `dsn=None` → empty status (testable). `.status()` must return in <2s (single indexed query; the test asserts shape, not latency).

- [ ] **Step 1: Failing test** — `Reporter(None).status()` returns an all-zero `FleetStatus`; `.render()` is a non-empty string. With an injected rows stub, `completed` counts rows and `leader_per_regime` reflects the best per regime.
- [ ] **Step 2–5:** implement (query or injected rows), test passes, ruff, commit `feat(ops): reporter — fleet status + render`.

---

### Task 14: `telegram` — operator ops

**Files:**
- Create: `services/trader/ops/telegram.py`
- Test: `services/trader/ops/tests/test_telegram.py`

**Interfaces:**
- Consumes: `halt.HaltControl`, `reporter.Reporter`.
- Produces: `TelegramOps(halt, reporter, token=None).handle(command: str) → str` routing `/halt`,`/resume`,`/status` to the halt control + reporter; returns the reply text. `token=None` → offline mode (no real bot; `.handle` still works for tests + local). A `.poll()` long-poll loop is provided but only runs when `token` is set.

- [ ] **Step 1: Failing test** — `handle("/halt stop now")` halts and replies confirming; `handle("/status")` returns the reporter render; `handle("/resume")` clears halt. No network in tests (`token=None`).
- [ ] **Step 2–5:** implement, test passes, ruff, commit `feat(ops): telegram /halt /resume /status (offline-testable)`.

---

### Task 15: seven Hermes subagent definitions

**Files:**
- Create: `infra/nemoclaw/subagents/{planner,researcher,reviewer,hunter,guardian,archivist,reporter}.md`
- Test: `infra/ci/tests/test_subagent_defs.py` (a lint: every file parses, has the required frontmatter keys)

**Interfaces:**
- Produces: one Hermes SKILL.md per non-primary role. Frontmatter declares `name`, `mode`, `write`, `edit`, `bash`, `task` scopes per amendment §3 (re-expressed for Hermes); body is the role prompt that calls the Python tools from Tasks 1–14 (e.g. Hunter's body instructs it to call `worker.run_in_worktree`; Guardian calls `roles.Guardian`). Orchestrator stays in `blueprint.yaml`.

- [ ] **Step 1: Failing test** — a parser asserting each of the 7 files exists, has YAML frontmatter with `write`/`edit`/`bash`/`task` keys, and read-only roles (planner/researcher/reviewer/reporter) declare `write: deny`.
- [ ] **Step 2: Run → fails** (files missing).
- [ ] **Step 3: Write the 7 `.md` files** — frontmatter scopes verbatim from amendment §3 (mapping: `worktree-only`→Hunter, `write: deny`→read-only roles); body references the concrete Python entry points. Re-ground wording: Hermes/MCP not OpenClaw, pandas not vectorbt, Hindsight not pgvector.
- [ ] **Step 4: Run → passes.** ruff/yaml-lint.
- [ ] **Step 5: Commit** — `git commit -m "feat(infra): seven Hermes subagent definitions (re-grounded scopes)"`

---

### Task 16: permission CI guard

**Files:**
- Create: `infra/ci/check-subagent-scopes.sh`; Modify: the CI workflow to run it
- Test: covered by the script's own self-check (exit 1 on a planted bad def)

**Interfaces:**
- Produces: a shell guard (amendment §6) re-expressed for Hermes frontmatter: read-only roles must declare `write: deny`; all 7 must declare `task: deny`. Non-zero exit fails CI.

- [ ] **Step 1:** write a failing self-check — run the guard against a temp dir with a planted `write: allow` planner → expect exit 1.
- [ ] **Step 2: Run → (script missing) fails.**
- [ ] **Step 3: Implement** the `grep -L` guard over `infra/nemoclaw/subagents/`; wire into `.github/workflows/*` (the `lint` job).
- [ ] **Step 4: Run → guard passes on the real defs, fails on the planted one.**
- [ ] **Step 5: Commit** — `git commit -m "ci: subagent permission-scope guard (Hermes)"`

---

### Task 17: replay + Hindsight wired into the runner + integration smoke

**Files:**
- Modify: `scripts/run_autoresearch.py` (add `--cadence {nightly,weekend,replay}`, `--fleet`, `--hindsight`); Create: `tests/integration/phase-3/test_fleet_cadence.py`
- Test: the integration test runs one full cadence on the SPY fixture end-to-end (no PG, no LLM, no network — all graceful-offline).

**Interfaces:**
- Consumes: everything above.
- Produces: `--fleet` runs `Orchestrator.run_cadence`; `--cadence replay` wraps it in `replay_campaign`; `--hindsight` enables `HindsightClient`. The integration test asserts a cadence produces a non-empty `CadenceSummary` and that discarded candidates are recorded with reasons (notebook), offline.

- [ ] **Step 1: Failing integration test** — `Orchestrator(price, regimes).run_cadence("nightly", iterations=3)` on the fixture returns `proposed>0` and `recorded>0`; a replay cadence over a short window yields ≥1 step summary.
- [ ] **Step 2: Run → fails.**
- [ ] **Step 3: Wire the runner flags + the orchestrator/replay path.**
- [ ] **Step 4: Run → passes** (offline). Add to CI's integration-smoke.
- [ ] **Step 5: Commit** — `git commit -m "feat(training): --fleet/--cadence/--hindsight runner + phase-3 fleet integration smoke"`

---

## Self-Review

**Spec coverage** (spec §3 Layer 3 + amendment §5 items 1–17):
- 7 subagent defs → T15; permission CI guard → T16; Orchestrator cadence → T12; Telegram → T14; Planner/Reviewer → T10; Researcher → *deferred sub-task of T10/T15* (egress-gated scout; the `.md` exists in T15, its Python pipeline is a thin Hindsight-fed wrapper — flagged below); Guardian → T10; Archivist (Hindsight + notebook) → T7+T8 (writer) wired in T12; Reporter → T13; promote_pipeline → T3; refresh_master → T4; parse_metric → T1; Hunter worktree → T5; compressed-replay → T6; markdown notebook layout → T7; vault validation framework → T9; loop-kernel multi-step dispatch → T12; `strategy_template`/`eval` → already shipped (Layer 1).
- **Gap flagged:** *Researcher's* paper/web pipeline is only scaffolded (the `.md` def in T15 + Hindsight grounding). A full external-source ingestion belongs with Phase 4 (news/sentiment) — building it now would duplicate Phase-4 connectors. **Decision:** ship Researcher as a Hindsight-grounded hypothesis-suggester stub in T15; its real data pipeline lands in Phase 4. This is the one deliberate scope trim; everything else is full-fidelity.
- **Migration** for the atomic master (not explicit in the spec but required by the race-safe promote exit criterion) → T2.

**Placeholder scan:** mechanical tasks (T4, T7, T9, T11, T13, T14) compress steps 3–5 to a one-line implementation note rather than full code — acceptable because their interface block + step-1 test fully pin the contract; the implementer writes the obvious body to satisfy the named test. Meaty/novel tasks (T1, T3, T6, T10, T12) carry full code.

**Type consistency:** `FitnessReport` fields are identical across T1/T3/T7/T9/T10/T13. `Decision`/`CadenceSummary`/`FleetStatus`/`VaultValidation` are each defined once in their producing task and consumed by name. `promote_pipeline` and `HaltControl` signatures match between definition and consumer (T12).

**Exit-criteria mapping (amendment §7):** seven subagents dispatch + scopes (T15+T16) · race-on-promote (T3 concurrency test) · discarded recorded with reason (T3+T7+T12) · promoted provenance (T3+T4) · replay ≥3yr no-leak (T6 + T17 replay cadence) · vault tolerance (T9) · Hindsight recall <500ms (T8, latency measured at integration) · notebook regenerable (T7) · Reporter /status <2s (T13). All mapped.
