# Phase 6 — Governance + Live Prep — Task Dependency Graph

Tasks defined in [`plan.md`](plan.md). One PR per wave; CI green before merge.

## Dependency edges

```
T1  AuditLog            ── (none)
T2  attribution         ── (none)
T3  telegram commands   ── (none; providers injectable)
T4  secrets audit       ── (none)

T5  DashboardData       ── needs T2 (attribution panel)
T7  convergence report  ── needs T2 (paper-sharpe/attribution inputs)

T6  Streamlit dashboard ── needs T5
```

## Parallel batches

| Wave | Tasks (parallel) | Unblocks |
|---|---|---|
| **1** | T1, T2, T3, T4 | T5, T7 |
| **2** | T5, T7 | T6 |
| **3** | T6 | Phase-6 exit |

## Notes for implementers

- **Review lesson (gates-real-inputs-fake) is binding:** DB-reading code is tested with production-shaped rows AND a DDL cross-check; graceful-offline paths log one warning; convergence criteria fail closed when unmeasured.
- Reuse, don't rebuild: `HaltControl`, `TelegramOps`, `Reporter`, `TradeStore`, `hindsight_client`, `attribution` feed the dashboard — bind to real signatures.
- Streamlit is an `ops` optional dependency; nothing under `services/` may import it (thin shell in `scripts/dashboard.py` only).
- After each merge: tick plan.md boxes, update `docs/PROGRESS.md` Phase-6 row.
- Exit sign-off: kill-switch <10s test, all Telegram commands, dashboard live, chain verification, secrets audit, convergence report rendering (its PASS verdict waits on the 30-day paper window by design).
