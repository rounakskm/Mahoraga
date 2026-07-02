# Phase 5 — Broker + Paper Trading Spec

**Status:** Approved 2026-04-26; **code complete 2026-07-01** (PRs #74–#79; [plan.md](plan.md) / [tasks.md](tasks.md)). Built firewall-first: domain model + trades.* schema + AlpacaBrokerClient (dry-run default) + hard-limit firewall + sizing + compliance (PDT/wash-sale) + ATR stops + econ-calendar gate + reconciliation + executor + TradeStore + run_paper runner. The architectural firewall invariant (a rejected/halted order NEVER reaches the broker) is asserted by the executor + integration tests. Read-only proven on the live Alpaca paper account. **Live paper-order submission is a user-gated switch (`run_paper.py cycle --live-orders`, default OFF).** Remaining exit items are operational, not code: the 30-day unattended paper window + Sharpe>1.0 readiness gate (run under Phase-6 monitoring). See [`../../PROGRESS.md`](../../PROGRESS.md) Phase-5 section.
**Type:** Phase-level spec
**Phase duration:** 8 weeks
**Anchor specs:** [`../2026-04-25-mahoraga-architecture-decomposition.md`](../2026-04-25-mahoraga-architecture-decomposition.md)
**Predecessor:** Phase 4

> **⚠️ Memory-layer revision (2026-05-03):** Trade decision *contexts* (reasoning, regime, signals, expected outcome) are retained as Experience Facts in Hindsight per [`../2026-05-03-hindsight-memory-layer-revision.md`](../2026-05-03-hindsight-memory-layer-revision.md). The trade itself (transactional state — order, fill, position, pnl) **stays in Postgres `trades.*`** because regulatory + reconciliation needs ACID + exact tabular queries. The hash-chained `audit.events` log also stays in Postgres. The split is intentional: knowledge ↔ Hindsight; system-of-record ↔ Postgres.

---

## 1. Goal

First end-to-end **orders flow through the architecture** under hard-limit and compliance enforcement. Paper trading on live data for 30 consecutive days against the Alpaca paper API, validating the system trades responsibly before any real capital is staged.

## 2. Major Sub-Features

Each will get its own SDD feature spec:

1. **Alpaca paper integration** — submit / cancel / query orders via Alpaca paper API; rate-limit handling; order-status reconciliation.
2. **Position sizing module** — turns Strategy `position_size()` output into actual share counts respecting hard limits; price-aware (avoid sub-share-cost orders); fractional-share support where Alpaca allows.
3. **Compliance predicates at execution boundary** (Plan §23, FR-4.4):
   - **PDT** pattern-day-trader rule (no >3 day-trades in 5 business days unless account >$25K)
   - **Wash-sale** detection (30-day window, cross-instrument; BTC ETFs treated as substantially-identical to each other for safety)
   - **SSR** short-sale-restriction flag (relevant when shorts arrive in Phase 8b)
4. **Hard-limit enforcement at execution boundary** — implements arch spec §5.5: max-position 5%, max-sector 20%, daily loss halt 2%, 10% monthly catastrophic, no-entry near FOMC/CPI/NFP releases (±30 min), no-entry if regime confidence <40%, ATR-based stops (max 2× ATR from entry).
5. **Reconciliation job** — every 30 min: compare local position state to broker; auto-resync benign mismatches; halt on material discrepancies (>1% notional difference, or any phantom position).
6. **30-day paper-trading window** — system runs unattended; daily Telegram reports; weekly Archivist syntheses; Sharpe and drawdown metrics tracked.

## 3. Exit Criteria

- Alpaca paper API live: submit, cancel, query orders successfully
- An order rejected by hard limit or compliance is correctly logged with reason and **never reaches the broker** (architectural firewall test)
- Reconciliation job catches injected position discrepancies within one cycle
- 30 consecutive days of paper trading on live data with no infrastructure incidents
- Sharpe > 1.0 on the paper-only window (Phase 5 readiness gate, not a final metric — paper conditions can be optimistic)

## 4. Dependencies

- Phase 4 (live news + sentiment + regime active in real time)

## 5. Timeline & Sequencing — 8 weeks

| Weeks | Workstream |
|---|---|
| 1 | Alpaca paper SDK integration; order primitives; rate-limit handling |
| 2 | Position sizing + hard-limit predicates |
| 3 | Compliance predicates (PDT, wash-sale, SSR) |
| 4 | Reconciliation job; firewall integration test |
| 5–8 | 30-day paper-trading window (4 weeks unattended; daily monitoring; weekly Archivist; pre-go-live audit) |

## 6. Phase-Specific Risks

- **Alpaca rate limits and API quirks.** Mitigation: integration tests against paper API; documented retry/backoff; respect 200 req/min default.
- **Reconciliation under disconnects.** Mitigation: exponential reconnect; halt if discrepancy unresolved within 5 min.
- **Paper-vs-live divergence.** Paper Alpaca fills at midpoint; live has slippage. Mitigation: this phase doesn't claim live readiness; Phase 7 reads live realistic.
- **Wash-sale across BTC ETFs.** IBIT and FBTC are arguably substantially-identical for tax purposes. Mitigation: conservative interpretation — treat all BTC ETFs as one position for wash-sale; tax counsel consultation before live (Phase 7 prep).
- **Insufficient trade volume in 30-day window.** May not generate enough trades for statistical significance. Mitigation: extend window if needed (gates Phase 6, not a deadline).

## 7. Open Questions for This Phase

- BTC-ETF substantially-identical wash-sale interpretation — tax-counsel review before Phase 7.
- Paper-trading sample size adequacy — empirical; extend window if needed.
- Position sizing for BTC ETFs (different vol than equities) — calibrated in `paper-trading-spec.md`.
