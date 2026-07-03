"""Tests for SentimentAggregator — weighted rolling state + Hindsight World Facts."""

from __future__ import annotations

import pandas as pd

from services.trader.news.aggregator import SentimentAggregator, SentimentState
from services.trader.news.alpaca_news import NewsItem
from services.trader.training.hindsight_client import HindsightClient

_ASOF = pd.Timestamp("2026-06-30T12:00:00Z")


class _FakeHindsight(HindsightClient):
    """HindsightClient that records `retain` calls instead of hitting the network."""

    def __init__(self) -> None:
        super().__init__(base_url="http://fake")
        self.calls: list[tuple[str, dict]] = []

    def retain(self, text: str, metadata: dict | None = None) -> str | None:
        self.calls.append((text, metadata or {}))
        return f"fact-{len(self.calls)}"


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


def test_state_weighted_score_and_n() -> None:
    items = [
        _item(1, "strong beat guidance raised profit surge", 2.0),  # in 24h
        _item(2, "downgrade loss miss decline weak", 100.0),  # in 7d
        _item(3, "gain upside rally", 600.0),  # in 30d (~25d)
        _item(4, "stale old news", 24 * 40),  # outside 30d
    ]
    agg = SentimentAggregator()
    agg.ingest(items)

    state = agg.state("SPY", _ASOF)
    assert isinstance(state, SentimentState)
    assert state.symbol == "SPY"
    assert -1.0 <= state.score <= 1.0
    assert state.n == 3  # only items within 30d
    assert set(state.windows) == {"24h", "7d", "30d"}
    assert all(-1.0 <= v <= 1.0 for v in state.windows.values())


def test_state_empty_is_zero() -> None:
    agg = SentimentAggregator()
    state = agg.state("SPY", _ASOF)
    assert state.score == 0.0
    assert state.n == 0


def test_state_accepts_tz_naive_asof() -> None:
    # A naive asof is treated as UTC (same normalization as features/sentiment.py).
    items = [
        NewsItem(
            id=1,
            created_at=pd.Timestamp("2024-01-01T12:00:00Z"),
            headline="strong beat guidance raised profit surge",
            summary="",
            symbols=["SPY"],
            source="test",
            url="http://x",
        )
    ]
    agg = SentimentAggregator()
    agg.ingest(items)
    state = agg.state("SPY", pd.Timestamp("2024-01-02"))  # tz-naive
    assert isinstance(state, SentimentState)
    assert state.n == 1
    assert state.score > 0.0


def test_state_respects_asof() -> None:
    items = [_item(1, "gain upside rally beat", 2.0)]
    agg = SentimentAggregator()
    agg.ingest(items)
    early = agg.state("SPY", _ASOF - pd.Timedelta(hours=5))
    assert early.n == 0
    assert early.score == 0.0


def test_ingest_retains_material_and_critical_only() -> None:
    hs = _FakeHindsight()
    agg = SentimentAggregator(hindsight=hs)
    items = [
        _item(1, "FOMC hikes rates hawkish", 1.0),  # CRITICAL (urgency trigger)
        _item(2, "strong beat guidance raised profit surge rally", 2.0),  # MATERIAL
        _item(3, "company names new office manager", 3.0),  # BACKGROUND
    ]
    classifications = agg.ingest(items)
    assert len(classifications) == 3

    n_material_plus = sum(1 for c in classifications if c.level in {"MATERIAL", "CRITICAL"})
    assert n_material_plus >= 1
    assert len(hs.calls) == n_material_plus  # exactly non-BACKGROUND retained
    for _text, meta in hs.calls:
        assert meta["kind"] == "world_fact"
        assert meta["ticker"] == "SPY"
        assert meta["classification"] in {"MATERIAL", "CRITICAL"}
        assert "sentiment" in meta
        assert meta["source"] == "test"
        assert "ts" in meta


def test_ingest_no_hindsight_still_classifies() -> None:
    agg = SentimentAggregator(hindsight=None)
    out = agg.ingest([_item(1, "FOMC hikes rates hawkish", 1.0)])
    assert len(out) == 1
    state = agg.state("SPY", _ASOF)
    assert state.n == 1


def test_rolling_series_is_15min_indexed_and_monotonic() -> None:
    items = [
        _item(1, "gain rally", 6.0),
        _item(2, "loss decline", 3.0),
        _item(3, "beat surge", 1.0),
    ]
    agg = SentimentAggregator()
    series = agg.rolling_series("SPY", items, freq="15min")
    assert isinstance(series, pd.Series)
    assert len(series) > 0
    assert series.index.is_monotonic_increasing
    deltas = series.index.to_series().diff().dropna().unique()
    assert all(d == pd.Timedelta(minutes=15) for d in deltas)
