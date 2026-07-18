#!/bin/bash
# Daily paper-window driver — launchd fires this twice per day (see
# infra/ops/com.mahoraga.paper-window.plist):
#
#   before 13:00 local -> ONE signal-driven live-paper cycle (weekdays only)
#   13:00 or later     -> end-of-day P&L + position snapshot recording
#
# The strategy artifact defaults to the vault-validated seed4 candidate and can
# be overridden via MAHORAGA_PAPER_STRATEGY in .env. All output is appended to
# data/logs/paper_window.log. ALWAYS exits 0 (launchd-friendly): a failed run
# is diagnosed from the log, never from the exit status.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT" || exit 0

mkdir -p data/logs
LOG="data/logs/paper_window.log"

{
    echo "==== paper_window $(date '+%Y-%m-%d %H:%M:%S %Z') ===="

    # Env (Alpaca keys, MAHORAGA_DSN, FRED_API_KEY, MAHORAGA_PAPER_STRATEGY).
    set -a
    # shellcheck disable=SC1091
    source .env 2>/dev/null
    set +a

    hour=$((10#$(date +%H)))
    if (( hour < 13 )); then
        # Morning cycle branch — market days only (launchd StartCalendarInterval
        # cannot express per-entry weekday filters, so the guard lives here).
        if [[ $(date +%u) -lt 6 ]]; then
            # 1) refresh live news → World Facts + per-symbol sentiment snapshot
            #    (the Phase-4 "sentiment every 15 min" cadence via periodic REST)
            uv run python scripts/run_intel.py refresh --symbols SPY QQQ IWM || true
            # 2) the multi-symbol signal-driven live-paper cycle over the watchlist;
            #    each symbol passes the portfolio-wide firewall independently.
            uv run python scripts/run_paper.py cycle \
                --strategy "${MAHORAGA_PAPER_STRATEGY:-strategies/seed11-1783928660.json}" \
                --signal \
                --watchlist \
                --live-orders
        else
            echo "weekend — skipping cycle"
        fi
    else
        uv run python scripts/run_paper.py eod
    fi

    echo "==== done (rc=$?) ===="
} >> "$LOG" 2>&1

exit 0
