<!--
Adapted from anthropics/financial-services @ 1c2ece3467c3434ddd01e655970e35b773940a29
Source: plugins/partner-built/lseg/skills/option-vol-analysis/SKILL.md
License: Apache 2.0 (preserved below)
Adapted: 2026-05-09 for Mahoraga Researcher role — kept the implied-vs-realized-vol +
surface-shape framework, stripped LSEG-MCP tool refs (`equity_vol_surface`, `option_value`,
etc.). Mahoraga's universe is US equities + ETFs + BTC ETFs; we don't trade vanilla options
directly, but realized-vs-implied-vol skew is a high-signal MICRO regime input. Output drives
the regime-detector's MICRO classification (calm / normal / elevated / crisis) and informs
position-sizing scaled by regime-vol.
-->

<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: Copyright (c) 2026 Anthropic PBC. Adapted by Mahoraga maintainers.
-->

# Option Volatility Analysis (Researcher role)

Analyze implied vs. realized volatility for the Mahoraga universe. Mahoraga does not trade options as positions, but option-implied vol is the cleanest forward-looking measure of MICRO-regime stress. Output drives the regime-detector's MICRO label and the position-sizing vol scalar.

## Core principles

- Start from the **vol surface** — it encodes the market's view of future uncertainty across strikes and expiries.
- The **vol premium** (implied minus realized) is the key metric for assessing whether options are mis-priced — and by extension whether the underlying is in a stable or stressed regime.
- For Mahoraga, vol surface shape (skew, term structure) is a regime-classification input. Surface tilting steeper (puts richer than calls) is a tightening-stress signal.

## Data sources (Phase 1+ ingestion)

Free / cheap sources for the Mahoraga universe:
- **CBOE VIX, VIX9D, VVIX, VXN** — index-level implied vol time series (free)
- **CBOE put/call ratio, SKEW index** — surface shape proxies (free)
- **yfinance options chains** — sample IV at standard tenors for SPY/QQQ/IWM/major single names (free, daily lag)
- **CBOE Datashop / OPRA derived** — paid; consider only if needed in Phase 4+

For BTC ETFs (IBIT/FBTC/etc.), implied vol comes from the underlying ETF options chain plus the Deribit BTC IV index as cross-reference.

## Workflow

### Step 1: Vol surface snapshot

For each universe-defining instrument (SPY, QQQ, IWM, IBIT, plus tracked single names):

| tenor | atm_iv | rr_25d | bf_25d |
|---|---|---|---|
| 1M | | skew (puts − calls) | smile curvature |
| 3M | | | |
| 6M | | | |
| 1Y | | | |

ATM IV term structure: `inverted` (front > back), `flat`, or `upward-sloping` (back > front).

### Step 2: Realized vol

Compute close-to-close realized vol for the same instruments at matching tenors:
- 20-day realized (matches 1M IV)
- 60-day realized (matches 3M IV)
- 90-day realized (matches 6M IV)

Use log-return standard deviation × √252.

### Step 3: Implied vs. realized comparison

| Window | Realized | Implied (matching tenor) | Premium (IV − RV) | Signal |
|---|---|---|---|---|
| 20d | | 1M ATM | | rich / fair / cheap |
| 60d | | 3M ATM | | rich / fair / cheap |
| 90d | | 6M ATM | | rich / fair / cheap |

Premium > 5 vol pts: `rich`. Premium < −2 vol pts: `cheap`. In between: `fair`.

### Step 4: Surface-shape signals

- **Skew direction**: 25-delta put IV − 25-delta call IV > 5 pts → defensive positioning; <0 → call demand (rare in equities, common around event-driven setups)
- **Term-structure slope**: front-month IV > 3M IV → near-term event/stress priced in; back-month IV > front-month IV → "calm now, worried later"
- **VVIX > 110**: vol-of-vol elevated → unstable regime, even if VIX itself looks normal

### Step 5: MICRO regime classification

Based on the spread of signals across the universe:

```json
{
  "as_of": "2026-MM-DD",
  "micro_regime": "calm|normal|elevated|crisis",
  "confidence_pct": 0.0,
  "vol_premium_summary":  { "spy_3m": 0.0, "qqq_3m": 0.0, "ibit_3m": 0.0 },
  "skew_summary":         { "spy_25d_skew": 0.0, "qqq_25d_skew": 0.0 },
  "term_structure_summary": { "spy_front_minus_3m": 0.0 },
  "tail_flags":           ["VVIX above 110", "VIX9D inverted vs VIX", "BTC IV >2x SPY IV"],
  "position_sizing_scalar": 0.0
}
```

`position_sizing_scalar` is the multiplier the autoresearch loop applies to default position sizes given current MICRO regime:
- `calm` → 1.0
- `normal` → 0.8
- `elevated` → 0.5
- `crisis` → 0.0 (no new entries — falls into the firewall halt path)

### Step 6: Output

Two artifacts:
1. **JSON regime record** — feeds the regime-detector + autoresearch sizing.
2. **One-paragraph narrative** — for the morning note, ≤256 chars.

## Important notes

- Mahoraga does not pay for tick-level options data; daily-end IV from yfinance + CBOE indices is sufficient for regime classification.
- The vol premium is most informative when sustained — a one-day spike is noise; a 5-day rolling premium >5 vol pts is a regime change.
- Cross-asset checks matter: VIX up while bond vol (MOVE index) is flat tells a different story than both rising together.
- Hindsight stores the daily MICRO classification + the realized regime label decided 5 days later (by realized drawdown). Over time the gap between predicted and realized labels is itself a feedback signal that improves the threshold parameters.
