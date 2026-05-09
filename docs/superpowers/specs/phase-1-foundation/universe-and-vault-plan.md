# Phase 1 — Universe + Vault Embargo Implementation Plan

**Status:** Drafted 2026-05-09
**Specs:** [`universe-spec.md`](universe-spec.md), [`vault-embargo-spec.md`](vault-embargo-spec.md)
**Parent plan:** [`plan.md`](plan.md)

These two sub-features are bundled in one design PR but ship in separate
implementation PRs. They run in parallel — they touch different files
(`services/trader/universe/` vs `services/trader/data/storage/`) with no
shared code edits.

---

## 1. Implementation strategy

Six small chunks total — three per sub-feature. Each is sized for <60-min review.

```
P1.2 universe                          P1.3 vault embargo
────────────────────                   ──────────────────
[U1 yaml + loader]                     [V1 storage hook + canary tests]
       │                                       │
[U2 bootstrap scripts]                 [V2 audit-writer wire-up]
       │                                       │
[U3 index reproduction audit]          [V3 default flip + test sweep]
```

P1.2 chunks U1 → U2 → U3 are sequential (U2 needs U1's loader; U3 needs U1+U2 + P1.1's adapter).

P1.3 chunks V1 → V2 → V3 are sequential (V2 wires audit on top of V1; V3 changes the default once V1+V2 stabilize).

P1.2 and P1.3 are independent of each other; either can start first.

## 2. P1.2 — Universe management chunks

### Chunk U1 — YAML schema + `Universe.load()`
**Branch:** `phase-1-universe-yaml-and-loader`
**Target review time:** ~45 min

Lands:
- `services/trader/universe/__init__.py`, `models.py`, `loader.py`
- `services/trader/universe/tests/test_loader.py`
- `data/universe/{sp500,russell1000}/{seed.yaml,events.yaml}` — small bootstrap content covering 2014–2018 only (full history lands in U2)
- `data/universe/etfs.yaml` — the Phase 1 ETF allowlist (broad + sectors + commodities)

Acceptance:
- `Universe.load("data/universe").members(name="sp500", asof=date(2017, 1, 1))` returns a non-empty set
- `Universe.is_member(name="etfs", asof=date(2026, 5, 1), ticker="SPY")` returns True
- Schema validation rejects malformed YAML (out-of-order events, add-after-add, remove-before-add)
- Pure read — no HTTP

### Chunk U2 — Bootstrap scripts
**Branch:** `phase-1-universe-bootstrap-scripts`
**Target review time:** ~50 min

Lands:
- `scripts/build_sp500_universe.py` — fetches the Wikipedia "List of S&P 500 companies" current table + the "Selected changes" history; emits `seed.yaml` + `events.yaml`
- `scripts/build_russell1000_universe.py` — fetches the Wikipedia table + FTSE Russell reconstitution PRs
- Manifest written to `data/universe/manifests/universe-rebuilds.parquet` per build run
- `services/trader/universe/tests/test_loader.py` extended with a fixture exercising the full multi-year history

Acceptance:
- Re-running the build script is idempotent (no duplicate event rows)
- The output passes U1's schema validator
- One manifest row per script invocation; `audit.events` row written when `MAHORAGA_AUDIT_DSN` is set

### Chunk U3 — Index-reproduction audit test
**Branch:** `phase-1-universe-index-reproduction`
**Target review time:** ~40 min

Lands:
- `tests/integration/phase-1/universe/test_index_reproduction.py` — composes the S&P 500's PIT membership for July 2018 with OHLCV from P1.1's adapter and reproduces the monthly price return; asserts within tolerance against a published reference (e.g. ±50 bps for price-only)
- Documentation note in `services/trader/universe/README.md` describing the audit and how to extend it to other months/years

Acceptance:
- Audit test passes within tolerance in CI's integration-smoke job
- Failure mode: surfaces which constituents diverge from the reference

## 3. P1.3 — Vault embargo chunks

### Chunk V1 — Storage hook + canary tests
**Branch:** `phase-1-vault-storage-changes`
**Target review time:** ~45 min

Lands:
- `services/trader/data/storage/parquet_adapter.py` — gain `vault_cutoff_days` constructor param (**default `None` to preserve existing behaviour**) and `vault_override` kwarg on `read()`
- `services/trader/data/storage/vault.py` — `VaultEmbargoError`, helper to compute `vault_cutoff_dt`, helper to detect window overlap
- `services/trader/data/storage/tests/test_vault.py` — boundary tests: just inside, just outside, override-warn, default-disabled

Acceptance:
- Passing `vault_cutoff_days=None` (the default) preserves existing P1.1 behaviour — every existing test remains green without modification
- Passing `vault_cutoff_days=180` raises `VaultEmbargoError` for any read whose `[start, end]` overlaps `(asof - 180d, asof]`
- `vault_override=True` returns the data and logs a Python `WARNING` containing the requested window
- Boundary tests cover the `=` cases (cutoff exclusive vs inclusive)

### Chunk V2 — Audit-writer wire-up
**Branch:** `phase-1-vault-audit-integration`
**Target review time:** ~40 min

Lands:
- `ParquetAdapter` gains an optional `audit_writer: PostgresAuditWriter | None = None` constructor param
- `vault_override=True` calls write an `action='vault_override'` row to `audit.events` (best-effort; failure of the audit write logs but doesn't suppress the read)
- New required kwarg `vault_override_reason: str` (raises `ValueError` if `vault_override=True` but `reason` is missing)
- `tests/integration/phase-1/data_foundation/test_vault_audit.py` — Postgres-backed e2e test marked `pytest.mark.integration`
- README updated with override usage example

Acceptance:
- An override call yields exactly one `vault_override` row in `audit.events` with the expected payload
- Missing `vault_override_reason` raises `ValueError`
- Postgres-down case: warning logged, read still returns data

### Chunk V3 — Default flip + test sweep
**Branch:** `phase-1-vault-default-flip`
**Target review time:** ~30 min

Lands:
- `ParquetAdapter` constructor default changes from `vault_cutoff_days=None` to `vault_cutoff_days=180`
- Every existing test that reads "recent" data is updated to either:
  - Pass `vault_cutoff_days=None` if it's testing storage mechanics, not vault policy
  - Use `asof` deep in history (already in 2026 in most tests; vault doesn't fire)
- README updated to reflect the new default

Acceptance:
- All existing tests still pass under the new default
- A canary test verifies that constructing `ParquetAdapter(tmp_path)` (no kwargs) gives 180-day vault enforcement

## 4. Per-chunk PR template

Each PR follows the same shape (already established by P1.1):

```
## Summary
1-3 bullets — what this chunk lands.

## Scope
- In-scope:
- Out-of-scope (deferred to chunk N):

## Test plan
- [ ] pytest <path>
- [ ] CI green on lint + unit-tests + integration-smoke
- [ ] Cross-check against <spec>-spec.md §<section> acceptance criterion
```

## 5. Risks during implementation

| Risk | Mitigation |
|---|---|
| Wikipedia table layouts shift mid-bootstrap | Cache a snapshot in the build script; fail-loud if structure drifts; bootstrap is operator-run, not CI-run |
| FTSE Russell PR pages change format | Manual YAML diff is the fallback; the bootstrap script can be skipped entirely if needed |
| Index-reproduction audit fails by >tolerance | Most likely cause is dividends — document this, treat price-only as adequate for Phase 1, defer total-return audit to Phase 2 |
| Vault default flip breaks an unrelated PR mid-flight | V3 lands as a separate small PR after V1 + V2 are stable; coordinate with anyone in the queue |
| Vault override audit write needs Postgres but caller has no DSN | `audit_writer=None` cleanly degrades; log warning with `audit-skipped` marker so missing audit trails are visible in production logs |

## 6. Definition of done

P1.2 done when chunks U1 + U2 + U3 are all merged and the index-reproduction test is green in CI.

P1.3 done when chunks V1 + V2 + V3 are all merged, the canary test catches an in-vault read by default, and the override audit row appears in `audit.events`.

After both: P1.4 (`feature-pipeline-spec.md`) is unblocked.
