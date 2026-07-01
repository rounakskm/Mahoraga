"""NewsClassifier — fast lexicon backend (default) + optional FinBERT backend.

The lexicon backend is deterministic, pure-local (no network, microseconds), and
meets the <2s fast-path SLA. It scores headline+summary against the signed finance
lexicons in `lexicon.py` and escalates to CRITICAL on urgency triggers. FinBERT is a
pluggable heavy backend that lazily imports `transformers`; if absent, construction
raises a clear error and the caller stays on the lexicon backend.

    sentiment = clip((pos - neg) / max(pos + neg, 1), -1, 1)
    impact    = from max trigger weight + symbol breadth
    level     = CRITICAL on any trigger (or very high impact); else MATERIAL / BACKGROUND
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from services.trader.news.alpaca_news import NewsItem
from services.trader.news.lexicon import NEGATIVE, POSITIVE, URGENCY_TRIGGERS

_WORD_RE = re.compile(r"[a-z']+")


@dataclass(frozen=True)
class Classification:
    """Classifier verdict for one news item."""

    level: str  # CRITICAL | MATERIAL | BACKGROUND
    sentiment: float  # [-1, 1]
    impact: float  # [0, 1]
    rationale: str


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


class LexiconClassifier:
    """Deterministic finance lexicon classifier. Pure local, no network."""

    def classify(self, item: NewsItem) -> Classification:
        text = f"{item.headline} {item.summary}".lower()
        tokens = _WORD_RE.findall(text)

        pos = sum(1 for t in tokens if t in POSITIVE)
        neg = sum(1 for t in tokens if t in NEGATIVE)
        sentiment = _clip((pos - neg) / max(pos + neg, 1), -1.0, 1.0)

        hits = [(phrase, w) for phrase, w in URGENCY_TRIGGERS.items() if phrase in text]
        trigger_weight = max((w for _, w in hits), default=0.0)

        # Impact blends trigger strength with how broadly the item is tagged.
        symbol_breadth = min(len(item.symbols) / 5.0, 1.0)
        impact = _clip(0.75 * trigger_weight + 0.25 * symbol_breadth, 0.0, 1.0)

        if hits or impact >= 0.8:
            level = "CRITICAL"
        elif impact >= 0.4 or abs(sentiment) >= 0.5:
            level = "MATERIAL"
        else:
            level = "BACKGROUND"

        trigger_note = f"triggers={[p for p, _ in hits]}" if hits else "no triggers"
        rationale = f"pos={pos} neg={neg} {trigger_note} symbols={len(item.symbols)}"
        return Classification(level=level, sentiment=sentiment, impact=impact, rationale=rationale)


class FinbertClassifier:
    """Optional FinBERT backend. Lazily imports transformers; raises if absent."""

    def __init__(self, model: str = "ProsusAI/finbert") -> None:
        try:
            from transformers import pipeline  # noqa: PLC0415 (optional heavy dep)
        except ImportError as exc:  # transformers/torch not installed
            raise RuntimeError(
                "FinBERT backend requires 'transformers'; install it or use backend='lexicon'"
            ) from exc
        self._pipe = pipeline("sentiment-analysis", model=model)

    def classify(self, item: NewsItem) -> Classification:
        text = f"{item.headline}. {item.summary}"
        result = self._pipe(text[:512])[0]
        label = str(result["label"]).lower()
        score = float(result["score"])
        sign = 1.0 if label == "positive" else -1.0 if label == "negative" else 0.0
        sentiment = _clip(sign * score, -1.0, 1.0)
        impact = _clip(abs(sentiment), 0.0, 1.0)
        level = "MATERIAL" if impact >= 0.5 else "BACKGROUND"
        return Classification(
            level=level,
            sentiment=sentiment,
            impact=impact,
            rationale=f"finbert label={label} score={score:.3f}",
        )


class NewsClassifier:
    """Front door: selects a backend and delegates `classify`."""

    def __init__(self, backend: str = "lexicon") -> None:
        self.backend = backend
        if backend == "lexicon":
            self._impl: LexiconClassifier | FinbertClassifier = LexiconClassifier()
        elif backend == "finbert":
            self._impl = FinbertClassifier()
        else:
            raise ValueError(f"unknown classifier backend: {backend!r}")

    def classify(self, item: NewsItem) -> Classification:
        return self._impl.classify(item)
