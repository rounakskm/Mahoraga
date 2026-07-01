"""SentimentAggregator — weighted rolling sentiment state + Hindsight World Facts.

Ingests classified news into per-symbol history, then answers two questions:

- `.state(symbol, asof)` — a single weighted sentiment score blending three
  trailing windows (24h/7d/30d) of item sentiment visible at `asof`, plus the
  count `n` of items within 30d. Point-in-time: only items with
  `created_at <= asof` are considered (no look-ahead).
- `.rolling_series(symbol, items, freq)` — classified sentiments resampled onto
  a forward-filled 15-min grid for the sentiment feature.

MATERIAL/CRITICAL items are retained to Hindsight as World Facts on ingest;
BACKGROUND items are not. `hindsight=None` -> no retain, state still computed.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from services.trader.news.alpaca_news import NewsItem
from services.trader.news.classifier import Classification, NewsClassifier
from services.trader.training.hindsight_client import HindsightClient

# Trailing-window weights: nearer news dominates, but a month of context still counts.
_WINDOWS: dict[str, pd.Timedelta] = {
    "24h": pd.Timedelta(hours=24),
    "7d": pd.Timedelta(days=7),
    "30d": pd.Timedelta(days=30),
}
_WEIGHTS: dict[str, float] = {"24h": 0.5, "7d": 0.3, "30d": 0.2}
_RETAIN_LEVELS = frozenset({"MATERIAL", "CRITICAL"})


@dataclass(frozen=True)
class SentimentState:
    """Weighted rolling sentiment for one symbol at a point in time."""

    symbol: str
    score: float  # [-1, 1]
    n: int  # item count within the 30d window
    asof: pd.Timestamp
    windows: dict[str, float]  # per-window sub-score, each in [-1, 1]


class SentimentAggregator:
    """Classifies news, retains World Facts, and serves rolling sentiment state."""

    def __init__(
        self,
        classifier: NewsClassifier | None = None,
        hindsight: HindsightClient | None = None,
    ) -> None:
        self.classifier = classifier or NewsClassifier()
        self.hindsight = hindsight
        self._history: list[tuple[NewsItem, Classification]] = []

    def ingest(self, items: list[NewsItem]) -> list[Classification]:
        """Classify each item, retain MATERIAL/CRITICAL as World Facts, store history."""
        classifications: list[Classification] = []
        for item in items:
            classification = self.classifier.classify(item)
            classifications.append(classification)
            self._history.append((item, classification))
            if self.hindsight is not None and classification.level in _RETAIN_LEVELS:
                self._retain(item, classification)
        return classifications

    def state(self, symbol: str, asof: pd.Timestamp) -> SentimentState:
        """Weighted 24h/7d/30d rolling sentiment for `symbol` visible at `asof`."""
        asof = pd.Timestamp(asof)
        visible = [
            (item, cls)
            for item, cls in self._history
            if symbol in item.symbols and item.created_at <= asof
        ]

        windows: dict[str, float] = {}
        for label, span in _WINDOWS.items():
            cutoff = asof - span
            sentiments = [cls.sentiment for item, cls in visible if item.created_at >= cutoff]
            windows[label] = float(sum(sentiments) / len(sentiments)) if sentiments else 0.0

        n = sum(1 for item, _ in visible if item.created_at >= asof - _WINDOWS["30d"])
        score = _clip(sum(_WEIGHTS[label] * sub for label, sub in windows.items()), -1.0, 1.0)
        return SentimentState(symbol=symbol, score=score, n=n, asof=asof, windows=windows)

    def rolling_series(
        self,
        symbol: str,
        items: list[NewsItem],
        freq: str = "15min",
    ) -> pd.Series:
        """Classified sentiments for `symbol` resampled onto a forward-filled grid."""
        rows = [
            (item.created_at, self.classifier.classify(item).sentiment)
            for item in items
            if symbol in item.symbols
        ]
        if not rows:
            return pd.Series(dtype="float64")
        rows.sort(key=lambda r: r[0])
        index = pd.DatetimeIndex([ts for ts, _ in rows])
        raw = pd.Series([s for _, s in rows], index=index)
        # Mean-per-bucket, then a continuous forward-filled 15-min grid.
        return raw.resample(freq).mean().ffill()

    def _retain(self, item: NewsItem, classification: Classification) -> None:
        ticker = item.symbols[0] if item.symbols else ""
        text = f"[{classification.level}] {item.headline}"
        metadata = {
            "ticker": ticker,
            "classification": classification.level,
            "sentiment": classification.sentiment,
            "source": item.source,
            "ts": item.created_at.isoformat(),
        }
        self.hindsight.retain(text, metadata=metadata)  # type: ignore[union-attr]


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))
