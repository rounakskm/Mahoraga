# Tier 3 — Task Dependency Graph

Tasks in [`plan.md`](plan.md). One PR per wave; CI green before merge.

```
T1 watchlist + multi-signal   ── (none)
T3 researcher pipeline        ── (none)
T4 live news refresh          ── (none)
T5 fedwatch endpoint          ── (none)

T2 multi-symbol run_paper     ── needs T1
T6 cadence wrapper + docs     ── needs T2, T4
```

| Wave | Tasks (parallel) | Unblocks |
|---|---|---|
| **1** | T1, T3, T4, T5 | everything |
| **2** | T2 (T1) | T6 |
| **3** | T6 (T2, T4) | complete |

Wave 1 = 4 independent tasks (disjoint modules: execution/, intel/, news/+run_intel, data/connectors).

## Notes
- Graceful-offline mandatory; unit tests never touch the network.
- Multi-symbol reuses the already-multi-intent `Executor.run_cycle` + portfolio-wide firewall — no safety path changes.
- After each merge: tick plan.md, update `docs/PROGRESS.md`.
- FinBERT + held-open websocket + per-symbol retraining are deliberately deferred (see plan self-review) — keep them out of scope.
