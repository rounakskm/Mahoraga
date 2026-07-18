# Runbook — 30-day paper-trading window

The paper window runs the promoted regime-conditional strategy against the live
Alpaca **paper** account once per market day, and records end-of-day state for
the convergence report. Everything routes through the production safety stack:
hard-limit firewall, compliance engine, econ-calendar blackout, reconciliation,
kill-switch.

## Moving parts

| Piece | Path |
|---|---|
| Daily driver script | `scripts/paper_window.sh` |
| launchd LaunchAgent | `infra/ops/com.mahoraga.paper-window.plist` |
| Runner | `scripts/run_paper.py` (`cycle --signal --live-orders`, `eod`) |
| Signal | `services/trader/execution/signal.py` |
| Strategy artifact | `strategies/seed4-1782849823.json` (override: `MAHORAGA_PAPER_STRATEGY` in `.env`) |
| Log | `data/logs/paper_window.log` |
| Results | Postgres `trades.pnl_daily`, `trades.orders`, `trades.positions` |

Schedule: **07:35 local** — one signal-driven cycle (script no-ops on Sat/Sun);
**13:15 local** — `eod` recording. Both entries invoke the same script, which
branches on the hour (before 13:00 → cycle, after → eod).

## Install

```sh
cp infra/ops/com.mahoraga.paper-window.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.mahoraga.paper-window.plist
```

Verify it registered:

```sh
launchctl list | grep com.mahoraga.paper-window
```

Prerequisites in `.env` at the repo root: `ALPACA_API_KEY` / `ALPACA_SECRET_KEY`
(paper), `MAHORAGA_DSN` (results won't persist without it), `FRED_API_KEY`
(CPI/NFP blackout; FOMC constants are enforced regardless).

## Disable

```sh
launchctl unload ~/Library/LaunchAgents/com.mahoraga.paper-window.plist
```

Re-enable with `launchctl load` again. To pause trading without unloading, trip
the kill-switch (below) — cycles then halt immediately at the executor's
halt-first check while `eod` recording continues.

## Watch the log

```sh
tail -f data/logs/paper_window.log
```

Each run is bracketed by `==== paper_window <timestamp> ====` / `==== done ====`
lines. A cycle prints the signal line (`signal: regime=... want_long=...`), the
reconcile result, and the `CycleReport(...)` summary; `eod` prints the recorded
equity / realized / unrealized row.

## Halt (kill-switch, <10s)

Any of:

- **Telegram**: send `/halt` to the ops bot.
- **Dashboard**: the halt button on the ops dashboard.
- **Manually**: create the flag file the `HaltControl` primitive polls —
  `touch data/control/halt.flag` (contents = optional reason). Clear with
  `rm data/control/halt.flag`.

A tripped halt stops every cycle at step 1 (nothing is sized, checked or
submitted) until the flag is cleared.

## Where the convergence report reads results

The convergence report (vault-holdout validation gate before any real capital)
reads the paper window's outcomes from Postgres:

- `trades.pnl_daily` — the date-keyed equity / realized / unrealized series
  written by `eod` (the realized P&L the Phase-5 halt keys on — NOT backtest DD).
- `trades.orders` + `trades.fills` — every submitted order with its signal
  reason string and firewall verdict trail (rejected orders never reach Alpaca).
- `trades.positions` — the per-cycle and end-of-day position snapshots used by
  reconciliation.

30 days of clean `pnl_daily` rows is the operational exit criterion for the
window; real capital remains a human gate.

## Tier-3 update: multi-symbol + news refresh

The daily cadence (`scripts/paper_window.sh`) now (1) runs `run_intel.py refresh --symbols SPY QQQ IWM` to pull live news into World Facts + per-symbol sentiment snapshots, then (2) runs the **multi-symbol** cycle `run_paper.py cycle --signal --watchlist` over SPY/QQQ/IWM/XLK/XLE/XLF/XLV — each symbol clears the portfolio-wide hard-limit firewall independently. Default strategy is `strategies/seed11-1783928660.json` (override via `MAHORAGA_PAPER_STRATEGY`).
