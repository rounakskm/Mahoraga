# Mahoraga

Self-improving, regime-aware autonomous trading system for US equities/ETFs. It detects
market regimes (MACRO/MESO/MICRO), trains regime-conditional strategies through an
anti-overfitting fortress on real SPY history, reads live news sentiment, and executes
through a hard-limit firewall against an Alpaca **paper** account. Real capital is gated
behind a fail-closed convergence report **and** an explicit human sign-off — always.

Project context and architecture: [`CLAUDE.md`](CLAUDE.md) · spec map:
[`docs/superpowers/specs/`](docs/superpowers/specs/) · live status:
[`docs/PROGRESS.md`](docs/PROGRESS.md)

**Status:** Phases 1–6 complete. The 30-day paper-trading window is live (zero real capital).

---

## 1. Setup

### Prerequisites

| Needed for | Requirement |
|---|---|
| Everything | Python 3.11+, [`uv`](https://docs.astral.sh/uv/) (`brew install uv`), Git 2.40+ |
| Postgres (trade store, provenance, audit) | Docker Desktop or Colima |
| Hermes agent fleet substrate (optional — training runs without it) | Node.js 22.16+, [Ollama](https://ollama.ai) on host |

### API keys

Copy the template, then fill in keys. **`.env` is git-ignored — secrets never leave your machine.**

```bash
cp .env.example .env
```

| Key | Get it at | Needed for |
|---|---|---|
| `ALPACA_API_KEY` + `ALPACA_SECRET_KEY` | [alpaca.markets](https://alpaca.markets) (free; create a **paper** account) | News archive (Phase 4), paper trading (Phase 5). The single most important pair. |
| `POSTGRES_PASSWORD` | choose one | Trade store, provenance, audit chain |
| `MAHORAGA_DSN` | `postgresql://postgres:<POSTGRES_PASSWORD>@localhost:5432/postgres` | Same (the connection string the scripts read) |
| `NVIDIA_API_KEY` | [build.nvidia.com](https://build.nvidia.com) (free tier) | LLM-driven training mutations (`--llm`) |
| `FRED_API_KEY` | [fred.stlouisfed.org](https://fred.stlouisfed.org/docs/api/api_key.html) (free, instant) | CPI/NFP release blackout in the execution firewall (FOMC dates work without it) |
| `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` | @BotFather on Telegram | Optional: `/halt` `/status` operator commands |
| `ANTHROPIC_API_KEY` etc. | — | Optional: extra LLM providers via LiteLLM |

Everything degrades gracefully: a missing key disables that feature with a logged
warning instead of crashing.

### Bring up the stack and load market data

```bash
# Postgres (schemas auto-apply on first init)
docker compose up -d postgres

# ~10 years of real SPY daily OHLCV -> data/parquet/ohlcv/SPY/
uv sync
uv run python scripts/pull_spy_daily.py

# sanity: full test suite (fast, offline; DSN-gated tests skip without Postgres env)
uv run --with pytest python -m pytest services/trader -q
```

Optional (for the seven-role Hermes fleet + Hindsight memory): `docker compose up -d`
brings up LiteLLM + Hindsight too; the NemoClaw/Hermes sandbox setup is in
[`infra/nemoclaw/`](infra/nemoclaw/) and `scripts/onboard.sh`.

---

## 2. Start training

The autoresearch loop mutates a **regime-conditional** strategy (per-regime SMA windows
+ learnable regime-detector thresholds), scores every candidate through the Phase-2
anti-overfitting fortress (PBO/DSR walls + gates), and only promotes survivors that also
hold on an untouched 6-month vault. Results stream live to `data/autoresearch/<run>.csv`.

```bash
# Mechanical hill-climb (no LLM, no network — the baseline)
uv run python scripts/run_autoresearch.py --iterations 50

# LLM-proposed mutations (Nemotron via NVIDIA_API_KEY), detector learnable too
uv run python scripts/run_autoresearch.py --iterations 50 --llm --learn-detector

# The seven-role fleet (Planner->Reviewer->Hunter->Guardian->Archivist), one nightly cadence
uv run python scripts/run_autoresearch.py --fleet --cadence nightly --iterations 10

# Compressed-history replay: "experience" ~5 years of regimes, PIT-clamped, never
# touching the vault (the system's core thesis)
uv run python scripts/run_autoresearch.py --fleet --cadence replay --iterations 3
```

Promoted, vault-holding strategies land in `strategies/<run>.json` (and
`strategies.registry` when Postgres is up) — these artifacts are what paper trading
executes. Runbook: [`docs/runbooks/autoresearch-training.md`](docs/runbooks/autoresearch-training.md).

## 3. News + sentiment intelligence

```bash
# Ingest + classify real SPY news (CRITICAL/MATERIAL/BACKGROUND + sentiment)
uv run python scripts/run_intel.py ingest --symbols SPY --start 2024-01-01

# The real point-in-time sentiment feature over a date range
uv run python scripts/run_intel.py sentiment --symbol SPY --start 2024-03-01 --end 2024-03-15

# Weekly macro brief (FRED / SEC EDGAR / Fed RSS synthesis)
uv run python scripts/run_intel.py brief
```

## 4. Paper trading (zero real capital)

Everything is **dry-run by default**. A live paper order requires the explicit
`--live-orders` flag, a real market quote, and passes halt-check → hard-limit firewall
(5% position / 20% sector / 2% daily loss / regime confidence / FOMC-CPI-NFP blackout /
2×ATR stop) → PDT+wash-sale compliance before it can reach Alpaca.

```bash
# Read-only: your paper account + positions
uv run python scripts/run_paper.py account
uv run python scripts/run_paper.py positions

# One signal-driven cycle, DRY-RUN (nothing submitted)
uv run python scripts/run_paper.py cycle --strategy strategies/seed4-1782849823.json --signal

# The same cycle, LIVE against the paper account (prints a warning banner)
uv run python scripts/run_paper.py cycle --strategy strategies/seed4-1782849823.json --signal --live-orders

# End-of-day: record daily P&L + position snapshot (feeds the convergence report)
uv run python scripts/run_paper.py eod
```

**The 30-day window, hands-off:** install the launchd agent (cycle 7:35am PT weekdays,
EOD 1:15pm PT) — deliberately a human step:

```bash
cp infra/ops/com.mahoraga.paper-window.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.mahoraga.paper-window.plist
```

Runbook (disable, logs, halt options): [`docs/runbooks/paper-window.md`](docs/runbooks/paper-window.md).

## 5. Monitor and control

```bash
# Operator dashboard: positions, orders, P&L, fleet activity, HALT/RESUME buttons
uv run --with streamlit streamlit run scripts/dashboard.py

# The go/no-go gate for real capital (fail-closed: unmeasured = NOT READY)
uv run python scripts/convergence_report.py --date $(date +%F)
```

**Kill switch (<10s, halts every cycle):** the dashboard HALT button, Telegram `/halt`,
or `touch data/control/halt.flag`. Resume via the dashboard, `/resume`, or deleting the flag.

**The line that never moves:** paper trading needs `--live-orders`; **real capital
needs a passing convergence report (≥30 paper days, Sharpe >1.0, replay ≥3yr, all
regimes covered) *and* an explicit human sign-off.** The report can't pass vacuously —
anything unmeasured fails.

---

## Project layout

- `services/trader/` — all domain code (substrate-portable, plain Python): `data` `features` `regime` `walls` `gates` `backtest` `training` `news` `intel` `execution` `ops`
- `scripts/` — the operator entry points used above
- `infra/` — Postgres migrations, NemoClaw/Hermes config + subagent defs, CI guards, launchd
- `vendor/` — NemoClaw (subtree), tradingagents (subtree), Hindsight (subtree), autoresearch (frozen), multiautoresearch (frozen reference)
- `docs/` — project plan, specs (`superpowers/specs/`), runbooks, PROGRESS, convergence reports

## Updating vendored upstreams

```bash
git fetch nemoclaw-upstream
git subtree pull --prefix=vendor/nemoclaw nemoclaw-upstream <new-tag> --squash
uv run --with pytest python -m pytest services/trader -q
```

Routine pulls monthly; security advisories within 72h. History:
[`vendor/nemoclaw/MAHORAGA_CHANGES.md`](vendor/nemoclaw/MAHORAGA_CHANGES.md).
