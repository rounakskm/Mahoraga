#!/usr/bin/env python3
"""Hermes gateway liveness trigger — Mitigation 1 for NemoClaw issue #2426.

Division of responsibility (IMPORTANT — do not reinvent NemoClaw)
----------------------------------------------------------------
NemoClaw OWNS gateway recovery. It ships the relaunch logic (buildRecoveryScript
in agent/runtime.ts), the on-demand recovery command (`nemoclaw <name> recover`),
the full re-provision (`nemoclaw <name> rebuild`), and diagnostics
(`nemoclaw <name> doctor`). This script must NOT reimplement any of that.

What NemoClaw does NOT ship is a CONTINUOUS SUPERVISOR — recovery is on-demand,
so nothing auto-detects a crashed gateway and invokes recovery. That single gap
is all this watchdog fills: it polls health and, when the gateway is down, calls
NemoClaw's OWN `recover`. If recover does not restore health, it raises a loud
operator ALERT (and only escalates to `nemoclaw rebuild` when explicitly opted in
via --allow-rebuild — rebuilding the trading brain unattended is itself risky).

Why recover can fail (verified in Rung-D testing, 2026-06-20)
------------------------------------------------------------
A hard gateway death (e.g. SIGKILL) is NOT auto-recovered: NemoClaw's recovery
script refuses to relaunch the gateway when the security preloads are missing
(#2478, "refusing unguarded gateway relaunch") — a deliberate safety guard, not a
bug to work around. The reliable recovery in that case is `nemoclaw <name> rebuild
--yes` (requires the provider credential, e.g. COMPATIBLE_API_KEY, in the env),
which re-provisions with correct env. #2426 + #2478 are tracked upstream; per the
ADR they are a Phase-6 entry gate, not a Phase 2-5 blocker (zero capital at risk).
See ADR docs/superpowers/specs/2026-06-12-hermes-runtime-migration.md section 4.

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
        --sandbox mahoraga-hermes \
        --health-url http://127.0.0.1:8642/health \
        --interval 30
    # add --allow-rebuild to let it escalate to `nemoclaw rebuild` autonomously
    # (off by default; requires the provider credential in env).

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


def restart_gateway(restart_cmd: str, *, log_path: str | None = None) -> bool:
    """Invoke the configured restart command. Return True on exit code 0.

    Output is redirected to a FILE (or DEVNULL), never to a captured pipe.
    `nemoclaw <name> recover` spawns a background port-forward daemon that
    inherits the child's stdout/stderr fds. With `capture_output=True` the pipe
    never reaches EOF (the daemon holds the write end open forever), so
    `subprocess.run` blocks until the timeout and the gateway is never actually
    recovered — even though `recover` itself finishes in ~1s. Writing to a real
    file avoids the pipe read; `start_new_session` detaches the daemon from the
    watchdog's process group. Found in Rung-D testing, 2026-06-12.
    """
    _log(f"gateway unhealthy — restarting via: {restart_cmd}")
    log_path = log_path or os.environ.get(
        "MAHORAGA_WATCHDOG_RESTART_LOG", "/tmp/mahoraga-watchdog-restart.log"
    )
    try:
        with open(log_path, "ab", buffering=0) as logf:  # noqa: PTH123
            result = subprocess.run(  # noqa: S603
                shlex.split(restart_cmd),
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=logf,
                stderr=logf,
                start_new_session=True,
                timeout=180,
            )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        _log(f"restart command failed to run: {exc!r}")
        return False
    if result.returncode == 0:
        _log("restart command exited 0")
        return True
    _log(f"restart command exited {result.returncode}; see {log_path}")
    return False


def _paused() -> bool:
    """Operator-initiated halts set this so the watchdog does not fight them."""
    return os.environ.get("MAHORAGA_WATCHDOG_PAUSED", "").strip() in {"1", "true", "yes"}


def restore_gateway(
    *, sandbox: str, health_url: str, health_timeout: float, allow_rebuild: bool
) -> bool:
    """Drive NemoClaw's OWN recovery commands; return True if health restored.

    This is a thin trigger over NemoClaw — it does not implement recovery itself.
      Tier 1: `nemoclaw <sandbox> recover` (NemoClaw's recovery script).
      Tier 2: `nemoclaw <sandbox> rebuild --yes` — ONLY if allow_rebuild; heavy
              re-provision; needs the provider credential (e.g. COMPATIBLE_API_KEY)
              in the watchdog's env. Recovers a hard gateway death (#2426/#2478).
    Otherwise: a loud operator ALERT. We never loop-rebuild the trading brain
    unattended.
    """
    restart_gateway(f"nemoclaw {sandbox} recover")
    if gateway_healthy(health_url, health_timeout):
        _log("NemoClaw `recover` restored the gateway")
        return True
    if allow_rebuild:
        _log("`recover` insufficient (likely #2478) — escalating to `rebuild --yes`")
        restart_gateway(f"nemoclaw {sandbox} rebuild --yes")
        if gateway_healthy(health_url, health_timeout):
            _log("NemoClaw `rebuild` restored the gateway")
            return True
    _log(
        "ALERT: gateway DOWN and NemoClaw `recover` did not restore it "
        f"(#2426/#2478). Operator: run `nemoclaw {sandbox} rebuild --yes` with the "
        "provider credential (e.g. COMPATIBLE_API_KEY) set in the environment."
    )
    return False


def watch(
    *,
    sandbox: str,
    health_url: str,
    interval: float,
    health_timeout: float,
    max_restarts_per_hour: int,
    allow_rebuild: bool,
) -> None:
    _log(
        f"starting — polling {health_url} every {interval:.0f}s for sandbox "
        f"'{sandbox}' (restart cap {max_restarts_per_hour}/h, "
        f"allow_rebuild={allow_rebuild})"
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
        restore_gateway(
            sandbox=sandbox,
            health_url=health_url,
            health_timeout=health_timeout,
            allow_rebuild=allow_rebuild,
        )


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
        "--sandbox",
        default=os.environ.get("MAHORAGA_WATCHDOG_SANDBOX", "mahoraga-hermes"),
        help="NemoClaw sandbox name; its `recover`/`rebuild` commands are invoked.",
    )
    parser.add_argument(
        "--allow-rebuild",
        action="store_true",
        default=os.environ.get("MAHORAGA_WATCHDOG_ALLOW_REBUILD", "").strip()
        in {"1", "true", "yes"},
        help="Let the watchdog escalate to `nemoclaw <sandbox> rebuild --yes` when "
        "`recover` fails (off by default; needs the provider credential in env).",
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
            sandbox=args.sandbox,
            health_url=args.health_url,
            interval=args.interval,
            health_timeout=args.health_timeout,
            max_restarts_per_hour=args.max_restarts_per_hour,
            allow_rebuild=args.allow_rebuild,
        )
    except KeyboardInterrupt:
        _log("interrupted — exiting")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
