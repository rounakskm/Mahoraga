# Phase 4 — Intelligence Layer Spec

**Status:** Approved 2026-04-26
**Type:** Phase-level spec
**Phase duration:** 9 weeks
**Anchor specs:** [`../2026-04-25-mahoraga-architecture-decomposition.md`](../2026-04-25-mahoraga-architecture-decomposition.md)
**Predecessor:** Phase 3

---

## 1. Goal

Add **real-time market intelligence**: news pipeline (live + classified), sentiment state, transition predictor, web-research agent. KB Level-2/Level-3 populated by Archivist running on richer context. This phase makes Mahoraga regime-aware in real time, not just historically.

## 2. Major Sub-Features

Each will get its own SDD feature spec:

1. **News websocket pipeline** — Alpaca news websocket (primary); supplementary feeds for crypto-relevant news (BTC ETFs benefit from BTC sentiment). Reconnect logic and polling fallback.
2. **News classifier** — FinBERT or similar quantized model; CRITICAL / MATERIAL / BACKGROUND classification; <2s latency SLA per integration spec §4.6. Emits to `news-classified` channel.
3. **Sentiment state aggregator** — 15-min rolling sentiment per symbol; published to `kb-updates` channel; consumed by Hunter for context.
4. **Transition predictor** — rules-based layer (always on, deterministic) + Hunter-learned layer (emerges from KB after enough iterations); predicts regime transitions before damage accumulates (5-day detection window).
5. **Web-research agent** — Sunday 7pm cron per integration spec §5.1; outbound web egress to fixed allowlist (FRED, SEC EDGAR, Federal Reserve RSS, CME FedWatch, news syndication); produces weekly macro narratives → KB Level-2 entries.
6. **Archivist Level-2 / Level-3 promotion** — weekly Level-2 pattern extraction (across recent Level-1 entries); monthly Level-3 meta-principle synthesis (across Level-2 patterns).
7. **News shock protocol** — CRITICAL classification triggers entry-halt mode within 10s; tightened stops; alert human; 10-min hold before any forced exits.

## 3. Exit Criteria

- News classified <2s end-to-end (websocket → classifier → published)
- Sentiment aggregated every 15 min, queryable by Hunter
- Transition predictor live, producing transition probabilities
- Web-research agent producing weekly macro briefs landing in KB Level-2
- Archivist Level-2 patterns appearing in `knowledge.patterns`; Level-3 entries beginning to emerge
- News shock protocol tested end-to-end (synthetic CRITICAL event triggers entry halt)

## 4. Dependencies

- Phase 3 (Hunter / Guardian / Archivist running, KB Level-1 populated, compressed-replay complete)

## 5. Timeline & Sequencing — 9 weeks, 3 parallel streams

| Week | Stream A (News) | Stream B (Web research + transition) | Stream C (Archivist L2/L3) |
|---|---|---|---|
| 1–2 | Alpaca news websocket integration | web-research-agent sandbox + outbound allowlist | Level-2 schema + extraction algorithm design |
| 3–4 | News classifier (FinBERT/quantized) | macro source connectors (FRED, EDGAR, Fed RSS, CME FedWatch) | Level-2 weekly job |
| 5–6 | Sentiment aggregation 15-min | web-research weekly synthesis prompt | Level-3 schema + extraction |
| 7 | News shock protocol | transition predictor v1 (rules) | Level-3 monthly job |
| 8 | Shock protocol end-to-end testing | transition predictor v2 (Hunter-learned overlay) | end-to-end validation |
| 9 | exit sign-off | exit sign-off | exit sign-off |

## 6. Phase-Specific Risks

- **News classifier latency under burst.** Mitigation: quantized model; pre-warmed inference; queue-depth monitoring; SLA tested under burst load.
- **Web-research sandbox correctness.** Outbound allowlist must be tight (security) but functional. Mitigation: enumerate hosts in config; integration test verifies allowlist enforcement; log every fetch.
- **News source reliability.** Alpaca websocket can drop. Mitigation: reconnect logic + polling fallback; alert human on extended outage.
- **Sentiment model bias on BTC-ETF symbols.** General-purpose sentiment may not know IBIT vs BTC. Mitigation: alias mapping (IBIT → "Bitcoin ETF"); BTC-aware sentiment lexicon for crypto terms.
- **Transition predictor false positives early.** Hunter-learned layer needs many iterations to mature. Mitigation: rules layer always on as a safety net; transition warnings ranked by source.

## 7. Open Questions for This Phase

- Pre-2020 news archive coverage (architecture spec §9 OQ 2). Decided in `intelligence-layer-spec.md`.
- Crypto-news sources for BTC sentiment — CoinDesk RSS, The Block, others. Decided in same spec.
- News-classifier model choice (FinBERT vs newer alternative). Empirical comparison in week 3.
- Web-research synthesis frequency (weekly vs daily). Default Sunday-only; revisit if value warrants daily.
