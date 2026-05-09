<!--
Adapted from anthropics/financial-services @ 1c2ece3467c3434ddd01e655970e35b773940a29
Source: plugins/partner-built/lseg/skills/macro-rates-monitor/SKILL.md
License: Apache 2.0 (preserved below)
Adapted: 2026-05-09 for Mahoraga Researcher role — kept the macro-narrative scaffolding
(cycle position / curve shape / real rates / financial conditions / overall assessment),
stripped every `qa_macroeconomic`, `interest_rate_curve`, `inflation_curve`, `ir_swap`,
`tscc_historical_pricing_summaries` LSEG-MCP tool reference. Mahoraga's data sources for
this skill are FRED (free), TreasuryDirect (free), and BLS (free) — these get wired in
during Phase 1 data ingestion. Output feeds the regime-detector's MACRO classification.
-->

<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: Copyright (c) 2026 Anthropic PBC. Adapted by Mahoraga maintainers.
-->

# Macro & Rates Monitor (Researcher role)

Synthesize macroeconomic data, yield curves, inflation breakevens, and swap rates into a coherent macro narrative. Output drives the **regime-detector's MACRO classification** and feeds `prompts/reporter/morning-note.md`.

## Core principles

Macro analysis synthesizes multiple indicators into a narrative. Always assess:
1. **Where are we in the economic cycle?** — GDP, employment, PMI
2. **What is the central bank doing?** — policy rate, balance sheet, forward guidance, curve shape
3. **What does the bond market signal?** — curve slope, real rates
4. **Are financial conditions tightening or easing?** — swap spreads, real rates, credit spreads

Start broad, drill down. The output is a regime classification — not an opinion piece.

## Data sources (Phase 1 ingestion)

Free, public sources only — no paid vendor MCPs in Mahoraga:
- **FRED** (Federal Reserve Economic Data) — GDP, CPI, PCE, unemployment, payrolls, industrial production, retail sales, ISM/PMI
- **TreasuryDirect / FRED Treasury Yield curves** — 1M, 3M, 6M, 1Y, 2Y, 5Y, 10Y, 30Y constant-maturity yields
- **FRED TIPS yields + breakevens** — 5Y, 10Y, 30Y inflation-protected vs. nominal
- **FRED swap rates** — when available; OIS spreads as proxy for funding stress
- **BLS** — direct CPI components and labor data

The wiring of these sources is Phase-1 work; this prompt is the analytical scaffolding the Researcher runs once the data is available.

## Workflow

### Step 1: Pull macro indicators

For US (extend to EZ/UK as Mahoraga universe expands):
- GDP YoY (quarterly)
- Core CPI YoY (monthly), Core PCE YoY (monthly)
- Unemployment rate, NFP MoM, JOLTS (monthly)
- ISM Manufacturing PMI, ISM Services PMI (monthly)
- Retail sales MoM, industrial production MoM (monthly)

Latest value + 3M prior + 12M prior, all seasonally adjusted where available.

### Step 2: Yield curve snapshot

- Yields at 3M, 2Y, 5Y, 10Y, 30Y
- 2s10s slope (10Y − 2Y)
- 3M-10Y slope (10Y − 3M)
- Curve shape classification: `normal` / `flat` / `inverted` / `humped`

### Step 3: Inflation decomposition

| Tenor | Nominal | Breakeven | Real Rate | Signal |
|---|---|---|---|---|
| 5Y | | | | accommodative / neutral / restrictive |
| 10Y | | | | accommodative / neutral / restrictive |

Real rate = nominal − breakeven. Restrictive: real rate >2%; accommodative: real rate <0%.

### Step 4: Financial conditions

- 2Y, 5Y, 10Y swap spreads (where available)
- High-yield credit spread (FRED HYG-vs-Treasury proxy)
- VIX (current vs. 1Y avg)
- Trade-weighted USD index (DXY proxy)

Classify: `easing` / `neutral` / `tightening` / `stressed`.

### Step 5: Historical context

For each indicator, percentile rank of the current reading vs. trailing 5Y range. Flags any indicator at >95th or <5th percentile as `tail`.

### Step 6: Output

```json
{
  "as_of": "2026-MM-DD",
  "cycle_position": "expansion|late_cycle|contraction|recovery",
  "policy_outlook": "tightening|on_hold|easing",
  "curve_shape":   "normal|flat|inverted|humped",
  "real_rate_regime": "accommodative|neutral|restrictive",
  "financial_conditions": "easing|neutral|tightening|stressed",
  "macro_table":  [ {"indicator": "string", "value": 0, "prior": 0, "direction": "up|down|flat", "signal": "string"} ],
  "curve_table":  [ {"tenor": "string", "yield": 0.0} ],
  "real_rate_table": [ {"tenor": "string", "nominal": 0.0, "breakeven": 0.0, "real": 0.0, "signal": "string"} ],
  "tail_flags":   ["array of indicators currently >95th or <5th pctile of trailing 5Y"],
  "overall_assessment": "string ≤512 chars — 2-3 sentence narrative covering cycle, policy, conditions, key risks"
}
```

The structured output feeds:
- `regime-detector` MACRO label + confidence
- `morning-note` regime section
- Hindsight as a daily World Fact (with the realized state on each metric)

### Step 7: Tool-chaining discipline

When data sources return errors or are stale (>3 days for daily series, >35 days for monthly):
- Mark the affected indicator `stale` in the output
- Drop it from the overall assessment
- Surface to the operator if ≥2 indicators in the same domain (rates / inflation / activity) are stale — partial signals can mislead

## Important notes

- This is regime classification, not market commentary. Avoid directional language; the autoresearch loop translates regime state into position bias, not this prompt.
- Tail flags matter more than the central tendency — a 99th-pctile inflation print or 1st-pctile yield is what changes the regime, not gradual drift.
- Track regime transitions in Hindsight as Mental Model entries: when the MACRO regime flipped from `late_cycle` to `contraction`, what indicators led, by how many weeks?
- The "overall assessment" string is bounded at ≤512 chars and must be loadable into a downstream prompt without truncation. Keep it tight.
