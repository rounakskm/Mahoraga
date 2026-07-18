"""Tests for the Researcher pipeline (Tier-3 Task 3).

Stub connectors return fixture-shaped records (matching the real connector
return types); no network is ever touched. Covers the keyword→signal_kind
mapping, FedWatch high-confidence path, 8-K event mapping, the graceful
empty/erroring contract, Hindsight retain/recall grounding, and the planner-
queue shape.
"""

from __future__ import annotations

import hashlib

import pandas as pd

from services.trader.data.connectors.edgar import Filing
from services.trader.data.connectors.fed_rss import FedItem
from services.trader.intel.researcher import (
    Hypothesis,
    Researcher,
    to_planner_queue,
)

ASOF = pd.Timestamp("2026-07-17", tz="UTC")


# --- stub connectors --------------------------------------------------------


class _StubFedRss:
    def __init__(self, items: list[FedItem]) -> None:
        self._items = items

    def latest(self) -> list[FedItem]:
        return list(self._items)


class _StubEdgar:
    def __init__(self, filings: list[Filing]) -> None:
        self._filings = filings

    def recent_8k(self, ticker: str, since: pd.Timestamp) -> list[Filing]:
        return list(self._filings)


class _StubFedWatch:
    def __init__(self, probs: dict[str, float]) -> None:
        self._probs = probs

    def probabilities(self, asof: pd.Timestamp) -> dict[str, float]:
        return dict(self._probs)


class _ErroringConnector:
    def latest(self) -> list[FedItem]:
        raise RuntimeError("boom")

    def recent_8k(self, ticker: str, since: pd.Timestamp) -> list[Filing]:
        raise RuntimeError("boom")

    def probabilities(self, asof: pd.Timestamp) -> dict[str, float]:
        raise RuntimeError("boom")


class _FakeHindsight:
    """Records retains; recall returns a configurable do-not-repeat set."""

    def __init__(self, recall_texts: list[str] | None = None) -> None:
        self.retained: list[tuple[str, dict]] = []
        self._recall_texts = recall_texts or []

    def is_enabled(self) -> bool:
        return True

    def retain(self, text: str, metadata: dict | None = None) -> str:
        self.retained.append((text, metadata or {}))
        return "ok"

    def recall(self, query: str, k: int = 5) -> list[dict]:
        return [{"content": t} for t in self._recall_texts[:k]]


# --- fixtures ---------------------------------------------------------------


def _hawkish_fed_item() -> FedItem:
    return FedItem(
        title="Chair signals further rate hike to combat persistent inflation",
        published=ASOF,
        url="https://www.federalreserve.gov/x",
        kind="speeches",
    )


def _neutral_fed_item() -> FedItem:
    return FedItem(
        title="Federal Reserve Board announces new appointment to committee",
        published=ASOF,
        url="https://www.federalreserve.gov/y",
        kind="press",
    )


def _material_8k() -> Filing:
    return Filing(
        cik="884394",
        form="8-K",
        filed_at=ASOF,
        url="https://www.sec.gov/z",
        items=["2.02", "9.01"],
    )


# --- tests ------------------------------------------------------------------


def test_hawkish_fed_item_yields_rate_path() -> None:
    r = Researcher({"fed_rss": _StubFedRss([_hawkish_fed_item()])})
    hyps = r.scan(ASOF)
    kinds = {h.signal_kind for h in hyps}
    assert "rate_path" in kinds
    rate = next(h for h in hyps if h.signal_kind == "rate_path")
    assert rate.source == "fed_rss"
    assert 0.0 < rate.confidence <= 1.0


def test_neutral_fed_item_yields_no_hypothesis() -> None:
    r = Researcher({"fed_rss": _StubFedRss([_neutral_fed_item()])})
    assert r.scan(ASOF) == []


def test_high_fedwatch_prob_yields_high_confidence_rate_path() -> None:
    r = Researcher({"fedwatch": _StubFedWatch({"+25bps hike": 0.7})})
    hyps = r.scan(ASOF)
    rate = [h for h in hyps if h.signal_kind == "rate_path"]
    assert len(rate) == 1
    assert rate[0].confidence >= 0.7
    assert "+25bps hike" in rate[0].text
    assert "70%" in rate[0].text
    assert rate[0].source == "fedwatch"


def test_low_fedwatch_prob_is_dropped() -> None:
    r = Researcher({"fedwatch": _StubFedWatch({"+25bps hike": 0.4})})
    assert r.scan(ASOF) == []


def test_material_8k_yields_event() -> None:
    r = Researcher(
        {"edgar": _StubEdgar([_material_8k()])}, watchlist=["SPY"]
    )
    hyps = r.scan(ASOF)
    events = [h for h in hyps if h.signal_kind == "event"]
    assert len(events) == 1
    assert events[0].source == "edgar"


def test_8k_without_items_is_not_material() -> None:
    empty_8k = Filing(
        cik="884394",
        form="8-K",
        filed_at=ASOF,
        url="https://www.sec.gov/z",
        items=[],
    )
    r = Researcher({"edgar": _StubEdgar([empty_8k])}, watchlist=["SPY"])
    assert r.scan(ASOF) == []


def test_empty_connectors_yield_empty() -> None:
    r = Researcher({"fed_rss": _StubFedRss([]), "fedwatch": _StubFedWatch({})})
    assert r.scan(ASOF) == []


def test_no_connectors_yield_empty() -> None:
    assert Researcher({}).scan(ASOF) == []


def test_erroring_connectors_never_raise() -> None:
    r = Researcher(
        {
            "fed_rss": _ErroringConnector(),
            "edgar": _ErroringConnector(),
            "fedwatch": _ErroringConnector(),
        }
    )
    assert r.scan(ASOF) == []


def test_dedup_identical_hypotheses() -> None:
    dupe = _hawkish_fed_item()
    r = Researcher({"fed_rss": _StubFedRss([dupe, dupe])})
    hyps = r.scan(ASOF)
    texts = [h.text for h in hyps]
    assert len(texts) == len(set(texts))


def test_hindsight_retains_one_per_surviving_hypothesis() -> None:
    fake = _FakeHindsight()
    r = Researcher(
        {
            "fed_rss": _StubFedRss([_hawkish_fed_item()]),
            "fedwatch": _StubFedWatch({"+25bps hike": 0.7}),
        },
        hindsight=fake,
    )
    hyps = r.scan(ASOF)
    assert len(fake.retained) == len(hyps)
    assert all(
        meta.get("kind") == "research_hypothesis" for _, meta in fake.retained
    )
    assert all("signal_kind" in meta for _, meta in fake.retained)


def test_hindsight_recall_drops_do_not_repeat() -> None:
    hawkish = _hawkish_fed_item()
    # Build the researcher once to learn the text it would emit.
    plain = Researcher({"fed_rss": _StubFedRss([hawkish])})
    emitted = plain.scan(ASOF)
    assert emitted, "precondition: hawkish item must emit a hypothesis"
    stale_text = emitted[0].text

    fake = _FakeHindsight(recall_texts=[stale_text])
    r = Researcher({"fed_rss": _StubFedRss([hawkish])}, hindsight=fake)
    hyps = r.scan(ASOF)
    assert all(h.text != stale_text for h in hyps)
    # dropped ones are not retained
    assert all(text != stale_text for text, _ in fake.retained)


def test_hindsight_recall_by_hash_drops() -> None:
    """Recall may return hashes rather than full text; those drop too."""
    hawkish = _hawkish_fed_item()
    plain = Researcher({"fed_rss": _StubFedRss([hawkish])})
    stale_text = plain.scan(ASOF)[0].text
    stale_hash = hashlib.sha256(stale_text.encode()).hexdigest()

    fake = _FakeHindsight(recall_texts=[stale_hash])
    r = Researcher({"fed_rss": _StubFedRss([hawkish])}, hindsight=fake)
    assert all(h.text != stale_text for h in r.scan(ASOF))


def test_to_planner_queue_shape() -> None:
    hyps = [
        Hypothesis(
            source="fed_rss",
            text="hawkish stance",
            signal_kind="rate_path",
            confidence=0.6,
        ),
        Hypothesis(
            source="edgar",
            text="material 8-K",
            signal_kind="event",
            confidence=0.5,
        ),
    ]
    queue = to_planner_queue(hyps)
    assert queue == [
        {
            "hypothesis": "hawkish stance",
            "kind": "rate_path",
            "confidence": 0.6,
            "source": "fed_rss",
        },
        {
            "hypothesis": "material 8-K",
            "kind": "event",
            "confidence": 0.5,
            "source": "edgar",
        },
    ]
