#!/usr/bin/env python3
"""Run the Mahoraga Telegram ops bot with the REAL providers wired in.

    uv run python scripts/run_telegram_bot.py                     # long-poll
    uv run python scripts/run_telegram_bot.py --once "/status"    # one command

Builds `HaltControl` (the file-flag kill-switch), `Reporter(dsn)` (fleet
status), `DashboardData(dsn, hindsight=...)` and the four read-only providers
from `services.trader.ops.bot_providers`, then hands them to `TelegramOps`.

SAFETY — the allowlist is REQUIRED for polling. `TelegramOps` treats
`allowed_chat_ids=None` as "open" (its offline/test path); an OPEN bot on the
public Telegram API would let any stranger who discovers the bot handle issue
`/resume` and clear the kill-switch (or `/halt` to grief the fleet). So this
runner refuses to poll unless `TELEGRAM_CHAT_ID` is set, printing why and
exiting 0. `--once` handles a single command locally (no polling, no Telegram
round-trip), so it needs neither token nor allowlist — it is the smoke path.

Env (read via `os.environ.get`, never required — every path degrades):
    TELEGRAM_BOT_TOKEN     — bot token from @BotFather; unset -> informative skip.
    TELEGRAM_CHAT_ID       — the operator's chat id; the polling allowlist.
    MAHORAGA_DSN           — Postgres DSN for /status, /strategy and /report.
    MAHORAGA_HINDSIGHT_URL — Hindsight endpoint for /kb + the learned overlay.
    MAHORAGA_HALT_FLAG     — kill-switch flag path override (see ops/halt.py).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

# scripts/ is not a package; anchor the repo root before the services imports.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from services.trader.ops.bot_providers import build_providers  # noqa: E402
from services.trader.ops.dashboard_data import DashboardData  # noqa: E402
from services.trader.ops.halt import HaltControl  # noqa: E402
from services.trader.ops.reporter import Reporter  # noqa: E402
from services.trader.ops.telegram import TelegramOps  # noqa: E402
from services.trader.training.hindsight_client import HindsightClient  # noqa: E402

logger = logging.getLogger("run_telegram_bot")


def build_ops() -> TelegramOps:
    """TelegramOps over the real providers, configured entirely from env."""
    dsn = os.environ.get("MAHORAGA_DSN")
    hindsight = HindsightClient(os.environ.get("MAHORAGA_HINDSIGHT_URL"))
    data = DashboardData(dsn=dsn, hindsight=hindsight)
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    return TelegramOps(
        HaltControl(),
        Reporter(dsn),
        token=os.environ.get("TELEGRAM_BOT_TOKEN"),
        allowed_chat_ids={chat_id} if chat_id else None,
        **build_providers(data, dsn=dsn, hindsight=hindsight),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--once",
        metavar="COMMAND",
        help='handle ONE command locally and print the reply (e.g. "/status"); '
        "no polling, no token or allowlist needed",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    ops = build_ops()

    if args.once:
        print(ops.handle(args.once))
        return 0

    if not ops.token:
        print(
            "TELEGRAM_BOT_TOKEN not set — nothing to poll; skipping. "
            '(Local smoke: --once "/status")'
        )
        return 0

    if not ops.allowed_chat_ids:
        print(
            "Refusing to poll without a chat allowlist: set TELEGRAM_CHAT_ID. "
            "An open bot would let anyone /resume the kill-switch."
        )
        return 0

    logger.info(
        "polling Telegram (allowlist: %s chat id(s)); Ctrl-C to stop",
        len(ops.allowed_chat_ids),
    )
    ops.poll()
    return 0


if __name__ == "__main__":
    sys.exit(main())
