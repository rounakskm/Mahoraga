<!--
Adapted from anthropics/financial-services @ 1c2ece3467c3434ddd01e655970e35b773940a29
Source: plugins/vertical-plugins/equity-research/skills/thesis-tracker/SKILL.md
License: Apache 2.0 (preserved below)
Adapted: 2026-05-09 for Mahoraga Reviewer role — kept the thesis-pillar / scorecard / falsifiability
discipline, retargeted "position" from human-managed long/short bets to autoresearch strategy
versions. Drives the "retire decaying edges" half of the autoresearch loop: a thesis whose pillars
fall is exactly a strategy whose edge has decayed.
-->

<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: Copyright (c) 2026 Anthropic PBC. Adapted by Mahoraga maintainers.
-->

# Thesis Tracker (Reviewer role)

Maintain falsifiable theses for every active strategy and watchlist candidate. Run on a schedule (weekly + on-event) and after every earnings analysis. **The scorecard output drives strategy retirement decisions in the autoresearch loop.**

## When to use

- A new strategy enters the registry → create thesis record
- An earnings analysis flags a thesis-pillar status change → update record
- A scheduled weekly review → recompute scorecard for every active strategy
- Operator asks "is strategy X still working?" → reload + summarize

## Workflow

### Step 1: Define or load thesis

For a new thesis (paired with a strategy version in `strategies.*` Postgres):

```json
{
  "thesis_id": "uuid",
  "strategy_id": "uuid",
  "strategy_version": "v1",
  "direction": "long|short|long_short_pair|long_short_basket",
  "thesis_statement": "1-2 sentence core thesis",
  "pillars": [
    { "id": "p1", "claim": "string", "expected": "string", "metric": "string" }
  ],
  "risks": ["3-5 statements that would invalidate the thesis if true"],
  "catalysts": ["upcoming events that could prove/disprove (link to catalyst-calendar event_ids)"],
  "valuation_target": { "type": "expected_sharpe|expected_return_pct|target_price", "value": 0 },
  "stop_loss_trigger": { "type": "drawdown|invalidating_event", "rule": "string" },
  "created_at": "2026-MM-DD"
}
```

A thesis without falsifiable pillars and explicit risks is **rejected** at creation time — it is not a thesis.

### Step 2: Update log

For each new data point or development:

```json
{
  "thesis_id": "uuid",
  "logged_at": "2026-MM-DD HH:MM TZ",
  "data_point": "string ≤256 chars",
  "thesis_impact": {
    "pillar_id": "p1|p2|...",
    "effect": "strengthened|weakened|invalidated|neutral"
  },
  "action": "no_change|reduce_size|halt_new_entries|retire_strategy",
  "updated_conviction": "high|medium|low"
}
```

Reviewer logs this as an Experience Fact in Hindsight.

### Step 3: Scorecard

Maintain a running scorecard for each thesis:

| pillar_id | original_expectation | current_status | trend |
|---|---|---|---|
| p1 | revenue growth >20% | Q3 was 22% | stable |
| p2 | margin expansion | margins flat YoY | concerning |
| p3 | new product launch | delayed to Q2 | watch |

Statuses: `confirmed`, `on_track`, `concerning`, `weakened`, `invalidated`, `untested`.

A thesis where:
- ≥1 pillar is `invalidated` → strategy flagged for retirement next autoresearch sweep
- ≥2 pillars are `weakened` → halt new entries, keep existing positions until firewall stop-loss
- All pillars `confirmed`/`on_track` → continue normal allocation

### Step 4: Catalyst calendar link

Track upcoming catalysts that will test pillars:

| date | event_id | pillar_tested | expected_outcome | realized_outcome |
|---|---|---|---|---|

After each event resolves, the realized outcome is filled in — pattern recognition over time learns which pillar types are reliable predictors.

### Step 5: Output

Three artifacts:
1. **Strategy registry update** — `strategies.theses` row with the latest scorecard.
2. **Hindsight Mental Model entry** — the disconfirming-evidence log so future strategy proposals can be cross-checked against past thesis failures.
3. **Operator-facing markdown** — only when status changes to `concerning`/`weakened`/`invalidated`. The morning report aggregates these.

## Important notes

- A thesis must be falsifiable — if nothing could disprove it, it is not a thesis.
- Track disconfirming evidence as rigorously as confirming evidence; it is more informative.
- Review every thesis at least quarterly even when nothing dramatic has happened — silent decay is the most dangerous kind.
- Multi-strategy reviews: when many theses share a pillar (e.g., "rates stay restrictive"), invalidation propagates — Reviewer must identify the shared pillar and surface it to the operator.
- Store thesis data in structured form so it is referenceable across sessions and feeds autoresearch retirement decisions automatically.
