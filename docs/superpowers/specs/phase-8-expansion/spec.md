# Phase 8 — Expansion Spec (Framework)

**Status:** Approved 2026-04-26 (framework only; specific tracks each get their own spec when started)
**Type:** Phase-level spec
**Phase duration:** ongoing — each expansion track is its own scoped effort
**Anchor specs:** [`../2026-04-25-mahoraga-architecture-decomposition.md`](../2026-04-25-mahoraga-architecture-decomposition.md)
**Predecessor:** Phase 7 stable (90+ days live without infrastructure incident)

---

## 1. Goal

**Add capabilities** in independent expansion tracks. Each track is its own SDD spec → `plan.md` → `tasks.md` → implementation cycle. Phase 8 is a *framework*, not a single implementation; this spec defines the framework rules and the tracks we anticipate.

## 2. Anticipated Expansion Tracks

Each is its own future SDD spec; tracks can run in parallel only when they don't share state.

| Track | Why we add it | Major dependencies | Likely order |
|---|---|---|---|
| **8a — Options on equity & BTC ETFs** | Defined-risk strategies; tail-risk hedging; covered calls for income; leverage without margin | Options data feed, options-aware position sizing, options compliance, expanded LiteLLM routing for options analysis | First — lowest infrastructure delta |
| **8b — Short selling** | Symmetric exposure; mean-reversion strategies needing both sides; hedging | Margin account, locate-availability checks, SSR awareness, regulatory expansion | Second |
| **8c — Spot Bitcoin** | Direct BTC exposure outside ETFs; 24/7 market opportunities | Crypto broker (Alpaca crypto / Coinbase / Kraken), 24/7-aware scheduler, custody discipline, state-by-state regs | Third — biggest infrastructure delta |
| **8d — Multi-agent distributed research** | Faster autoresearch; multiple Hunter instances exploring different regimes in parallel | KB conflict resolution, agent-orchestration extension to multi-instance | After ≥2 expansion tracks have validated the per-track SDD process |
| **8e — Capital scaling Stage 2 → Stage 3** | $15K–$50K → $50K–$200K and beyond | Risk-limit recalibration at larger size, broker capacity, operational scale | Anytime stability supports it |
| **8f — Additional asset classes** | Fixed income (bonds), forex, commodity futures — only if validated cycles repeat | New data feeds, new compliance, new regimes, new vendor integrations | Last — validate everything else first |

## 3. Framework Rules (apply to every track)

- Each track gets a dedicated SDD spec at `docs/superpowers/specs/YYYY-MM-DD-phase-8<letter>-<topic>-spec.md`.
- Each track runs through brainstorming → spec → `plan.md` → `tasks.md` → implementation, same chain as earlier phases.
- A track does **not** start until the prior phase (7 or any other Phase 8 track it depends on) is stable for ≥ 90 days.
- Risk-adjusted outperformance (Sharpe > SPY+0.3 on 24-month rolling, drawdown <20%) must be **maintained** through every expansion. If a track degrades the metric, it gets rolled back.
- Each track's spec includes a phase-specific compliance section (options, shorts, crypto each have new regulatory surface).

## 4. Exit Criteria (per-track)

Each track defines its own. The Phase 8 framework "exit" is open-ended.

## 5. Phase-Specific Risks

- **Complexity creep.** Mitigation: one track at a time unless they're genuinely independent (e.g., 8e capital scaling is independent of capability additions).
- **Regulatory expansion.** Options, shorts, spot crypto each have new compliance surface area. Mitigation: per-track compliance section is mandatory.
- **KB conflicts in multi-agent track.** Mitigation: 8d's spec defines conflict resolution mechanisms (write coordination, eventual consistency policy).
- **BTC custody (8c).** Mitigation: state-specific regulatory review; reputable broker; segregated account.

## 6. Open Questions for This Phase

- Track ordering. Default: 8a (options) → 8b (shorts) → 8c (spot BTC) → others. Operator may revise based on what's working.
- Multi-agent track is the riskiest in terms of system complexity; consider only after at least 2 expansion tracks have validated the per-track SDD process.
- Capital-scaling triggers — Plan §27 specifies but reality may differ; revisit Stage thresholds in 8e.
