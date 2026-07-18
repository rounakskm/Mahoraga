# Training Loop v2 — Task Dependency Graph

Tasks in [`plan.md`](plan.md). One PR per wave; CI green before merge.

```
A  volume-profile features      ── (none)
B  regime detector v2 + A/B    ── (none — uses EXISTING registry features by design)
C  chart verification panel    ── (none for candles/SMA/regimes/markers; volume-profile overlay needs A)
D  LLM priority chain          ── (none)

B2 detector A/B evidence run   ── needs B (runner comparison, v1 vs v2, report table)
C2 volume-profile overlay      ── needs A, C
E  (stretch) TV webhook→halt   ── needs nothing; only if operator wants it
```

| Wave | Tasks (parallel) |
|---|---|
| **1** | A, B, C, D |
| **2** | B2 (the evidence gate), C2 |

## Notes
- **B is the thesis core**: 4-quadrant labels are backbone-frozen; v2 refines labeling + adds real confidence. v2 becomes a default ONLY after B2 shows vault-holdout ≥ v1. Until then `--learn-detector` (v1) stays the production path.
- **C uses TradingView Lightweight Charts (OSS)** vendored locally — no TV API/ToS dependency; operator's TV Premium is the manual cross-check.
- **D preserves the mechanical backstop** and env overrides; `claude setup-token` is an optional interactive operator step documented in .env.example — ANTHROPIC_API_KEY (already set) is the supported priority-1 path.
- PIT tamper tests mandatory on every new feature (A) and detector series (B).
- After each merge: tick plan.md, update `docs/PROGRESS.md`.
