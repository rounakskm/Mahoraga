#!/usr/bin/env python3
"""Bootstrap script: regenerate `data/universe/sp500/{seed,events}.yaml` from Wikipedia.

Operator-run, NOT in the runtime path. Pulls the current S&P 500 constituents
table + the "Selected changes" table, back-derives the seed at a configurable
historical date, and writes both YAML files in the schema the loader expects.

Usage:
    python scripts/build_sp500_universe.py [--seed-date 2014-01-01]
                                            [--root data/universe]
                                            [--url https://...]

The script never touches the network in tests; the parsing / back-derivation
logic in `services.trader.universe.bootstrap` is unit-tested with fixture
DataFrames.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from services.trader.data.audit import PostgresAuditWriter
from services.trader.universe.bootstrap import (
    SP500_WIKI_URL,
    back_derive_seed,
    filter_and_sort_events,
    parse_sp500_changes,
    parse_sp500_members,
)
from services.trader.universe.manifest import RebuildManifestWriter, RebuildRun

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    started_at = datetime.now(UTC)
    run = RebuildRun(
        run_id=str(uuid.uuid4()),
        source="sp500-wikipedia",
        started_at=started_at,
    )

    try:
        tables = pd.read_html(args.url)
        if len(tables) < 2:
            raise RuntimeError(
                f"expected at least 2 tables on the Wikipedia page, got {len(tables)}"
            )
        current = parse_sp500_members(tables[0])
        changes = parse_sp500_changes(tables[1])
        seed_members = back_derive_seed(current, changes, args.seed_date)
        events = filter_and_sort_events(changes, args.seed_date)

        _write_seed(args.root / "sp500" / "seed.yaml", args.seed_date, seed_members)
        _write_events(args.root / "sp500" / "events.yaml", events)

        run.seed_size = len(seed_members)
        run.events_count = len(events)
        logger.info(
            "wrote sp500 universe: seed_date=%s seed_size=%d events=%d",
            args.seed_date,
            run.seed_size,
            run.events_count,
        )
    except Exception as exc:  # noqa: BLE001  (top-level script handler)
        run.errors.append(f"{type(exc).__name__}: {exc}")
        logger.exception("build_sp500_universe failed")
        run.finished_at = datetime.now(UTC)
        _finalize(run, args.root)
        return 1

    run.finished_at = datetime.now(UTC)
    _finalize(run, args.root)
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--root",
        default=Path("data/universe"),
        type=Path,
        help="universe root directory (default: data/universe)",
    )
    p.add_argument(
        "--seed-date",
        default=date(2014, 1, 1),
        type=date.fromisoformat,
        help="seed date in ISO format (default: 2014-01-01)",
    )
    p.add_argument(
        "--url",
        default=SP500_WIKI_URL,
        help="Wikipedia URL (default: List of S&P 500 companies)",
    )
    return p.parse_args(argv)


def _write_seed(path: Path, seed_date: date, members: set[str]) -> None:
    body = {
        "name": "sp500",
        "seed_date": seed_date,
        "members": sorted(members),
    }
    _write_yaml(path, body)


def _write_events(path: Path, events: list[dict[str, Any]]) -> None:
    body = {
        "name": "sp500",
        "events": [
            {"date": ev["date"], "ticker": ev["ticker"], "action": ev["action"]}
            for ev in events
        ],
    }
    _write_yaml(path, body)


def _write_yaml(path: Path, body: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(body, sort_keys=False, default_flow_style=False))


def _finalize(run: RebuildRun, root: Path) -> None:
    manifest = RebuildManifestWriter(root)
    try:
        manifest.append(run)
    except Exception as exc:  # noqa: BLE001
        logger.error("manifest write failed: %s", exc)

    dsn = os.environ.get("MAHORAGA_AUDIT_DSN") or os.environ.get("MAHORAGA_TEST_DSN")
    writer = PostgresAuditWriter(dsn=dsn)
    if not writer.is_enabled():
        logger.info("audit-events row not recorded (no MAHORAGA_AUDIT_DSN/_TEST_DSN)")
        return
    try:
        writer.write(
            actor="universe-bootstrap",
            action="universe_rebuild",
            payload={
                "run_id": run.run_id,
                "source": run.source,
                "started_at": run.started_at.isoformat(),
                "finished_at": (run.finished_at or run.started_at).isoformat(),
                "seed_size": run.seed_size,
                "events_count": run.events_count,
                "errors": run.errors,
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("audit-events write failed: %s", exc)


if __name__ == "__main__":
    sys.exit(main())
