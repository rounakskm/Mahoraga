"""refresh_once — one periodic REST pass: fetch → ingest → sentiment snapshot.

Pure function (client / classifier / aggregator injected) so tests use a fake
client returning fixture `NewsItem`s. Per symbol it fetches news since `since`,
ingests through the aggregator (which retains MATERIAL/CRITICAL as World Facts),
computes the point-in-time `SentimentState` at now, and — when a snapshot dir is
given — writes `data/sentiment/<symbol>.json` (`symbol`/`score`/`n`/`asof`) that
the MICRO lens or a future live firewall can read.

Disabled (no-key) clients short-circuit to `{"counts": {}, "states": {}}` with no
write, mirroring the graceful-offline contract used across the intelligence layer.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path

import pandas as pd

from services.trader.news.aggregator import SentimentAggregator, SentimentState
from services.trader.news.alpaca_news import AlpacaNewsClient
from services.trader.news.classifier import NewsClassifier

_DEFAULT_SNAPSHOT_DIR = Path("data/sentiment")


def refresh_once(
    client: AlpacaNewsClient,
    classifier: NewsClassifier,  # noqa: ARG001 (aggregator owns classification; kept for a stable call site)
    aggregator: SentimentAggregator,
    symbols: list[str],
    since: pd.Timestamp,
    *,
    snapshot_dir: Path | None = None,
) -> dict:
    """Fetch news since `since`, ingest, and snapshot per-symbol sentiment.

    Returns `{"counts": {level: n}, "states": {symbol: SentimentState}}`.
    A disabled client yields empty maps and writes nothing.
    """
    if not client.is_enabled():
        print("Alpaca key not set; nothing to refresh")
        return {"counts": {}, "states": {}}

    since = pd.Timestamp(since)
    since = since.tz_localize("UTC") if since.tzinfo is None else since.tz_convert("UTC")
    now = pd.Timestamp.now(tz="UTC")
    start = since.isoformat()
    end = now.isoformat()

    out_dir = snapshot_dir if snapshot_dir is not None else _DEFAULT_SNAPSHOT_DIR
    counts: Counter[str] = Counter()
    states: dict[str, SentimentState] = {}

    for symbol in symbols:
        items = client.fetch([symbol], start, end)
        classifications = aggregator.ingest(items)
        counts.update(c.level for c in classifications)
        state = aggregator.state(symbol, asof=now)
        states[symbol] = state
        _write_snapshot(out_dir, state)

    return {"counts": dict(counts), "states": states}


def _write_snapshot(out_dir: Path, state: SentimentState) -> None:
    """Atomic-ish write of one symbol's latest sentiment to `<dir>/<symbol>.json`."""
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "symbol": state.symbol,
        "score": state.score,
        "n": state.n,
        "asof": state.asof.isoformat(),
    }
    target = out_dir / f"{state.symbol}.json"
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    os.replace(tmp, target)
