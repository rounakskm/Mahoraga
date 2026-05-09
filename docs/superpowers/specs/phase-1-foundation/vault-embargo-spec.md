# Phase 1 — Vault Embargo Spec (sub-feature 3)

**Status:** Drafted 2026-05-09
**Parent:** [`spec.md`](spec.md), [`plan.md`](plan.md), [`tasks.md`](tasks.md)
**Predecessor:** P1.1 data-foundation (merged 2026-05-09)
**Owner stream:** A (data) — runs alongside P1.2 universe management

---

## 1. Goal

Make it **architecturally impossible** for a backtest, autoresearch mutation, or training run to read data within the vault — a rolling embargo window covering the most recent 6 months of any time series. The vault is held back from training so that the live deployment in Phase 7+ has a genuinely out-of-sample window to validate against. A silent read of vault data invalidates that validation; a noisy read with audit trail is an acceptable explicit override.

## 2. Contract (the load-bearing rule)

```
default behaviour:
  read(start, end, asof=T)            with [start, end] overlapping [T - 6mo, T]
  ───────────────────────────────────────────────────────────────────────────
                              ↓
                   raise VaultEmbargoError

opt-in override:
  read(start, end, asof=T, vault_override=True)
  ───────────────────────────────────────────────────────────────────────────
                              ↓
                   log AUDIT WARN + return data
```

This matches the original `phase-1-foundation/spec.md` exit criterion verbatim:

> Vault embargo demonstrably enforced (test: `read(vault_dates)` raises; with `vault_override=True` warns and returns)

## 3. Scope

### In scope

- A configurable vault window (default 180 days) baked into the storage adapter at construction time.
- `VaultEmbargoError` raised by `ParquetAdapter.read()` when the requested `[start, end]` overlaps the vault relative to `asof`.
- `vault_override=True` per-call escape, with a `WARNING`-level log line + an `audit.events` row tagged `action='vault_override'` so every override is forensically reconstructible.
- A canary test ("inject a row whose `bar_timestamp` is inside the vault, attempt to read it without override → assert raises") wired into CI.

### Out of scope

- Per-ticker / per-indicator overrides. The vault applies uniformly to all data the adapter manages.
- Mutating the vault window at runtime. Override is per-call only; the cutoff itself is a constructor parameter.
- "Reverse" embargo (excluding ancient data). Vault is a *recency* policy.

## 4. Implementation strategy

Vault enforcement lands inside `ParquetAdapter.read()` (chunk B of P1.1) — not as a wrapper. Reasons:

1. The adapter is already the single chokepoint for PIT correctness; adding the vault check there keeps the chokepoint count at one.
2. Strategy code that constructs its own ParquetAdapter still gets vault enforcement. There's no "naive" reader exposed at the package boundary.
3. Wrapping would mean two adapters (one with vault, one without); the bypass surface is whichever the strategy author imports. Single-adapter design eliminates the choice.

Concretely:

```python
# services/trader/data/storage/parquet_adapter.py — modified
class ParquetAdapter:
    def __init__(
        self,
        root: Path | str,
        *,
        vault_cutoff_days: int | None = 180,
    ) -> None: ...

    def read(
        self,
        *,
        kind: Kind,
        keys: Iterable[str],
        start: datetime,
        end: datetime,
        asof: datetime | None = None,
        vault_override: bool = False,
    ) -> pd.DataFrame:
        ...
```

Vault check happens on the resolved `asof` (caller's value, or `now`):

```
vault_cutoff_dt = asof - timedelta(days=vault_cutoff_days)
overlaps = (end >= vault_cutoff_dt)  # any portion of [start, end] is within the vault
```

If `overlaps and not vault_override`, raise `VaultEmbargoError(start, end, asof, vault_cutoff_dt)`.

If `overlaps and vault_override`, log a `WARNING` line via Python `logging`, **and** write an `audit.events` row via the existing `PostgresAuditWriter` (best-effort; if Postgres is down, the WARNING line is the only forensic trace). The `audit.events` row carries:

```json
{"actor": "...", "action": "vault_override", "payload": {"start": "...", "end": "...", "asof": "...", "kind": "ohlcv|macro", "keys_count": N}}
```

`vault_cutoff_days=None` disables vault enforcement entirely. Tests use `None`; production tests use the default 180.

## 5. Substrate-portability

- The adapter does not call into NemoClaw or any sandbox primitive. It optionally accepts an `audit_writer` so the override audit trail goes to whatever audit sink the application has wired up (Phase 0's hash-chained `audit.events`). A no-op default is provided for tests / scripts.

## 6. Acceptance / exit criteria

| Check | Where |
|---|---|
| **Default-block canary test**: write a row inside the vault, attempt to `read(asof=now)` without override, assert `VaultEmbargoError` | `services/trader/data/storage/tests/test_vault.py` |
| **Override-and-warn**: same setup, pass `vault_override=True`, assert log warning emitted + Postgres audit row written | `services/trader/data/storage/tests/test_vault.py` (Postgres part marked `pytest.mark.integration`) |
| **Window outside vault**: read `[2020-01-01, 2020-12-31]` with `asof=2026-05-09` succeeds (well outside the vault) | `services/trader/data/storage/tests/test_vault.py` |
| **Boundary case**: `end = asof - 6mo + 1 day` is inside the vault (overlaps); `end = asof - 6mo - 1 day` is outside | `services/trader/data/storage/tests/test_vault.py` |
| **Construct with `vault_cutoff_days=None`**: behaves like today (no vault) | Backwards-compat test |
| **Audit row**: end-to-end test asserts an override write produces exactly one `vault_override` row in `audit.events` with the expected payload | `tests/integration/phase-1/data_foundation/test_vault_audit.py` |

## 7. Migration impact (existing P1.1 tests)

The current chunk-2 / chunk-4 tests construct `ParquetAdapter(tmp_path)` without specifying a vault. With a default of 180 days, those tests would start failing if their asof is "today" and their data is inside the vault.

**Strategy:**
1. Default the constructor to `vault_cutoff_days=None` for the rollout PR. Existing tests remain green.
2. Once the vault tests pass, flip the default to `180` in a follow-up commit and update existing tests to either:
   - Pass `vault_cutoff_days=None` (when they don't care about the policy), or
   - Pass `asof` deep in history (when they want vault to be inert).

This two-step rollout keeps each commit independently reviewable.

## 8. Plan — three chunks

| # | Branch | What |
|---|---|---|
| 1 | `phase-1-vault-storage-changes` | Add `vault_cutoff_days` constructor param + `vault_override` kwarg + `VaultEmbargoError` + WARNING log path. Default cutoff = `None` (no behaviour change). Add canary tests. |
| 2 | `phase-1-vault-audit-integration` | Wire optional `audit_writer` injection so override calls write an `audit.events` row. End-to-end Postgres test. |
| 3 | `phase-1-vault-default-flip` | Flip default `vault_cutoff_days` from `None` to `180`. Update existing tests to be explicit. |

## 9. Open questions

| Question | Default if undecided |
|---|---|
| Vault duration: 6 months exactly, or rolling 180 days? | 180 days for simplicity; "6 months" colloquially means the same to operators. |
| Inclusive vs exclusive boundary | Inclusive: `bar_timestamp >= asof - 180d` is in the vault. |
| Should override require a `reason` string for the audit row? | Yes — raise `ValueError` if override is True but no `reason` is passed. Forces the operator to document why. (Defer to chunk 2; chunk 1 just logs a fixed reason.) |

## 10. What lands in the design PR (this branch)

- This spec
- Companion plan + tasks for both P1.2 and P1.3 (in `plan.md` and `tasks.md`)
- `universe-spec.md` for P1.2 (paired in the same PR for review efficiency)

Code lands in subsequent per-chunk PRs.
