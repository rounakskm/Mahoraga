<!--
Adapted from anthropics/financial-services @ 1c2ece3467c3434ddd01e655970e35b773940a29
Source: plugins/vertical-plugins/equity-research/skills/idea-generation/SKILL.md
License: Apache 2.0 (header preserved below)
Adapted: 2026-05-09 for Mahoraga Hunter role — kept the long/short/value/quality/special-situation
screen taxonomy verbatim, dropped the "ask the user for parameters" interactive framing (Hunter
runs autonomously with config-injected universe), retargeted "Suggested Next Steps" from human-handoff
to autoresearch-loop handoff (build_full_model → backtest mutation, deep_dive → Researcher tool call).
-->

<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: Copyright (c) 2026 Anthropic PBC. Adapted by Mahoraga maintainers.
-->

# Idea Generation (Hunter role)

Systematic stock screening and investment idea sourcing. Combines quantitative screens, thematic research, and pattern recognition to surface new long and short candidates for the autoresearch loop. Hunter calls this on each scheduled scan; outputs feed the Researcher's deep-dive queue and the autoresearch mutation candidates.

## Workflow

### Step 1: Read search criteria from config

Hunter receives parameters from the upstream caller, not interactively:
- **Direction**: `long`, `short`, or `both`
- **Universe**: ticker list or filter (US large-cap, US small-cap, ETF universe, BTC ETF set)
- **Style**: `value`, `growth`, `quality`, `special_situation`, `event_driven`
- **Theme** *(optional)*: thematic angle to overlay on the style screen

### Step 2: Run quantitative screens

#### Value
- P/E below sector median
- EV/EBITDA below historical average
- Free-cash-flow yield > 5%
- Price/book < 1.5x
- Insider buying in last 90 days
- Dividend yield above market average

#### Growth
- Revenue growth > 15% YoY
- Earnings growth > 20% YoY
- Revenue acceleration (growth rate increasing)
- Expanding margins
- Return on invested capital > 15%
- Net retention > 110% (SaaS only)

#### Quality
- Consistent revenue growth (5+ years)
- Stable or expanding margins
- ROE > 15%
- Low debt/equity
- High free-cash-flow conversion
- Insider ownership > 5%

#### Short
- Declining revenue or decelerating growth
- Margin compression
- Rising receivables / inventory vs. sales
- Insider selling
- Valuation premium to peers without justification
- High short interest with deteriorating fundamentals
- Accounting red flags (auditor changes, restatements)

#### Special situation
- Recent IPOs/SPACs with lockup expirations
- Spin-offs in last 12 months
- Companies emerging from restructuring
- Activist involvement
- Management changes at underperforming companies

### Step 3: Thematic sweep (optional)

For thematic ideas, research the theme and identify beneficiaries:
1. Define the thesis (e.g., "AI infrastructure spending accelerates through 2026")
2. Map the value chain — direct vs. indirect beneficiaries
3. Identify pure-play vs. diversified exposure
4. Assess which names are already priced in vs. under-appreciated
5. Look for second-order beneficiaries the market hasn't connected to the theme

### Step 4: Per-idea structured output

For each idea that passes the screen, produce one record:

```json
{
  "ticker": "STR",
  "direction": "long|short",
  "thesis_one_liner": "string ≤140 chars",
  "metrics": {
    "market_cap_usd": 0,
    "ev_ebitda_ntm": 0.0,
    "pe_ntm": 0.0,
    "revenue_growth_yoy": 0.0,
    "ebitda_margin": 0.0,
    "fcf_yield": 0.0
  },
  "vs_peers": { "metric": "premium|in_line|discount" },
  "thesis_pillars": ["3-5 bullets"],
  "key_risks": ["3-5 bullets — what would make this wrong"],
  "next_action": "build_full_model|deep_dive_research|expert_call|backtest|watchlist|reject"
}
```

### Step 5: Hand off to the autoresearch loop

Output a **shortlist of 5-10 candidates** ranked by next-action priority. The orchestrator routes:
- `next_action: backtest` → autoresearch mutation queue
- `next_action: deep_dive_research` → Researcher role
- `next_action: build_full_model` → blocked (Mahoraga does not do bottom-up DCF; mark as `reject` and explain)
- `next_action: watchlist` → Hindsight `mahoraga-trader` bank as a World Fact / candidate observation
- `next_action: reject` → no-op (Hindsight may still log negative signal for pattern learning)

## Important notes

- Screens surface **candidates**, not conclusions — every screen output needs the autoresearch backtest step before any capital allocation.
- The best ideas often come from intersections (quality company at value price due to temporary headwind).
- Avoid crowded trades — check ownership data, short interest, and how many analysts cover the name.
- Contrarian ideas need a catalyst — being early without a catalyst is the same as being wrong.
- Track idea hit rates over time in Hindsight — which screens and approaches produce the best ideas is itself an Observation that feeds Phase-3 strategy mutation.
- Short ideas need higher conviction — timing is harder and risk is asymmetric.
