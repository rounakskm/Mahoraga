# Phase 7 — Live Trading Stage 1 Spec

**Status:** Approved 2026-04-26
**Type:** Phase-level spec
**Phase duration:** 10 weeks
**Anchor specs:** [`../2026-04-25-mahoraga-architecture-decomposition.md`](../2026-04-25-mahoraga-architecture-decomposition.md)
**Predecessor:** Phase 6 (convergence report passed)

> **⚠️ Memory-layer revision (2026-05-03):** Live trade decision contexts retained as Experience Facts in Hindsight per [`../2026-05-03-hindsight-memory-layer-revision.md`](../2026-05-03-hindsight-memory-layer-revision.md). Operator queries via Telegram (`/why-did-we-trade-X`, `/regime`, `/strategy <id>`) flow through Hindsight `recall()` and `reflect()`. Convergence-report (Phase 6 deliverable feeding into Phase 7 readiness) leverages Hindsight `reflect()` over months of training history.

---

## 1. Goal

Deploy **real capital** at Stage 1 size ($5K–$15K per Plan §27). Monitor closely. Iterate on what we learn. Phase 7 is where the learning loop meets reality; expect surprises, and have safety nets.

## 2. Major Sub-Features

Each will get its own SDD feature spec:

1. **PROD environment activation** — cloud deployment per `cloud-deployment-spec.md` (written before Phase 7 cutover); `MAHORAGA_ENV=prod`; live Alpaca API keys via cloud secrets.
2. **Live broker integration** — Alpaca live (not paper); same architecture as Phase 5 paper but with live keys, tighter monitoring, and live-realistic slippage assumptions.
3. **Capital allocation rules** — per Plan §27: Stage 1 $5K–$15K initial; promotion to Stage 2 ($15K–$50K) requires Sharpe > 1.0 AND 6–12 months track record; further stages similar.
4. **Live monitoring + escalation** — Telegram bot reports every meaningful event; daily summary at market close; weekly summary Sunday evening; Archivist Level-3 entries surfaced to operator weekly.
5. **Tax-aware position management** — wash-sale tracking across actual cross-account holdings; year-end loss harvesting awareness (can defer detail to Phase 8 if scope creeps; foundation here).
6. **Cost monitoring** — cloud cost dashboard; LLM cost dashboard; alert on monthly budget thresholds.

## 3. Exit Criteria

- 90 consecutive days without infrastructure incident
- Positive returns OR controlled-loss learning loop (loss limited to learning value; documented per loss > 1%)
- Weekly Archivist syntheses producing meaningful Level-3 entries
- Capital scaling decision (Stage 1 → 2) made with documented rationale (whether to advance, stay, or pause)

## 4. Dependencies

- Phase 6 (governance, dashboard, kill switch, convergence report passed)
- `cloud-deployment-spec.md` written and reviewed
- Tax counsel consultation completed (BTC-ETF wash-sale interpretation; account structure)

## 5. Timeline & Sequencing — 10 weeks

| Weeks | Workstream |
|---|---|
| 1 | Cloud deployment cutover; PROD environment up; smoke tests on cloud stack; secrets in cloud vault |
| 2 | Live keys provisioned; first orders at minimum Stage 1 size with operator monitoring |
| 3–10 | Live trading observation; weekly reviews; iteration on issues found in production; Stage 1 → 2 decision in week 10 |

## 6. Phase-Specific Risks

- **Real money at risk.** First phase where mistakes cost money. Mitigation: hard-limit firewall, kill switch, controlled capital ramp, weekly review cadence, conservative initial Stage 1 size.
- **Cloud cost unknowns.** Mitigation: budget alerts on cloud provider; cost-attribution dashboard from Phase 6.
- **Live LLM cost.** Bootstrap was free local; live trading may need more cloud LLM. Mitigation: track cost/decision in audit log; cap monthly LLM spend with alert.
- **Tax events.** Wash-sale across BTC ETFs and equities is real. Mitigation: end-of-year wash-sale audit; tax counsel pre-Phase-7; tax-loss harvesting awareness.
- **Live regime not in training.** Convergence report gates this, but reality outpaces backtests. Mitigation: halt if regime confidence persistently <40% for >5 days; manual review.
- **Operator availability.** Phase 7 expects close monitoring. Mitigation: Telegram-based operator presence; explicit availability schedule for first 4 weeks.

## 7. Open Questions for This Phase

- Cloud provider final selection (Hostinger / CloudFront / DigitalOcean / Hetzner) — decided in `cloud-deployment-spec.md`.
- Specific Stage-1 size within $5K–$15K range — operator's call before cutover; likely start at $5K.
- Operator availability and escalation policy — documented before week 1 cutover.
- Tax-counsel-confirmed wash-sale interpretation — must complete before live trading begins.
