#!/usr/bin/env python3
"""Run the Phase-4 intelligence-layer cadences (graceful-offline).

Three subcommands, each degrading to a clear no-op skip (exit 0) when its
external dependency is absent — no Alpaca key, no Hindsight URL, no network:

    uv run python scripts/run_intel.py ingest --symbols SPY --start 2024-01-01
    uv run python scripts/run_intel.py refresh --symbols SPY QQQ --since-min 20
    uv run python scripts/run_intel.py brief
    uv run python scripts/run_intel.py sentiment --symbol SPY --start 2024-01-01 --end 2024-02-01

- `ingest`    — fetch the Alpaca news archive, classify + aggregate, optionally
                retain World Facts to Hindsight; prints classified counts by level.
- `refresh`   — one live REST pass over the last `--since-min` minutes: fetch +
                classify + aggregate (writes World Facts) + snapshot per-symbol
                sentiment. Invoked periodically (launchd), this REST cadence IS the
                Phase-4 "sentiment every 15 min" exit criterion.
                # ponytail: a held-open news websocket is a cloud-phase optimization;
                # periodic REST gives the same effect for a local operator.
- `brief`     — pull the T3 macro connectors, synthesize a weekly `MacroBrief`
                (deterministic template offline), print its narrative.
- `sentiment` — compute the PIT `SentimentFeature` for a ticker over a date range
                (live Alpaca client when keyed, else the 0.0 placeholder series),
                print the head + tail of the series.

Env (read via `os.environ.get`, never required):
    ALPACA_API_KEY / ALPACA_SECRET_KEY / ALPACA_DATA_ENDPOINT — news archive.
    MAHORAGA_HINDSIGHT_URL — Hindsight memory endpoint.
"""

from __future__ import annotations

import argparse
import os
from collections import Counter
from datetime import UTC, datetime

import pandas as pd

from services.trader.data.connectors.edgar import EdgarConnector
from services.trader.data.connectors.fed_rss import FedRssConnector
from services.trader.data.connectors.fedwatch import FedWatchConnector
from services.trader.features.base import FeatureContext
from services.trader.features.sentiment import SentimentFeature
from services.trader.intel.web_research import WebResearcher
from services.trader.news.aggregator import SentimentAggregator
from services.trader.news.alpaca_news import AlpacaNewsClient
from services.trader.news.classifier import NewsClassifier
from services.trader.news.refresh import refresh_once
from services.trader.training.hindsight_client import HindsightClient


def _alpaca_client() -> AlpacaNewsClient:
    """Build an `AlpacaNewsClient` from env; no key -> disabled (safe no-op)."""
    return AlpacaNewsClient(
        key=os.environ.get("ALPACA_API_KEY"),
        secret=os.environ.get("ALPACA_SECRET_KEY"),
        data_url=os.environ.get("ALPACA_DATA_ENDPOINT", "https://data.alpaca.markets"),
    )


def _hindsight() -> HindsightClient:
    """Build a `HindsightClient` from env; no URL -> disabled (safe no-op)."""
    return HindsightClient(os.environ.get("MAHORAGA_HINDSIGHT_URL"))


def cmd_ingest(args: argparse.Namespace) -> int:
    """Fetch -> classify -> aggregate. No key -> informative skip, exit 0."""
    client = _alpaca_client()
    if not client.is_enabled():
        print("Alpaca key not set; nothing to ingest")
        return 0

    hindsight = _hindsight()
    end = args.end or datetime.now(UTC).date().isoformat()
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]

    items = client.fetch(symbols, args.start, end)
    aggregator = SentimentAggregator(hindsight=hindsight if hindsight.is_enabled() else None)
    classifications = aggregator.ingest(items)

    counts = Counter(c.level for c in classifications)
    mem = "enabled" if hindsight.is_enabled() else "disabled"
    print(f"ingested {len(items)} items for {','.join(symbols)} [{args.start} -> {end}]")
    print(f"hindsight (World Facts): {mem}")
    for level in ("CRITICAL", "MATERIAL", "BACKGROUND"):
        print(f"  {level:<10} {counts.get(level, 0)}")
    return 0


def cmd_refresh(args: argparse.Namespace) -> int:
    """One live REST refresh pass. No key -> informative skip, exit 0."""
    client = _alpaca_client()
    if not client.is_enabled():
        print("Alpaca key not set; nothing to refresh")
        return 0

    hindsight = _hindsight()
    aggregator = SentimentAggregator(hindsight=hindsight if hindsight.is_enabled() else None)
    since = pd.Timestamp.now(tz="UTC") - pd.Timedelta(minutes=args.since_min)

    result = refresh_once(client, NewsClassifier(), aggregator, args.symbols, since=since)

    counts = result["counts"]
    total = sum(counts.values())
    mem = "enabled" if hindsight.is_enabled() else "disabled"
    print(f"refreshed {total} items for {' '.join(args.symbols)} (last {args.since_min} min)")
    print(f"hindsight (World Facts): {mem}")
    for level in ("CRITICAL", "MATERIAL", "BACKGROUND"):
        print(f"  {level:<10} {counts.get(level, 0)}")
    for symbol, state in result["states"].items():
        print(f"  {symbol:<6} score={state.score:+.3f} n={state.n}")
    return 0


def cmd_brief(args: argparse.Namespace) -> int:
    """Compose a weekly macro brief (deterministic template offline)."""
    connectors = {
        "edgar": EdgarConnector(),
        "fed_rss": FedRssConnector(),
        "fedwatch": FedWatchConnector(),
    }
    hindsight = _hindsight()
    researcher = WebResearcher(
        connectors,
        llm=None,
        hindsight=hindsight if hindsight.is_enabled() else None,
    )
    asof = pd.Timestamp(args.asof) if args.asof else pd.Timestamp.now(tz="UTC")
    brief = researcher.weekly_brief(asof)
    print(brief.narrative)
    return 0


def cmd_sentiment(args: argparse.Namespace) -> int:
    """Compute the PIT sentiment feature over a range; print series head/tail."""
    client = _alpaca_client()
    end = args.end or datetime.now(UTC).date().isoformat()
    start = pd.Timestamp(args.start, tz="UTC")
    stop = pd.Timestamp(end, tz="UTC")

    # A daily bar grid over [start, end] — the feature reads bar_timestamp/asof only.
    grid = pd.date_range(start, stop, freq="D", tz="UTC")
    if len(grid) == 0:
        print("empty date range; nothing to compute")
        return 0
    frame = pd.DataFrame(
        {"ticker": args.symbol, "bar_timestamp": grid, "close": 0.0, "volume": 0.0}
    )

    news_client = client if client.is_enabled() else None
    if news_client is None:
        print("Alpaca key not set; computing placeholder 0.0 sentiment series")
    feat = SentimentFeature(news_client=news_client, classifier=NewsClassifier())
    ctx = FeatureContext(
        ticker=args.symbol,
        frame=frame,
        asof=stop.to_pydatetime(),
        macro_fetcher=None,
    )
    series = feat.compute(ctx)
    series.index = grid

    print(f"sentiment_score for {args.symbol} [{args.start} -> {end}] ({len(series)} bars)")
    print("head:")
    print(series.head().to_string())
    print("tail:")
    print(series.tail().to_string())
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Phase-4 intelligence-layer runner (graceful-offline)"
    )
    sub = ap.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="fetch + classify + aggregate Alpaca news")
    p_ingest.add_argument("--symbols", default="SPY", help="comma-separated symbols")
    p_ingest.add_argument("--start", required=True, help="ISO date YYYY-MM-DD")
    p_ingest.add_argument("--end", default=None, help="ISO date (default: today)")
    p_ingest.set_defaults(func=cmd_ingest)

    p_refresh = sub.add_parser("refresh", help="one live REST refresh pass (periodic cadence)")
    p_refresh.add_argument("--symbols", nargs="+", default=["SPY"], help="symbols to refresh")
    p_refresh.add_argument(
        "--since-min", type=int, default=20, help="lookback window in minutes (default 20)"
    )
    p_refresh.set_defaults(func=cmd_refresh)

    p_brief = sub.add_parser("brief", help="synthesize + print the weekly macro brief")
    p_brief.add_argument("--asof", default=None, help="ISO date (default: now)")
    p_brief.set_defaults(func=cmd_brief)

    p_sent = sub.add_parser("sentiment", help="compute the sentiment feature over a range")
    p_sent.add_argument("--symbol", default="SPY")
    p_sent.add_argument("--start", required=True, help="ISO date YYYY-MM-DD")
    p_sent.add_argument("--end", default=None, help="ISO date (default: today)")
    p_sent.set_defaults(func=cmd_sentiment)

    args = ap.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
