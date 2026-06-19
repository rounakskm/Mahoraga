#!/usr/bin/env python3
"""Hermes gateway watchdog — Mitigation 1 for NemoClaw issue #2426.

Background
----------
NemoClaw issue #2426 (open as of 2026-06-12): if the Hermes gateway is ever
stopped, NemoClaw cannot bring it back up automatically (PR #2438 fixed only the
error message, not the recovery path). For a system that will eventually trade
real capital, an unrecoverable gateway after a halt is unacceptable.

This watchdog neutralizes #2426 for Phases 2-5 (zero capital at risk): it polls
the Hermes gateway health endpoint and re-launches the gateway when it stops
responding. See ADR docs/superpowers/specs/2026-06-12-hermes-runtime-migration.md
section 4, Mitigation 1.

Phase 6 entry gate
------------------
Before live capital (Phase 6), EITHER #2426 is closed upstream with a pinned
stable release, OR this watchdog is hardened to production grade (run under
systemd/launchd with alerting) and load-tested against the halt/resume cycle.
This script is the Phase 2-5 floor, not the Phase 6 ceiling.

Operational note
----------------
This watchdog is INTENTIONALLY dumb: it only restarts a *crashed* gateway. It
must NOT fight an operator-initiated halt. When the operator issues `/halt` or
`nemoclaw stop` deliberately, set MAHORAGA_WATCHDOG_PAUSED=1 (or stop the
watchdog) so it does not resurrect a gateway that was stopped on purpose. The
kill-switch contract (halt within seconds, recover only on explicit /resume)
lives in the architecture revision spec section 6 and takes precedence.

Usage
-----
    python scripts/hermes_gateway_watchdog.py \
        --health-url http://127.0.0.1:8642/health \
        --interval 30 \
        --restart-cmd "nemoclaw mahoraga-trader gateway start"

All flags also read from env (MAHORAGA_WATCHDOG_*). Stdlib only.
"""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime


def _log(msg: str) -> None:
    print(f"[{datetime.now(UTC).isoformat()}] watchdog: {msg}", flush=True)


def gateway_healthy(health_url: str, timeout: float) -> bool:
    """Return True iff the gateway health endpoint responds with HTTP 2xx."""
    try:
        with urllib.request.urlopen(health_url, timeout=timeout) as resp:  # noqa: S310
            return 200 <= resp.status < 300
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
        return False


def restart_gateway(restart_cmd: str) -> bool:
    """Invoke the configured restart command. Return True on exit code 0."""
    _log(f"gateway unhealthy — restarting via: {restart_cmd}")
    try:
        result = subprocess.run(  # noqa: S603
            shlex.split(restart_cmd),
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        _log(f"restart command failed to run: {exc!r}")
        return False
    if result.returncode == 0:
        _log("restart command exited 0")
        return True
    _log(f"restart command exited {result.returncode}: {result.stderr.strip()[:500]}")
    return False


def _paused() -> bool:
    """Operator-initiated halts set this so the watchdog does not fight them."""
    return os.environ.get("MAHORAGA_WATCHDOG_PAUSED", "").strip() in {"1", "true", "yes"}


def watch(
    *,
    health_url: str,
    interval: float,
    restart_cmd: str,
    health_timeout: float,
    max_restarts_per_hour: int,
) -> None:
    _log(
        f"starting — polling {health_url} every {interval:.0f}s "
        f"(restart cap {max_restarts_per_hour}/h)"
    )
    restart_times: list[float] = []
    while True:
        time.sleep(interval)
        if _paused():
            continue  # operator halted on purpose; do not resurrect
        if gateway_healthy(health_url, health_timeout):
            continue

        # Drop restart timestamps older than one hour, then enforce the cap.
        now = time.monotonic()
        restart_times = [t for t in restart_times if now - t < 3600]
        if len(restart_times) >= max_restarts_per_hour:
            _log(
                f"restart cap reached ({max_restarts_per_hour}/h) — gateway is "
                "flapping; backing off and leaving it down for operator review"
            )
            continue

        restart_times.append(now)
        restart_gateway(restart_cmd)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Hermes gateway watchdog (#2426 mitigation)")
    parser.add_argument(
        "--health-url",
        default=os.environ.get("MAHORAGA_WATCHDOG_HEALTH_URL", "http://127.0.0.1:8642/health"),
        help="Hermes gateway health endpoint (host-bridged port; default 8642).",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=float(os.environ.get("MAHORAGA_WATCHDOG_INTERVAL", "30")),
        help="Seconds between health checks (default 30).",
    )
    parser.add_argument(
        "--restart-cmd",
        default=os.environ.get(
            "MAHORAGA_WATCHDOG_RESTART_CMD",
            "nemoclaw mahoraga-trader gateway start",
        ),
        help="Command run to relaunch the gateway when it is unhealthy.",
    )
    parser.add_argument(
        "--health-timeout",
        type=float,
        default=float(os.environ.get("MAHORAGA_WATCHDOG_HEALTH_TIMEOUT", "5")),
        help="Per-probe HTTP timeout in seconds (default 5).",
    )
    parser.add_argument(
        "--max-restarts-per-hour",
        type=int,
        default=int(os.environ.get("MAHORAGA_WATCHDOG_MAX_RESTARTS_PER_HOUR", "6")),
        help="Flap guard: stop restarting after this many restarts in a rolling hour.",
    )
    args = parser.parse_args(argv)

    try:
        watch(
            health_url=args.health_url,
            interval=args.interval,
            restart_cmd=args.restart_cmd,
            health_timeout=args.health_timeout,
            max_restarts_per_hour=args.max_restarts_per_hour,
        )
    except KeyboardInterrupt:
        _log("interrupted — exiting")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
