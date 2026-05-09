# Phase 1 — Universe + Vault Embargo Tasks

**Status:** Drafted 2026-05-09
**Specs:** [`universe-spec.md`](universe-spec.md), [`vault-embargo-spec.md`](vault-embargo-spec.md)
**Plan:** [`universe-and-vault-plan.md`](universe-and-vault-plan.md)

Task IDs follow the parent [`tasks.md`](tasks.md) numbering. P1.2 = universe; P1.3 = vault embargo.

## Legend

- `[code]` = implementation
- `[test]` = pytest or fixture work
- `[doc]` = README, docstring, or measurement note
- `[infra]` = config, CI, or dependency change
- `→` = depends on

---

## P1.2 — Universe management

### P1.2.A — Chunk U1: YAML schema + loader

| ID | Type | Description | Depends on |
|---|---|---|---|
| **P1.2.A.1** | [code] | Create `services/trader/universe/__init__.py`, `models.py` (`UniverseEvent`, `UniverseEntry`), `loader.py` (`Universe`, `Universe.load`, `Universe.members`, `Universe.is_member`, `Universe.history`, `Universe.etf_allowlist`) | — |
| **P1.2.A.2** | [code] | YAML schema validators (events sorted by date, no add-after-add, no remove-before-add) | P1.2.A.1 |
| **P1.2.A.3** | [doc]  | Hand-authored `data/universe/sp500/seed.yaml` + `events.yaml` covering 2014-01-01 → 2018-12-31 (~30 events) | — |
| **P1.2.A.4** | [doc]  | Hand-authored `data/universe/russell1000/seed.yaml` + `events.yaml` covering same window | — |
| **P1.2.A.5** | [doc]  | `data/universe/etfs.yaml` — Phase 1 ETF allowlist (broad + sectors + commodities) with listed_at dates | — |
| **P1.2.A.6** | [test] | `services/trader/universe/tests/test_loader.py` — happy paths, schema-violation rejection, member set computation | P1.2.A.1, P1.2.A.3 |
| **P1.2.A.7** | [doc]  | `services/trader/universe/README.md` with usage example | P1.2.A.1 |

PR: `phase-1-universe-yaml-and-loader`.

### P1.2.B — Chunk U2: Bootstrap scripts

| ID | Type | Description | Depends on |
|---|---|---|---|
| **P1.2.B.1** | [code] | `scripts/build_sp500_universe.py` — Wikipedia fetch + parse + emit `seed.yaml` + `events.yaml` for full history (≥10 years) | P1.2.A done |
| **P1.2.B.2** | [code] | `scripts/build_russell1000_universe.py` — Wikipedia + FTSE Russell PR scraping | P1.2.A done |
| **P1.2.B.3** | [code] | Manifest writer (one row per script run to `data/universe/manifests/universe-rebuilds.parquet`); audit-events write when `MAHORAGA_AUDIT_DSN` set | P1.2.B.1 |
| **P1.2.B.4** | [test] | `services/trader/universe/tests/test_bootstrap.py` — mocked-HTTP test that the parser handles the Wikipedia table shape; idempotent re-run | P1.2.B.1 |
| **P1.2.B.5** | [doc]  | README section for the bootstrap scripts (operator runbook) | P1.2.B.1 |

PR: `phase-1-universe-bootstrap-scripts`.

### P1.2.C — Chunk U3: Index reproduction audit

| ID | Type | Description | Depends on |
|---|---|---|---|
| **P1.2.C.1** | [test] | `tests/integration/phase-1/universe/test_index_reproduction.py` — for July 2018: read `members(name="sp500", asof=2018-07-31)`, pull OHLCV from P1.1's adapter for those tickers, compute equal-weighted price return, compare to a published reference within ±50 bps tolerance | P1.2.B done + P1.1 merged |
| **P1.2.C.2** | [doc]  | Audit doc explaining the methodology + how to extend to other months/years; the operator-readable why-this-matters note | P1.2.C.1 |
| **P1.2.C.3** | [infra] | Extend CI integration-smoke job to run the new test | P1.2.C.1 |

PR: `phase-1-universe-index-reproduction`.

---

## P1.3 — Vault embargo

### P1.3.A — Chunk V1: Storage hook + canary tests

| ID | Type | Description | Depends on |
|---|---|---|---|
| **P1.3.A.1** | [code] | `services/trader/data/storage/vault.py` — `VaultEmbargoError`, `compute_vault_cutoff(asof, days)`, `window_overlaps_vault(start, end, vault_cutoff)` | — |
| **P1.3.A.2** | [code] | Modify `services/trader/data/storage/parquet_adapter.py` — accept `vault_cutoff_days` constructor param (**default `None`** to preserve P1.1 behaviour) and `vault_override` kwarg on `read()` | P1.3.A.1 |
| **P1.3.A.3** | [code] | When override is active, log Python `WARNING` with structured fields | P1.3.A.2 |
| **P1.3.A.4** | [test] | `services/trader/data/storage/tests/test_vault.py` — boundary cases (just inside, just outside, day-of-cutoff), override-warns, default-disabled-preserves-behaviour | P1.3.A.2 |

PR: `phase-1-vault-storage-changes`.

### P1.3.B — Chunk V2: Audit-writer wire-up

| ID | Type | Description | Depends on |
|---|---|---|---|
| **P1.3.B.1** | [code] | `ParquetAdapter` gains optional `audit_writer: PostgresAuditWriter | None = None` constructor param | P1.3.A done |
| **P1.3.B.2** | [code] | Make `vault_override_reason: str` required when `vault_override=True`; raise `ValueError` otherwise | P1.3.A.2 |
| **P1.3.B.3** | [code] | Override-active path writes `audit.events` row with `action='vault_override'` (best-effort; failure logs but doesn't suppress the read) | P1.3.B.1 |
| **P1.3.B.4** | [test] | Unit-level: `test_vault.py` extended with mocked `audit_writer` that records the override call | P1.3.B.3 |
| **P1.3.B.5** | [test] | `tests/integration/phase-1/data_foundation/test_vault_audit.py` — Postgres-backed e2e (`pytest.mark.integration`); asserts exactly one `vault_override` row + payload shape | P1.3.B.3 |
| **P1.3.B.6** | [doc]  | README updated with override usage example + audit-row payload shape | P1.3.B.3 |

PR: `phase-1-vault-audit-integration`.

### P1.3.C — Chunk V3: Default flip + test sweep

| ID | Type | Description | Depends on |
|---|---|---|---|
| **P1.3.C.1** | [code] | Flip `ParquetAdapter` constructor default `vault_cutoff_days` from `None` to `180` | P1.3.A done + P1.3.B done |
| **P1.3.C.2** | [test] | Update existing P1.1 chunk-2 / chunk-4 tests: pass `vault_cutoff_days=None` where the test is policy-agnostic, or move `asof` deep enough into history that vault is inert | P1.3.C.1 |
| **P1.3.C.3** | [test] | Canary: `ParquetAdapter(tmp_path)` (no kwargs) produces 180-day vault enforcement; reading a recent window without override raises | P1.3.C.1 |
| **P1.3.C.4** | [doc]  | README: vault is now opt-out (was opt-in); operator runbook for when override is appropriate | P1.3.C.1 |

PR: `phase-1-vault-default-flip`.

---

## Cross-sub-feature parallelism

P1.2 and P1.3 are independent. Either can land first. P1.4 (`feature-pipeline-spec.md`) waits for both:

- P1.4 needs `Universe.members(...)` to know which tickers to compute features for (P1.2)
- P1.4 reads through `ParquetAdapter` and must respect the vault by default (P1.3)

## Task ownership note

All six chunks are foreground work — single-thread implementation. Subagent dispatch becomes appropriate later when feature-pipeline (P1.4) breaks into 70+ feature files that can be implemented in parallel.

## Next concrete deliverable

After this design PR merges:

→ **Author chunk U1 implementation on `phase-1-universe-yaml-and-loader`** OR **chunk V1 implementation on `phase-1-vault-storage-changes`** (whichever has clearer requirements after one final read of the specs). The other follows immediately after on its own branch.
