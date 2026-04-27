# Phase 6 — Governance + Live Prep Spec

**Status:** Approved 2026-04-26
**Type:** Phase-level spec
**Phase duration:** 5 weeks
**Anchor specs:** [`2026-04-25-mahoraga-architecture-decomposition.md`](2026-04-25-mahoraga-architecture-decomposition.md)
**Predecessor:** Phase 5

---

## 1. Goal

**Operator-facing surfaces and safety hardening** before any real capital. Kill switch UX, Telegram bot, Streamlit dashboard, audit-log discipline, convergence report, performance attribution. By Phase 6 exit, a human can supervise, audit, and halt the system with confidence.

## 2. Major Sub-Features

Each will get its own SDD feature spec:

1. **Kill-switch UX** — surfaces the §5.6 halt contract through a prominent dashboard button + Telegram `/halt` command; both publish to the `halt` channel; tested end-to-end <10s.
2. **Telegram bot** — commands: `/halt`, `/resume`, `/status` (positions + PnL), `/regime` (current regime + transition probability), `/strategy <id>` (per-strategy detail), `/kb` (recent KB highlights). Daily and weekly report formats.
3. **Streamlit dashboard** — local web UI: regime state, current positions, recent orders, agent activity, KB recent entries, performance attribution, halt button.
4. **Audit-log discipline** — hash-chained `audit.events` rows; chain verified during weekly Archivist runs; tampering detected and surfaced.
5. **Security hardening** — secrets in OS keyring (Apple Keychain locally) or vault for cloud; no plaintext keys reachable from agent sandboxes; per-chat-ID Telegram allowlist.
6. **Convergence report** — final Phase 6 deliverable: vault holdout validation, regime coverage, KB depth, Archivist Level-3 entry sample. Output is a documented yes/no readiness for live capital with rationale and threshold.
7. **Performance attribution module** (Plan §25) — regime / strategy / sector / holding-period / signal-source attribution; surfaced in dashboard.

## 3. Exit Criteria

- Kill switch tested end-to-end <10s halt time
- Telegram bot operational with all listed commands; per-chat-ID allowlist enforced
- Streamlit dashboard live with all listed views
- Audit log hash-chain validation passes
- Secrets management hardened: no plaintext secrets reachable from agent sandboxes (verified by sandbox-audit test)
- Convergence report passes; threshold and rationale documented in `convergence-report-spec.md`
- Performance attribution module operational

## 4. Dependencies

- Phase 5 (paper trading proven; orders flowing through hard limits + compliance)

## 5. Timeline & Sequencing — 5 weeks, 3 parallel streams

| Week | Stream A (UX surfaces) | Stream B (Bot + commands) | Stream C (Hardening + reports) |
|---|---|---|---|
| 1 | Kill switch UX (dashboard + Telegram) | Telegram bot commands skeleton | audit-log hash-chain |
| 2 | Streamlit dashboard skeleton | bot integration tests; allowlist | secrets hardening |
| 3 | Dashboard views (regime, positions, KB) | dashboard integration | convergence-report framework |
| 4 | Performance attribution | dashboard polish | convergence-report pass |
| 5 | exit sign-off | exit sign-off | exit sign-off |

## 6. Phase-Specific Risks

- **Telegram API quirks.** Mitigation: integration tests against real bot; documented rate limits; allowlist enforcement tested.
- **Convergence-report threshold setting.** This is the single number that gates Phase 7 — what's "good enough"? Mitigation: define threshold in this phase with documented rationale; review with operator before Phase 7 cutover.
- **Dashboard usability.** Built for the operator (you), not for "any user". Mitigation: iterate during the 30-day paper window from Phase 5.
- **Audit-log chain integrity under crash.** Hash-chain must survive ungraceful shutdown. Mitigation: WAL-style commit pattern; Phase 6 includes crash-recovery test.

## 7. Open Questions for This Phase

- Convergence-report acceptance threshold (architecture spec §9 OQ 10). Resolved here with documented rationale.
- Telegram bot security model — per-chat-ID allowlist plus 2FA on operator account.
- Dashboard hosting — local-only (Phase 6) vs cloud (Phase 7+) — local until cloud deploy spec lands.
