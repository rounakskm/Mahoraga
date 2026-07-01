"""Phase-4 intelligence-layer integration smoke (Task 13).

Drives the full news-intelligence chain end-to-end, fully offline — no network,
no Alpaca key, no Hindsight DSN:

    fixture news -> NewsClassifier -> SentimentAggregator
                 -> SentimentFeature (injected fake source) -> sentiment_score series
    derived features (roc_3/roc_5/volume_surge + a plausible realized_vol_pct_60)
                 -> MicroLens.classify -> a CompositeRegime.micro label
    a planted CRITICAL item -> NewsShockProtocol(isolated HaltControl) -> halt trips

Everything is constructed from the same synthetic OHLCV frame pattern the feature
unit tests use (tz-aware UTC ``bar_timestamp`` + close + volume). The test asserts
no key and no DSN are needed: `AlpacaNewsClient(None, None)` is disabled, and no
Hindsight client is wired anywhere.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from services.trader.features.base import FeatureContext
from services.trader.features.micro import VolumeSurgeFeature
from services.trader.features.momentum import ROC
from services.trader.features.sentiment import SentimentFeature
from services.trader.news.aggregator import SentimentAggregator
from services.trader.news.alpaca_news import AlpacaNewsClient, NewsItem
from services.trader.news.classifier import Classification, NewsClassifier
from services.trader.news.shock import NewsShockProtocol
from services.trader.ops.halt import HaltControl
from services.trader.regime.base import UNDEFINED_LABEL
from services.trader.regime.micro import MicroLens

_MICRO_LABELS = {"momentum", "reversal", "shock", UNDEFINED_LABEL}


class _FakeNewsSource:
    """Injected news source (mirrors the Task-5 sentiment test injection)."""

    def __init__(self, items: list[NewsItem]) -> None:
        self._items = items

    def fetch(self, symbols, start, end, limit: int = 50) -> list[NewsItem]:  # type: ignore[no-untyped-def]
        return list(self._items)


def _synthetic_ohlcv(*, ticker: str = "SPY", bars: int = 40, seed: int = 7) -> pd.DataFrame:
    """A deterministic OHLCV frame with a tz-aware UTC ``bar_timestamp`` column,
    a strong late uptrend + a volume spike so the derived features are non-trivial."""
    rng = np.random.default_rng(seed)
    start = datetime(2024, 1, 2, tzinfo=UTC)
    timestamps = [start + timedelta(days=i) for i in range(bars)]

    # A gentle drift then a strong upward push over the last third — gives roc_3/roc_5
    # a clear positive momentum signal at the tail.
    steps = rng.normal(0.05, 0.4, size=bars)
    steps[-8:] += 1.2
    closes = 100.0 + steps.cumsum()
    highs = closes + rng.uniform(0.3, 1.2, size=bars)
    lows = closes - rng.uniform(0.3, 1.2, size=bars)
    opens = closes - rng.normal(0.0, 0.4, size=bars)
    volumes = rng.integers(900_000, 1_100_000, size=bars).astype("float64")
    volumes[-1] *= 2.6  # a volume surge on the final bar

    return pd.DataFrame(
        {
            "ticker": ticker,
            "bar_timestamp": pd.to_datetime(timestamps, utc=True),
            "open": opens.astype("float64"),
            "high": highs.astype("float64"),
            "low": lows.astype("float64"),
            "close": closes.astype("float64"),
            "volume": volumes,
        }
    )


def _news_items(df: pd.DataFrame, ticker: str) -> list[NewsItem]:
    """A fixed news list dated across the frame: several positive items and one
    clearly-CRITICAL negative headline (an FOMC rate hike + bankruptcy)."""
    ts = df["bar_timestamp"]

    def item(i: int, bar: int, headline: str, summary: str = "") -> NewsItem:
        return NewsItem(
            id=i,
            created_at=ts.iloc[bar],
            headline=headline,
            summary=summary,
            symbols=[ticker],
            source="test",
            url="",
        )

    return [
        item(1, 3, "Company reports record profit and strong beat, raises guidance"),
        item(2, 10, "Analysts upgrade outlook after robust growth and buybacks"),
        item(
            3,
            22,
            "FOMC delivers surprise rate hike; company faces bankruptcy risk and SEC probe",
            "shares halted",
        ),
        item(4, 30, "Firm announces new product line, modest positive reception"),
    ]


def _critical_classification(
    classifier: NewsClassifier, items: list[NewsItem]
) -> tuple[NewsItem, Classification]:
    """Find the planted CRITICAL item + its classification."""
    for it in items:
        cls = classifier.classify(it)
        if cls.level == "CRITICAL":
            return it, cls
    raise AssertionError("expected a CRITICAL item in the fixture news")


class TestIntelPipelineOffline:
    def test_end_to_end_offline_produces_micro_label_and_trips_shock(
        self, tmp_path: Path
    ) -> None:
        ticker = "SPY"
        df = _synthetic_ohlcv(ticker=ticker, bars=40)
        items = _news_items(df, ticker)

        # --- no key / no DSN needed: the Alpaca client is disabled ---
        client = AlpacaNewsClient(None, None)
        assert client.is_enabled() is False
        assert client.fetch([ticker], "2024-01-01", "2024-12-31") == []

        # --- classify + aggregate (no Hindsight) ---
        classifier = NewsClassifier(backend="lexicon")
        aggregator = SentimentAggregator(classifier=classifier, hindsight=None)
        classifications = aggregator.ingest(items)
        assert len(classifications) == len(items)
        asof = df["bar_timestamp"].iloc[-1]
        state = aggregator.state(ticker, asof)
        assert -1.0 <= state.score <= 1.0

        # --- sentiment feature over the frame via an injected fake source ---
        feat = SentimentFeature(news_client=_FakeNewsSource(items), classifier=classifier)
        ctx = FeatureContext(
            ticker=ticker,
            frame=df.reset_index(drop=True),
            asof=asof.to_pydatetime(),
            macro_fetcher=None,
        )
        sentiment = feat.compute(ctx)
        assert len(sentiment) == len(df)
        assert ((sentiment >= -1.0) & (sentiment <= 1.0)).all()
        assert sentiment.nunique() > 1  # varies over time

        # --- derived MICRO features from the frame ---
        roc_3 = ROC(3).compute(ctx)
        roc_5 = ROC(5).compute(ctx)
        volume_surge = VolumeSurgeFeature(window=20).compute(ctx)

        feature_row = pd.Series(
            {
                "sentiment_score": float(sentiment.iloc[-1]),
                "roc_3": float(roc_3.iloc[-1]),
                "roc_5": float(roc_5.iloc[-1]),
                "volume_surge": float(volume_surge.iloc[-1]),
                "realized_vol_pct_60": 55.0,  # plausible percentile constant
            }
        )

        result = MicroLens().classify(feature_row=feature_row, macro_row=None)
        assert result.label in _MICRO_LABELS
        assert 0.0 <= result.confidence <= 1.0

        # --- planted CRITICAL item trips an isolated kill-switch ---
        halt = HaltControl(tmp_path / "halt.flag")
        assert halt.is_halted() is False
        crit_item, crit_cls = _critical_classification(classifier, items)
        shock = NewsShockProtocol(halt, hold_minutes=10)
        action = shock.on_classified(crit_cls, crit_item.headline, asof)
        assert action.halted is True
        assert action.tightened_stops is True
        assert action.hold_until == asof + pd.Timedelta(minutes=10)
        assert halt.is_halted() is True
        reason = halt.reason()
        assert reason and "news shock" in reason
