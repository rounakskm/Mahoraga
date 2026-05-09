<!--
Adapted from anthropics/financial-services @ 1c2ece3467c3434ddd01e655970e35b773940a29
Source: plugins/vertical-plugins/equity-research/skills/earnings-preview/SKILL.md
License: Apache 2.0 (preserved below)
Adapted: 2026-05-09 for Mahoraga Researcher role — kept the bull/base/bear scenario framework
and the catalyst-checklist, dropped "consensus from FactSet/Bloomberg" wording (we use whatever
data sources Phase 1 ships — yfinance/finnhub default), and retargeted "trading setup" from
analyst commentary to a structured event-window record that feeds the hard-limit firewall's
"no entry within ±30 min of FOMC/CPI/NFP/earnings" rule.
-->

<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: Copyright (c) 2026 Anthropic PBC. Adapted by Mahoraga maintainers.
-->

# Earnings Preview (Researcher role)

Build pre-earnings analysis with estimate models, scenario frameworks, and key metrics to watch. Runs ahead of any covered name reporting. Output drives (a) Hunter's pre-event positioning, (b) the hard-limit firewall's event-window block, and (c) the post-event variance-vs-thesis check.

## Workflow

### Step 1: Gather context

- Company and reporting quarter
- Earnings date + time (pre-market vs. after-hours) — recorded with timezone for the firewall window
- Consensus estimates (revenue, EPS, key segment metrics) — cite source + as-of date
- Prior quarter's call: any guidance or commentary still relevant?
- Implied move from at-the-money straddle (if options data available)

### Step 2: Key metrics framework

Tailor by sector:

**Financial metrics (always)**
- Revenue vs. consensus (total + by segment)
- EPS vs. consensus
- Margins (gross, operating, net) — direction
- Free cash flow
- Forward guidance vs. consensus

**Operational metrics (sector-specific)**
- Tech / SaaS: ARR, net retention, RPO, customer count
- Retail: same-store sales, traffic, basket size
- Industrials: backlog, book-to-bill, price vs. volume
- Financials: NIM, credit quality, loan growth, fee income
- Healthcare: scripts, patient volumes, pipeline updates

### Step 3: Scenario analysis

Three scenarios with stock-price implications:

| scenario | revenue | eps | key_driver | stock_reaction_estimate |
|---|---|---|---|---|
| bull | | | | |
| base | | | | |
| bear | | | | |

For each, capture:
- What would need to happen operationally
- What management commentary would signal it
- Historical context — how the stock has moved on similar prints

### Step 4: Catalyst checklist

3–5 things that will determine the stock's reaction, ranked by importance:
1. `[metric]` vs. `[consensus|whisper]` — why it matters
2. `[guidance item]` — what the buy-side expects
3. `[narrative shift]` — strategic, M&A, restructuring

### Step 5: Output (structured record)

```json
{
  "ticker": "STR",
  "fiscal_period": "Q3_2026",
  "earnings_at": "2026-MM-DD HH:MM TZ",
  "release_window": "pre_market|after_hours|during_session",
  "consensus": { "revenue": 0, "eps": 0, "as_of": "2026-MM-DD", "source": "string" },
  "implied_move_pct": 0.0,
  "key_metrics": ["array of metric names ranked by importance"],
  "scenarios": [
    {"label": "bull", "revenue": 0, "eps": 0, "stock_reaction_pct": 0.0},
    {"label": "base", "revenue": 0, "eps": 0, "stock_reaction_pct": 0.0},
    {"label": "bear", "revenue": 0, "eps": 0, "stock_reaction_pct": 0.0}
  ],
  "catalyst_checklist": ["3-5 ordered items"],
  "firewall_blackout": {
    "start_at": "2026-MM-DD HH:MM TZ",
    "end_at":   "2026-MM-DD HH:MM TZ",
    "reason":   "earnings_release"
  }
}
```

The `firewall_blackout` block is mandatory — the execution-tool boundary reads it to refuse new entries within ±30 min of the event.

## Important notes

- Consensus changes — always note source + date; stale consensus invalidates the scenario table.
- Whisper numbers from buy-side surveys are often more relevant than published consensus; capture both when available.
- Historical earnings-reaction patterns help calibrate scenarios — search Hindsight for prior quarters' realized vs. predicted moves.
- Implied-move tells you what the market expects; if your bull/bear scenarios fall inside the implied move, the trade is uninteresting.
- Output is always JSON-validated against `services/trader/contracts/researcher.schema.json` (or a future `earnings-preview.schema.json`) before being passed downstream.
