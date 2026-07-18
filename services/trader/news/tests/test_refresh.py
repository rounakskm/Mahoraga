"""Tests for refresh_once — periodic REST news refresh cadence (pure helper)."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pandas as pd

from services.trader.news.aggregator import SentimentAggregator, SentimentState
from services.trader.news.alpaca_news import AlpacaNewsClient, NewsItem
from services.trader.news.classifier import NewsClassifier
from services.trader.news.refresh import refresh_once

_ASOF = pd.Timestamp("2026-07-17T12:00:00Z")


def _item(id_: int, headline: str, hours_ago: float, symbol: str = "SPY") -> NewsItem:
    return NewsItem(
        id=id_,
        created_at=_ASOF - pd.Timedelta(hours=hours_ago),
        headline=headline,
        summary="",
        symbols=[symbol],
        source="test",
        url="http://x",
    )


class _FakeClient(AlpacaNewsClient):
    """Enabled client that returns fixture items without any network call."""

    def __init__(self, items: list[NewsItem]) -> None:
        super().__init__(key="k", secret="s")
        self._items = items

    def fetch(
        self,
        symbols: Sequence[str],
        start: str,
        end: str,
        limit: int = 50,
    ) -> list[NewsItem]:
        wanted = set(symbols)
        return [i for i in self._items if wanted.intersection(i.symbols)]


class _DisabledClient(AlpacaNewsClient):
    """No-key client: is_enabled() is False, fetch() must never be called."""

    def __init__(self) -> None:
        super().__init__(key=None, secret=None)

    def fetch(self, *args: object, **kwargs: object) -> list[NewsItem]:  # noqa: ARG002
        raise AssertionError("disabled client must not fetch")


def _fixture_items() -> list[NewsItem]:
    # One item per level: CRITICAL trigger, MATERIAL, BACKGROUND.
    return [
        _item(1, "SEC halts trading bankruptcy fraud investigation", 1.0),
        _item(2, "strong beat guidance raised profit surge", 3.0),
        _item(3, "minor product update note", 5.0),
    ]


def test_refresh_once_returns_states_and_counts(tmp_path: Path) -> None:
    client = _FakeClient(_fixture_items())
    agg = SentimentAggregator(classifier=NewsClassifier())

    result = refresh_once(
        client,
        NewsClassifier(),
        agg,
        ["SPY"],
        since=_ASOF - pd.Timedelta(minutes=20),
        snapshot_dir=tmp_path,
    )

    states = result["states"]
    assert set(states) == {"SPY"}
    assert isinstance(states["SPY"], SentimentState)

    counts = result["counts"]
    assert sum(counts.values()) == 3
    assert counts.get("CRITICAL", 0) >= 1


def test_refresh_once_writes_snapshot(tmp_path: Path) -> None:
    client = _FakeClient(_fixture_items())
    agg = SentimentAggregator(classifier=NewsClassifier())

    refresh_once(
        client,
        NewsClassifier(),
        agg,
        ["SPY"],
        since=_ASOF - pd.Timedelta(minutes=20),
        snapshot_dir=tmp_path,
    )

    snap = tmp_path / "SPY.json"
    assert snap.exists()
    payload = json.loads(snap.read_text())
    assert set(payload) == {"symbol", "score", "n", "asof"}
    assert payload["symbol"] == "SPY"
    assert isinstance(payload["score"], float)
    assert isinstance(payload["n"], int)


def test_refresh_once_disabled_client_no_write(tmp_path: Path) -> None:
    client = _DisabledClient()
    agg = SentimentAggregator(classifier=NewsClassifier())

    result = refresh_once(
        client,
        NewsClassifier(),
        agg,
        ["SPY"],
        since=_ASOF - pd.Timedelta(minutes=20),
        snapshot_dir=tmp_path,
    )

    assert result == {"counts": {}, "states": {}}
    assert not (tmp_path / "SPY.json").exists()
