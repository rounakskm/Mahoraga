<!--
Adapted from anthropics/financial-services @ 1c2ece3467c3434ddd01e655970e35b773940a29
Source: plugins/vertical-plugins/equity-research/skills/sector-overview/SKILL.md
License: Apache 2.0 (header preserved below)
Adapted: 2026-05-09 for Mahoraga Researcher role — kept the market-overview / competitive-landscape /
valuation-context structure, dropped the Word/PowerPoint output framing (we emit structured markdown
+ JSON for downstream consumers), retargeted "investment implications" to "regime-context narration"
that feeds Hunter's universe-filter and the regime-detector.
-->

<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: Copyright (c) 2026 Anthropic PBC. Adapted by Mahoraga maintainers.
-->

# Sector Overview (Researcher role)

Produce industry/sector landscape briefs covering market dynamics, competitive positioning, key players, and thematic trends. Used by the Researcher role to (a) provide regime-context for Hunter's screening, (b) seed thematic mutations for the autoresearch loop, and (c) document sector state in Hindsight as World Facts.

## Workflow

### Step 1: Define scope (from caller config)

- **Sector / subsector** (GICS / FactSet RBICS / custom Mahoraga taxonomy)
- **Universe boundary** (US-listed, ETF-only, BTC-ETF set)
- **Angle** — neutral landscape vs. thematic thesis (e.g., "AI infrastructure buildout 2026")
- **Depth** — `brief` (~5 facts) vs. `full` (10–20 facts)

### Step 2: Market overview

**Market size & growth**
- TAM with citation
- Historical 5Y CAGR
- Forward growth rate + key assumptions
- Segmentation (product, geography, end market)

**Industry structure**
- Fragmented vs. consolidated — top-5 share
- Value chain map — where does value accrue?
- Business-model types (subscription, transaction, licensing, services)
- Barriers to entry (capital, regulatory, technical, network effects)

**Trends & drivers**
- Secular tailwinds (3–5)
- Headwinds and risks
- Technology disruption vectors
- Regulatory developments
- M&A and consolidation activity

### Step 3: Competitive landscape

For the top 5–10 players, produce a row in the comps table:

| ticker | revenue_ltm | growth_yoy | ebitda_margin | market_share | differentiator |
|---|---|---|---|---|---|

Plus brief profiles: business description, strategic positioning/moat, recent material developments, valuation snapshot (P/E, EV/EBITDA, EV/Revenue).

**Competitive dynamics**
- Basis of competition (price, product, service, distribution)
- Who is gaining/losing share and why
- Disruption risk from new entrants or adjacent players

### Step 4: Valuation context

- Sector trading multiples vs. historical range
- Premium/discount drivers
- Recent M&A transaction multiples
- Sector vs. broader market

### Step 5: Mahoraga-relevant synthesis

Replace the upstream "investment implications" section with:
- **Regime narration** — one paragraph on where this sector sits relative to the current MACRO/MESO/MICRO regime classification (input from regime-detector).
- **Hunter-screen overlay hints** — which screen styles best fit this sector right now (value vs. growth vs. quality vs. special-situation), with one-line reasoning.
- **Autoresearch mutation seeds** — 2–3 thematic angles that could be encoded as backtestable strategy mutations.
- **Bull / bear debate** — the strongest argument on each side; Hindsight logs both as Mental Model entries to prevent thesis drift.

### Step 6: Output

Emit:
1. A markdown brief (200–600 words) for the operator-facing morning report.
2. A `sector-reader.schema.json`-validated JSON block (claim + source list) for Hindsight ingestion.

## Important notes

- Source every market-size number — cite the research firm, methodology, or filing.
- Distinguish TAM hype from realistic addressable market.
- Sector overviews age fast — every Hindsight write includes the as-of timestamp and a flag for staleness.
- Tailor the synthesis to current regime — a sector primer in a contracting MACRO regime carries different implications than the same primer in expansion.
- If the brief exceeds 800 words it's noise — edit ruthlessly to the load-bearing facts.
