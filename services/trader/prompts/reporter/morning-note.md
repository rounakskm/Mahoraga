<!--
Adapted from anthropics/financial-services @ 1c2ece3467c3434ddd01e655970e35b773940a29
Source: plugins/vertical-plugins/equity-research/skills/morning-note/SKILL.md
License: Apache 2.0 (preserved below)
Adapted: 2026-05-09 for Mahoraga Reporter role — kept the tight 2-minute-readable format and
opinionated headline discipline, retargeted from sell-side morning meeting to operator-facing
Mahoraga summary (no clients, no PMs — the operator is the audience). Drops "no news = valid
note" — Mahoraga's morning note is generated regardless of news because it must always include
the firewall blackout windows and the regime-detector state.
-->

<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: Copyright (c) 2026 Anthropic PBC. Adapted by Mahoraga maintainers.
-->

# Morning Note (Reporter role)

The 06:00 ET daily summary delivered to the operator. Tight, opinionated, action-oriented. **Must always include the firewall blackout windows for today and the regime classification state — these are not optional even on quiet days.** Designed to be readable in 2 minutes.

## Workflow

### Step 1: Pull state from sidecars

- **Hindsight** — Experience Facts logged in last 24h, Observations promoted overnight, any Mental Model updates
- **Postgres `audit.events`** — last 24h of trader actions and any halt events
- **Postgres `strategies.*`** — open positions, exposure by sector, any thesis-tracker status changes
- **Catalyst calendar** — today's events with firewall blackouts
- **Regime detector** — current MACRO / MESO / MICRO classification + confidence
- **Overnight news** — Hunter's news-classifier summary (Phase 4+)

### Step 2: Format

```markdown
# Mahoraga Morning Note — [date] [day-of-week]

## Top Call: [headline — the one thing the operator needs to know]
2-3 sentences. The headline can be: a strategy that hit a stop-loss; a regime change overnight;
a thesis-pillar invalidation; a planned blackout window with material exposure; or "all green,
holding through today's CPI print" if it's quiet.

## Regime State
- MACRO: [label] (confidence X%)
- MESO:  [label] (confidence X%)
- MICRO: [label] (confidence X%)
Δ from yesterday: [one-line on what shifted]

## Today's Firewall Blackouts
- [HH:MM ET] [event_type] [subject] — [width ±N min]
- (or "none today")

## Open Positions (top 5 by exposure)
| ticker | direction | exposure_pct | thesis_status | next_catalyst |

## Overnight Developments
- [Ticker]: one-line summary + thesis impact
- [Sector / Macro]: relevant move + how it affects open exposure

## Strategy Status Changes (last 24h)
- [Strategy v3]: pillar p2 weakened — halt new entries; existing positions held
- (or "none")

## Operator Action Items
- (e.g., "review proposed retirement of strategy v1 in autoresearch queue")
- (or "none — system running within bounds")
```

### Step 3: Length discipline

- Total ≤500 words. The operator should finish in 2 minutes.
- Top Call is the load-bearing section — never bury the headline.
- "No news" is NOT a valid morning note for Mahoraga (unlike sell-side); the regime/firewall/positions sections are always present.
- Be opinionated — a note that summarizes without taking a view is useless.
- If a thesis was wrong yesterday, own it in today's note.

### Step 4: Output

- Markdown file at `data/morning-notes/YYYY-MM-DD.md`
- Telegram channel post (Phase 6+) — same content, possibly trimmed to top 3 sections
- Audit row in `audit.events` with `action='morning_note_published'`

## Important notes

- The Reporter does not make trading decisions. It surfaces state and changes; the autoresearch loop and the firewall make decisions.
- Time-stamp everything — the morning note is a snapshot at 06:00 ET; pre-market moves between then and 09:30 may invalidate parts of it. The note's footer notes generation time.
- Distinguish actionable events (catalyst that requires position adjustment) from noise (minor analyst notes, non-events).
- Credibility compounds — when the morning note is wrong, the next note opens with the correction. The operator's trust in the system depends on this discipline.
