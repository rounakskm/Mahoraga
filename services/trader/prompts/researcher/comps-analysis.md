<!--
Adapted from anthropics/financial-services @ 1c2ece3467c3434ddd01e655970e35b773940a29
Source: plugins/vertical-plugins/financial-analysis/skills/comps-analysis/SKILL.md
License: Apache 2.0 (preserved below)
Adapted: 2026-05-09 for Mahoraga Researcher role — the source is 661 lines of Excel-formula
+ formatting + color-palette guidance for human-built comp sheets. We extract only the
analytical patterns: peer-set definition, metric selection by question, statistics block
(quartiles), sanity checks, and red flags. Drops everything Excel/DOCX/Office-JS-specific.
The "FactSet/Bloomberg/Daloopa" hierarchy is replaced with "whatever data sources Phase 1 ships".
-->

<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: Copyright (c) 2026 Anthropic PBC. Adapted by Mahoraga maintainers.
-->

# Comparable Company Analysis (Researcher role)

Build a peer-set spread for a target ticker with consistent metric definitions and quartile statistics. Used for cross-sectional momentum / value / quality screens; produces the comps table that feeds Hunter's idea-generation step.

## Workflow

### Step 1: Define peer set

Companies must be **truly comparable**:
- Similar business model
- Similar scale (within ~3x revenue)
- Similar geography/regulatory regime
- Same sector classification (use one taxonomy consistently)

Better to have 3 perfect comps than 6 questionable ones. **When in doubt, exclude the company.**

### Step 2: Choose metrics by question

The analytical question dictates the metrics; Mahoraga screens for one of these at a time:

**"Which name is undervalued?"**
- EV/Revenue, EV/EBITDA, P/E, FCF yield
- Skip operational details

**"Which name is most efficient?"**
- Gross margin, EBITDA margin, FCF margin, ROIC, asset turnover
- Skip absolute size metrics

**"Which name is growing fastest?"**
- Revenue growth YoY, revenue acceleration, EBITDA CAGR, customer growth
- Skip margin metrics

**"Which is the best cash generator?"**
- FCF, FCF margin, FCF conversion, capex intensity
- Skip earnings-based multiples

### The 5-10 rule

5 operating metrics + 5 valuation metrics = 10 total columns. More than 15 is noise; edit ruthlessly.

### Step 3: Industry-specific overlay

Add 1–3 sector-specific metrics if relevant:

| Sector | Add | Skip |
|---|---|---|
| Software / SaaS | ARR, net retention, Rule of 40 | Asset turnover, inventory |
| Manufacturing / Industrials | EBITDA margin, asset turnover, capex/revenue | Rule of 40 |
| Financials | ROE, ROA, NIM, efficiency ratio | Gross margin, EBITDA |
| Retail / E-commerce | Same-store sales, GMV, inventory turns | Heavy R&D ratios |
| Healthcare | R&D/revenue, pipeline value, scripts | Asset turnover |

### Step 4: Build the spread (structured output)

```json
{
  "target": "TICKER",
  "as_of": "2026-MM-DD",
  "peer_set": ["TICKER1", "TICKER2", "..."],
  "rows": [
    {
      "ticker": "TICKER1",
      "metrics": {
        "revenue_ltm": 0,
        "revenue_growth_yoy": 0.0,
        "gross_margin": 0.0,
        "ebitda_margin": 0.0,
        "fcf_margin": 0.0,
        "ev_revenue": 0.0,
        "ev_ebitda": 0.0,
        "pe_ntm": 0.0
      }
    }
  ],
  "statistics": {
    "ev_ebitda":      { "max": 0, "p75": 0, "median": 0, "p25": 0, "min": 0 },
    "ebitda_margin":  { "max": 0, "p75": 0, "median": 0, "p25": 0, "min": 0 }
  },
  "data_sources": ["string per metric, dated"]
}
```

### Step 5: Sanity checks (run before emitting)

- **Margin test**: gross margin > EBITDA margin > net margin (always true by definition; if not, the data is wrong)
- **Multiple reasonableness**:
  - EV/Revenue: 0.5–20x typical (sector-dependent)
  - EV/EBITDA: 8–25x typical
  - P/E: 10–50x typical
- **Growth-multiple correlation**: higher growth usually means higher multiples; large violations flag a thesis or a data error
- **Time-period consistency**: never mix LTM and quarterly across rows
- **Data-source consistency**: every metric for a given ticker should come from the same source for the same period

### Step 6: Red flags

🚩 Inconsistent time periods (mixing quarterly and annual)
🚩 Missing data without explanation
🚩 >10% variance between data sources for the same metric
🚩 Negative-EBITDA companies being valued on EBITDA multiples (use revenue multiples instead)
🚩 P/E >100x without a hypergrowth story
🚩 Different fiscal year ends (timing mismatch)
🚩 Mixing pure-play and conglomerate businesses

When any flag fires, exclude the row and note the reason in `data_sources`.

## Important notes

- Statistics show patterns; the median + 25/75 quartiles tell you whether the target is rich or cheap relative to the peer set, and that signal is what feeds Hunter — not the absolute multiple.
- Higher growth is normally rewarded with a premium multiple; an outlier that has high growth AND a low multiple is the kind of intersection Hunter should escalate.
- The comps spread is data, not a recommendation — the autoresearch backtest validates whether the peer-relative signal predicts forward returns in this regime.
- Document every metric's source + as-of date inside `data_sources`; Hindsight ingests this so backtests can reproduce the peer-relative ranking at any historical point in time.
