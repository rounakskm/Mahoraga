"""NewsClassifier (lexicon backend): urgency levels + sentiment sign, pure-local.

The classifier must never hit the network — `classify()` still returns even when
`httpx.get` is monkeypatched to raise.
"""

from __future__ import annotations

import pandas as pd

from services.trader.news.alpaca_news import NewsItem
from services.trader.news.classifier import Classification, NewsClassifier


def _item(headline: str, summary: str = "", symbols: list[str] | None = None) -> NewsItem:
    return NewsItem(
        id=1,
        created_at=pd.Timestamp("2024-03-04T18:36:04Z"),
        headline=headline,
        summary=summary,
        symbols=symbols if symbols is not None else ["SPY"],
        source="test",
        url="https://example.com",
    )


def test_hawkish_fomc_is_critical_and_negative() -> None:
    item = _item(
        "Fed's Powell Signals Rate Hike As Inflation Runs Hot; Hawkish Tone Sinks Stocks",
        "The FOMC is prepared to raise rates further; equities plunged into the close.",
        symbols=["SPY", "QQQ", "DIA"],
    )
    c = NewsClassifier(backend="lexicon").classify(item)
    assert isinstance(c, Classification)
    assert c.level == "CRITICAL"
    assert c.sentiment < 0
    assert 0.0 <= c.impact <= 1.0
    assert -1.0 <= c.sentiment <= 1.0


def test_neutral_cfo_appointment_is_background_and_small() -> None:
    item = _item(
        "State Street names new CFO effective next quarter",
        "State Street Corp appointed a new chief financial officer as part of a planned transition.",
        symbols=["SPY", "STT"],
    )
    c = NewsClassifier(backend="lexicon").classify(item)
    assert c.level == "BACKGROUND"
    assert abs(c.sentiment) < 0.5


def test_strong_earnings_beat_is_positive_and_material_or_critical() -> None:
    item = _item(
        "Nvidia Shares Surge After Earnings Beat, Record Revenue And Upgraded Guidance",
        "Nvidia crushed earnings estimates, posted record revenue and raised full-year guidance, rallying.",
        symbols=["SPY", "NVDA"],
    )
    c = NewsClassifier(backend="lexicon").classify(item)
    assert c.sentiment > 0
    assert c.level in {"MATERIAL", "CRITICAL"}


# --- word-boundary trigger matching (review B1) -----------------------------


def test_award_headline_is_not_critical() -> None:
    # "award" must not substring-match the "war" trigger.
    c = NewsClassifier(backend="lexicon").classify(
        _item("Apple wins design award for new hardware")
    )
    assert c.level != "CRITICAL"


def test_warner_bros_is_not_critical() -> None:
    # "Warner" must not substring-match the "war" trigger.
    c = NewsClassifier(backend="lexicon").classify(
        _item("Warner Bros reports quarterly results")
    )
    assert c.level != "CRITICAL"


def test_wary_fed_officials_not_critical_from_war_trigger() -> None:
    # "wary" must not substring-match "war"; no severe trigger fires here.
    c = NewsClassifier(backend="lexicon").classify(
        _item("Fed officials wary of cutting too soon")
    )
    assert c.level != "CRITICAL"
    assert "war" not in c.rationale.split("triggers=")[-1]


def test_actual_war_headline_is_critical() -> None:
    c = NewsClassifier(backend="lexicon").classify(
        _item("Oil spikes as war escalates in the region")
    )
    assert c.level == "CRITICAL"


# --- severity gate: not every trigger is CRITICAL (review B2) ---------------


def test_analyst_downgrade_is_material_not_critical() -> None:
    # A routine single-name downgrade is a weak trigger (< 0.8) -> MATERIAL.
    c = NewsClassifier(backend="lexicon").classify(
        _item("Analyst downgrades small-cap retailer")
    )
    assert c.level == "MATERIAL"


def test_fomc_rate_decision_is_critical() -> None:
    c = NewsClassifier(backend="lexicon").classify(_item("FOMC raises rates 50bp"))
    assert c.level == "CRITICAL"


def test_recall_is_material_not_critical() -> None:
    c = NewsClassifier(backend="lexicon").classify(
        _item("Automaker announces recall of 12,000 vehicles over sensor issue")
    )
    assert c.level == "MATERIAL"


def test_classify_makes_no_network_call(monkeypatch) -> None:
    import httpx

    def _boom(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("classify must not touch the network")

    monkeypatch.setattr(httpx, "get", _boom)
    monkeypatch.setattr(httpx, "post", _boom)
    c = NewsClassifier(backend="lexicon").classify(
        _item("Company plunges after guidance cut and SEC probe")
    )
    assert isinstance(c, Classification)
    assert c.level == "CRITICAL"
