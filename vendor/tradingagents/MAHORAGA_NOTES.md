# Mahoraga adaptation of tauricresearch/tradingagents

This file is the canonical record of (a) how this vendored copy is tracked, (b) which modules we plan to cherry-pick into `services/trader/`, (c) which we explicitly reject, (d) every upstream pull we land, and (e) every cherry-pick we perform.

See architecture revision [`docs/superpowers/specs/2026-04-26-architecture-revision-consolidated-assistant.md`](../../docs/superpowers/specs/2026-04-26-architecture-revision-consolidated-assistant.md) for the architectural posture (Apache 2.0 paper-backed reference, never integrated wholesale; cherry-picks are one-way and manual).

## Vendored at

- Upstream: `https://github.com/tauricresearch/tradingagents`
- Tag: `v0.2.4` (paper at arXiv:2412.20138)
- Commit SHA (peeled): `7c37249f808f9c169ad2198dc384166e7ca7adf9`
- Date pulled: `2026-04-30`
- License: Apache 2.0

## Vendoring discipline

This is a **live `git subtree`**, mirrored on the NemoClaw vendoring pattern. We pull updates monthly because tradingagents is actively maintained and the community is large; bug fixes and new analyst-prompt versions arriving upstream are valuable.

- **Routine pulls:** monthly. First business day of the month, or whenever a new minor release ships and we want it.
- **Pull command:**
  ```bash
  git fetch tradingagents-upstream
  git subtree pull --prefix=vendor/tradingagents tradingagents-upstream <tag-or-sha> --squash
  ```
- **Push policy:** never automatic. If we ever want to upstream a fix, that is an explicit `git subtree push` against a separate branch + a deliberate PR — never accidental.
- **On every pull:** scan the upstream diff against the **Modifications log** (below). If upstream touched any file we have already cherry-picked + adapted, raise a follow-up review for re-cherry-pick consideration. Cherry-picks are one-way + manual; upstream changes do **not** auto-propagate to our adapted copy in `services/trader/`.

## License obligations

- Preserve `vendor/tradingagents/LICENSE` (Apache 2.0) verbatim. Never delete.
- Preserve any upstream `NOTICE` file if it exists (`tradingagents` v0.2.4 ships none at the root; re-check on every pull).
- Every cherry-picked file in `services/trader/` keeps the original Apache header and adds a Mahoraga-attribution block citing source path + upstream SHA. See [planned discipline below](#cherry-pick-attribution).

## Cherry-pick targets (planned, by phase)

These are scheduled extractions per the integration plan. Specific upstream paths confirmed against `v0.2.4`. Each cherry-pick lands at the listed target in `services/trader/` with adaptations applied (PIT correctness, retries, vault-embargo enforcement, no LangChain/LangGraph imports).

### Phase 1 — Foundation (data layer)

| Source path in `vendor/tradingagents/` | Target | Adaptation |
|---|---|---|
| `tradingagents/dataflows/y_finance.py` | `services/trader/tools/data_yfinance.py` | tenacity retries; PIT-clamp every `end` arg to `as_of`; vault-embargo enforcement; strip LangChain `Tool` wrapper |
| `tradingagents/dataflows/alpha_vantage*.py` (6 files) | `services/trader/tools/data_alphavantage.py` | + per-key rate-limit token bucket (5 req/min free tier) |
| `tradingagents/dataflows/stockstats_utils.py` | `services/trader/tools/indicators.py` | strip "today" defaults; force explicit `as_of` |
| `tradingagents/dataflows/yfinance_news.py` | `services/trader/tools/news_yfinance.py` | PIT-clamp; vault embargo; upstream of FinBERT (Phase 4) |

### Phase 4 — Intelligence (news + sentiment + research)

| Source path in `vendor/tradingagents/` | Target | Adaptation |
|---|---|---|
| `tradingagents/agents/analysts/news_analyst.py` (prompt) | `services/trader/agents/web_research/prompts/news_synthesis.md` | strip LangChain `ChatPromptTemplate` → plain markdown; remove debate hooks |
| `tradingagents/agents/analysts/social_media_analyst.py` (prompt) | reference for sentiment summarizer | only the *aggregation* prompt is reusable; FinBERT does classification |
| `tradingagents/agents/analysts/fundamentals_analyst.py` (prompt) | `services/trader/agents/web_research/prompts/fundamentals.md` | drop LangGraph state passing; map `tool_calls` onto OpenClaw tool registry |
| `tradingagents/agents/researchers/{bull_researcher,bear_researcher}.py` (prompts) | `services/trader/agents/web_research/prompts/{bull,bear}_briefing.md` | use as **single-pass briefing pair** fed into Archivist L2 synthesis. **Do NOT import multi-turn debate loop** — that is a live-pace pattern. |
| `tradingagents/dataflows/alpha_vantage_news.py` | merged into `services/trader/tools/news_fetch.py` (Phase 4) | PIT-clamp; vault embargo |

### Phase 5 — Paper trading

| Source path in `vendor/tradingagents/` | Target | Adaptation |
|---|---|---|
| `tradingagents/agents/managers/risk_manager.py` (position-sizing math, NOT veto logic) | `services/trader/execution/position_sizer.py` | extract Kelly / vol-targeting math only; hard limits stay in our firewall (architecture spec §5.5); their soft-veto language deleted |

### Explicitly rejected

- **`tradingagents/graph/` (LangGraph orchestration)** — substrate-portability violation. We use NemoClaw + OpenClaw subagent dispatch.
- **`tradingagents/agents/managers/risk_manager.py` (veto logic)** — our hard-limit firewall enforces at the execution boundary; soft veto would weaken the architecture.
- **`tradingagents/agents/researchers/` multi-turn debate loop** — live-pace pattern, incompatible with our compressed-replay autoresearch.
- **Backtrader harness** (if/when present) — committed to vectorbt for compressed-replay throughput (~100× faster).
- **Redis cache layer** — Postgres + pgvector is the single application database.
- **Any fetcher that defaults `end=datetime.now()`** — every Mahoraga loader must require explicit `as_of`.
- **LangChain `ChatPromptTemplate` / `Tool` wrappers** — strip when extracting prompts; OpenClaw tool registry is the substrate.

## Cherry-pick attribution discipline

Every cherry-picked file in `services/trader/`:

1. Preserves the original Apache 2.0 header verbatim at the top.
2. Adds a Mahoraga-attribution block immediately below:
   ```python
   # Adapted for Mahoraga from tauricresearch/tradingagents
   # Source: vendor/tradingagents/<original/path.py>
   # Upstream commit: <SHA at time of cherry-pick>
   # Modifications: <one-line summary>
   ```
3. Records an entry in the Modifications log below.
4. Passes the substrate-portability CI guard (`grep -R "langgraph\|langchain" services/trader/` must return empty).

## Subtree-pull log

| Date | Prior SHA | New SHA | Tag | Upstream summary | Cherry-picked files affected |
|---|---|---|---|---|---|
| 2026-04-30 | (initial) | `7c37249f` | v0.2.4 | Initial subtree-add | (none yet) |

## Modifications log (cherry-picks performed)

_None yet._ Append one row per cherry-pick when each Phase 1/4/5 sub-feature lands.

## Conventions for Tier-3 patches inside `vendor/tradingagents/`

If we ever need to modify the vendored tree directly (rare; same posture as NemoClaw §3 three-tier extension model):

1. Tag the diff in source with `// MAHORAGA-PATCH(YYYY-MM-DD): <reason>`.
2. Record below: date, files touched, scope, reason, upstream-PR status.

_No Tier-3 patches yet._
