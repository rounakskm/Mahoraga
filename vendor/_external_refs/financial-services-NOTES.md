# anthropics/financial-services — Mahoraga port log

This file tracks one-way ports of analyst skills and leaf-worker JSON-schemas from
[`anthropics/financial-services`](https://github.com/anthropics/financial-services) into
`services/trader/prompts/` and `services/trader/contracts/`.

This is **not** a `git subtree` — there is no upstream tracking, no automated pull.
Every port is manual, attribution-tagged, and recorded below.

## Why a port log instead of a vendor subtree

The full analysis is in the chat transcript dated 2026-05-09. Summary:

- The upstream repo is an **analyst-assistant skill marketplace** (pitch decks, earnings notes,
  KYC, GL recon) — not a trading system.
- It ships zero backtester, zero regime detection, zero broker connector, zero risk-limit
  enforcement, and explicitly disclaims "investment recommendations or transaction execution."
- Its data plane is paywalled enterprise MCPs (FactSet, CapIQ, Daloopa, S&P Kensho, LSEG,
  Morningstar, PitchBook, Moody's) — none of which we use or can reach from inside the
  NemoClaw-managed sandbox cheaply.
- Its hosted-agent path (`POST https://api.anthropic.com/v1/agents` with hardcoded
  `claude-opus-4-7`) bypasses our LiteLLM gateway and breaks our local-first posture.

What it *does* have are well-written analyst-style markdown skills that encode useful analytical
patterns: long/short/value/quality screen taxonomies, earnings-preview scenario frameworks,
catalyst-calendar event structures, comps-spread sanity rules, macro-narrative scaffolds, and
JSON-schema-disciplined leaf-worker output contracts. Those are worth lifting as
**prompt-engineering reference**, not as a runtime dependency.

So we cherry-pick — not subtree — and we record every port here so attribution and refresh
discipline survive future maintainers.

## Upstream pin (as of last sync)

- Repo: `https://github.com/anthropics/financial-services`
- Commit: `1c2ece3467c3434ddd01e655970e35b773940a29`
- Date pulled: `2026-05-09`
- License: `Apache 2.0` (preserved on each ported file via SPDX header + Mahoraga-attribution
  comment block)

## Port log

| # | Source path (relative to upstream repo root) | Mahoraga path | Tier | Adaptation summary |
|---|---|---|---|---|
| 1 | `managed-agent-cookbooks/earnings-reviewer/subagents/transcript-reader.yaml` | `services/trader/contracts/transcript-reader.schema.json` | 2 | Lifted JSON output_schema verbatim; stripped YAML container, model pin, MCP wiring. |
| 2 | `managed-agent-cookbooks/market-researcher/subagents/sector-reader.yaml` | `services/trader/contracts/sector-reader.schema.json` | 2 | Lifted JSON output_schema verbatim. (claim, source) pair is load-bearing. |
| 3 | `managed-agent-cookbooks/meeting-prep-agent/subagents/news-reader.yaml` | `services/trader/contracts/news-reader.schema.json` | 2 | Lifted JSON output_schema; retargeted from "client emails / news" to "Phase-4 news classifier inputs". |
| 4 | `managed-agent-cookbooks/pitch-agent/subagents/researcher.yaml` | `services/trader/contracts/researcher.schema.json` | 2 | Lifted JSON output_schema verbatim. The most polished generic researcher schema in the source repo. |
| 5 | `managed-agent-cookbooks/valuation-reviewer/subagents/package-reader.yaml` | `services/trader/contracts/package-reader.schema.json` | 2 | Lifted JSON output_schema; retargeted from PE-fund LP-reporting to autoresearch strategy reviews; added `backtest`/`walk_forward`/`monte_carlo` to the method enum. |
| 6 | `plugins/vertical-plugins/equity-research/skills/idea-generation/SKILL.md` | `services/trader/prompts/hunter/idea-generation.md` | 1 | Kept screen taxonomy verbatim; dropped interactive "ask the user" framing (Hunter runs autonomously); retargeted "next steps" from human-handoff to autoresearch-loop handoff. |
| 7 | `plugins/vertical-plugins/equity-research/skills/sector-overview/SKILL.md` | `services/trader/prompts/researcher/sector-overview.md` | 1 | Kept market-overview / competitive / valuation structure; replaced "investment implications" with regime-narration + Hunter-overlay hints + autoresearch mutation seeds. |
| 8 | `plugins/vertical-plugins/equity-research/skills/earnings-preview/SKILL.md` | `services/trader/prompts/researcher/earnings-preview.md` | 1 | Kept bull/base/bear scenario framework + catalyst checklist; added structured `firewall_blackout` block consumed by the execution firewall. |
| 9 | `plugins/vertical-plugins/equity-research/skills/earnings-analysis/SKILL.md` | `services/trader/prompts/researcher/earnings-analysis.md` | 1 | Kept beat/miss + variance + thesis-impact pattern; dropped 200+ lines of DOCX/chart/page-template/citation-hyperlink machinery; retargeted to structured JSON output + 4-hour SLA. |
| 10 | `plugins/vertical-plugins/equity-research/skills/catalyst-calendar/SKILL.md` | `services/trader/prompts/researcher/catalyst-calendar.md` | 1 | Kept calendar structure + macro-event categories; replaced Excel-workbook output with JSON consumed by the firewall. Directly load-bearing for the ±30-min FOMC/CPI/NFP/earnings rule. |
| 11 | `plugins/vertical-plugins/equity-research/skills/thesis-tracker/SKILL.md` | `services/trader/prompts/reviewer/thesis-tracker.md` | 1 | Kept thesis-pillar / scorecard / falsifiability discipline; retargeted from human-managed long/short bets to autoresearch strategy versions; pillar-invalidation drives strategy retirement. |
| 12 | `plugins/vertical-plugins/equity-research/skills/morning-note/SKILL.md` | `services/trader/prompts/reporter/morning-note.md` | 1 | Kept the 2-minute-readable + opinionated headline format; retargeted to operator-facing Mahoraga summary (no clients/PMs); always-include regime + firewall sections. |
| 13 | `plugins/vertical-plugins/financial-analysis/skills/comps-analysis/SKILL.md` | `services/trader/prompts/researcher/comps-analysis.md` | 1 | Lifted the analytical patterns only (peer-set definition, metric-by-question, statistics, sanity checks, red flags); dropped 600+ lines of Excel formulas, formatting, color palette, Office-JS API. |
| 14 | `plugins/vertical-plugins/financial-analysis/skills/audit-xls/SKILL.md` | `services/trader/prompts/reviewer/audit-xls.md` | 1 | Kept QC philosophy + universal sanity checks; replaced model-specific (DCF/LBO/3-stmt/merger) checks with backtest-output analogs (PnL reconstruction, Sharpe sanity, regime coverage, look-ahead-bias trace, hard-limit conformance). |
| 15 | `plugins/partner-built/lseg/skills/macro-rates-monitor/SKILL.md` | `services/trader/prompts/researcher/macro-rates-monitor.md` | 1 | Kept the cycle / curve / real-rate / financial-conditions narrative scaffolding; stripped every LSEG-MCP tool ref; replaced data plane with FRED + TreasuryDirect + BLS (free); output drives MACRO regime classification. |
| 16 | `plugins/partner-built/lseg/skills/option-vol-analysis/SKILL.md` | `services/trader/prompts/researcher/option-vol-analysis.md` | 1 | Kept implied-vs-realized + surface-shape framework; stripped LSEG-MCP option/vol tool refs; replaced data plane with CBOE indices + yfinance options; output drives MICRO regime + position-sizing scalar. |
| 17 | `plugins/agent-plugins/earnings-reviewer/agents/earnings-reviewer.md` | `services/trader/prompts/researcher/_agent_earnings-reviewer.md` | 3 | Compound agent prompt (filename `_agent_` prefix); composes earnings-preview / earnings-analysis / transcript-reader / thesis-tracker / morning-note into one event-window pipeline. Replaced FactSet/Daloopa MCP refs and Excel "model update" with autoresearch parameter review. |
| 18 | `plugins/agent-plugins/market-researcher/agents/market-researcher.md` | `services/trader/prompts/researcher/_agent_market-researcher.md` | 3 | Compound agent prompt (`_agent_` prefix); composes sector-overview / comps-analysis / idea-generation / sector-reader / morning-note. Stripped CapIQ/FactSet MCP refs; replaced Word/PPT output framing with structured JSON + markdown brief. |

## Maintenance protocol

- **Refreshing**: pick a new upstream commit, re-run the analysis from scratch (do not auto-port).
  Update the "Upstream pin" block above and add a new commit row to each affected port.
- **Adding a new port**: append a new row to the Port log; add the SPDX + Mahoraga-attribution
  comment to the new file; reference it from the relevant role's prompt index.
- **Removing a port**: leave the row in the log with a `removed: <date>, reason: <text>` note —
  history matters for license-audit reproducibility.
- **License compliance**: every ported file carries the upstream Apache 2.0 license header
  alongside the Mahoraga-attribution comment. Removing either is forbidden.

## Triggers to re-evaluate "adopt as vendor subtree"

Per the original analysis, the cherry-pick stance flips to "adopt-as-vendor" only if upstream
ships **all three** of:

1. Free or self-hostable MCP servers for OHLC + macro + news in this repo.
2. A backtester or trading-agent eval harness.
3. A non-preview managed-agents path that exposes an OpenAI-compatible endpoint we can route
   through LiteLLM.

Until all three are true, this port log is the canonical mechanism. Re-evaluate quarterly.
