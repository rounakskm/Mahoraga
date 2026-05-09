<!--
Adapted from anthropics/financial-services @ 1c2ece3467c3434ddd01e655970e35b773940a29
Source: plugins/vertical-plugins/equity-research/skills/catalyst-calendar/SKILL.md
License: Apache 2.0 (preserved below)
Adapted: 2026-05-09 for Mahoraga Researcher role — this is the directly load-bearing skill
for the firewall's ±30-min event-window block. Kept the calendar structure verbatim, dropped
"Excel workbook + Google Calendar" output (we emit JSON consumed by the firewall), retargeted
"our positioning" to the firewall's blackout-windows list.
-->

<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: Copyright (c) 2026 Anthropic PBC. Adapted by Mahoraga maintainers.
-->

# Catalyst Calendar (Researcher role)

Build and maintain a forward-looking calendar of events that affect the trading universe. **Drives the hard-limit firewall's "no entry within ±30 min of FOMC, CPI, NFP" rule** and Hunter's pre-event positioning.

## Workflow

### Step 1: Define coverage universe (from caller config)

- Tickers + ETFs to track
- Sector / industry filter
- Include macro events: yes (always for Mahoraga — FOMC, CPI, NFP gate the firewall)
- Time horizon (next 7 / 30 / 90 days)

### Step 2: Gather catalysts

**Earnings & financial events**
- Quarterly earnings date + time (pre/post market)
- Annual shareholder meeting
- Investor day / analyst day
- Capital markets day
- Debt maturity / refinancing dates

**Corporate events**
- Product launches and announcements
- FDA approvals / regulatory decisions
- Contract renewals or expirations
- M&A milestones (close dates, regulatory approvals)
- Management transitions
- Lockup expirations and insider trading windows

**Industry events**
- Major conferences (dates, presenting companies)
- Trade shows and expos
- Regulatory comment periods or rulings
- Industry data releases (monthly sales, traffic)

**Macro events (always required for the firewall)**
- FOMC meetings + minutes release
- CPI / Core CPI release
- NFP / unemployment release
- Other central-bank decisions (ECB, BOJ, BoE)
- GDP, PCE, retail sales, ISM, consumer confidence
- Geopolitical events with documented market-impact precedent

### Step 3: Calendar record (JSON, not Excel)

For each event:

```json
{
  "event_id": "uuid",
  "occurs_at": "2026-MM-DD HH:MM TZ",
  "event_type": "earnings|fomc|cpi|nfp|product|fda|manda|conference|other",
  "subject": "ticker | macro_indicator_name | sector",
  "expected_impact": "high|medium|low",
  "firewall_blackout": {
    "enabled": true,
    "window_minutes_before": 30,
    "window_minutes_after": 30,
    "applies_to": "all_new_entries | sector | ticker"
  },
  "notes": "string ≤256 chars"
}
```

### Step 4: Weekly preview

Generate a forward-looking summary every Monday 06:00 ET:

**This week's key events**
- `[day]: [subject] [event_type]` — one-line context
- Macro: highlight FOMC/CPI/NFP days as **firewall-blocked**

**Next week preview** — early heads-up on important events.

**Position implications** — events that could move open positions; pre-positioning notes; risk-management ahead of binary events.

### Step 5: Output

- **JSON calendar file** — consumed by the execution firewall to block entries during blackout windows
- **Markdown weekly preview** — for the operator-facing morning report
- **Hindsight write** — each event as a World Fact with the realized outcome appended after the event closes (feeds pattern-recognition)

## Important notes

- Earnings dates shift — verify against IR pages and the data provider 24h before the event. The calendar must self-correct.
- Pre-announce risk: track tickers with a history of pre-announcing (positive or negative) and widen their blackout window to ±60 min.
- Conference attendance lists matter — companies that are conspicuously absent from a major conference are a signal.
- Recurring catalysts (monthly industry data) get an auto-populated template; one-offs (FDA decisions) get manual entry.
- Color/impact coding: `high` = firewall-block + Hunter pre-position notice; `medium` = firewall-block only; `low` = info-only.
- After the event resolves, archive the realized outcome alongside the prediction in Hindsight — pattern recognition over time depends on this.
