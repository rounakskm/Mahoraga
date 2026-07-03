"""Calibration regression for the lexicon classifier (review B1/B2).

Pins the word-boundary trigger matching and the CRITICAL severity gate against
two corpora:

- the committed Alpaca fixture (`fixtures/spy_news_sample.json`), where exactly
  the FOMC/rate-hike item is CRITICAL and the routine items are not;
- an embedded ~25-headline benign/mixed corpus (earnings beats, CFO
  appointments, product launches, "warns of headwinds", award wins, Warner
  Bros, Delaware court) whose CRITICAL rate must stay <= 10%.

A regression back to substring triggers ("war" in "award"/"Warner"/"wary") or
to any-trigger-is-CRITICAL blows the rate assertion immediately.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from services.trader.news.alpaca_news import AlpacaNewsClient, NewsItem
from services.trader.news.classifier import NewsClassifier

_FIXTURE = Path(__file__).parent / "fixtures" / "spy_news_sample.json"

# Realistic benign / mixed headlines: none carries a genuinely-severe
# market-moving trigger, so none of them should classify CRITICAL.
_BENIGN_HEADLINES: list[str] = [
    "Apple wins design award for new hardware",
    "Warner Bros reports quarterly results",
    "Delaware court schedules hearing on merger terms",
    "Company appoints new CFO effective next quarter",
    "Retailer warns of headwinds in holiday quarter",
    "Tech firm launches new product line at annual event",
    "Chipmaker beats estimates on strong data-center demand",
    "Board declares quarterly dividend of $0.24 per share",
    "Airline expands routes to three new cities",
    "Fed officials wary of cutting too soon, minutes show",
    "Automaker opens new plant in Tennessee",
    "Software company announces annual developer conference dates",
    "Analyst initiates coverage with a hold rating",
    "Grocery chain tests self-checkout upgrades",
    "Pharma firm completes enrollment in mid-stage trial",
    "Bank names veteran executive to lead wealth unit",
    "Streaming service adds live sports tier",
    "Utility issues green bonds to fund grid upgrades",
    "Restaurant chain reports steady same-store sales",
    "Insurer reaffirms full-year outlook",
    "Homebuilder breaks ground on new community in Arizona",
    "Semiconductor firm extends partnership with automaker",
    "Apparel brand collaborates with designer on capsule collection",
    "Energy company schedules investor day for next month",
    "Logistics provider upgrades delivery fleet with electric vans",
]


def _item(id_: int, headline: str, summary: str = "") -> NewsItem:
    return NewsItem(
        id=id_,
        created_at=pd.Timestamp("2024-03-04T18:36:04Z"),
        headline=headline,
        summary=summary,
        symbols=["SPY"],
        source="test",
        url="https://example.com",
    )


def _fixture_items() -> list[NewsItem]:
    payload = json.loads(_FIXTURE.read_text())
    return AlpacaNewsClient._parse_news(payload)


def test_fixture_corpus_critical_only_for_the_fomc_item() -> None:
    classifier = NewsClassifier(backend="lexicon")
    items = _fixture_items()
    assert items, "fixture must parse to items"
    by_level = {item.headline: classifier.classify(item).level for item in items}

    for headline, level in by_level.items():
        if "Rate Hike" in headline:  # the planted FOMC/hawkish item
            assert level == "CRITICAL"
        else:  # CFO appointment, Nvidia earnings beat: material at most
            assert level != "CRITICAL", headline


def test_benign_corpus_critical_rate_at_most_10_percent() -> None:
    classifier = NewsClassifier(backend="lexicon")
    levels = [
        classifier.classify(_item(i, headline)).level
        for i, headline in enumerate(_BENIGN_HEADLINES, start=1)
    ]
    critical_rate = levels.count("CRITICAL") / len(levels)
    assert critical_rate <= 0.10, f"CRITICAL rate {critical_rate:.0%} over benign corpus"


def test_specific_benign_headlines_are_not_critical() -> None:
    classifier = NewsClassifier(backend="lexicon")
    for headline in (
        "Apple wins design award for new hardware",
        "Warner Bros reports quarterly results",
        "Delaware court schedules hearing on merger terms",
        "Retailer warns of headwinds in holiday quarter",
        "Fed officials wary of cutting too soon, minutes show",
    ):
        level = classifier.classify(_item(99, headline)).level
        assert level != "CRITICAL", headline
