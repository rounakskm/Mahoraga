"""Sentiment feature — real PIT sentiment from classified news, with a
placeholder fallback for the offline / no-key path.

Two classes live here:

- :class:`PlaceholderFeature` — the original Phase-1 column that always returns
  0.0 with ``placeholder=True``. Per Phase-1 plan §3 the backtest harness rejects
  strategies reading placeholder columns unless they opt in, forcing Phase 4 to
  deliver real sentiment. Kept unchanged so the Phase-1 registration + tests stay
  green.
- :class:`SentimentFeature` — the real Phase-4 feature (``placeholder=False``).
  It turns classified news history into a per-bar exponentially-weighted (EW)
  sentiment series.

**Point-in-time correctness (no look-ahead).** For each bar dated ``d`` (from
``ctx.frame["bar_timestamp"]``) with ``d <= ctx.asof``, the value is the EW-decayed
mean of the classified ``sentiment`` of ``ctx.ticker`` news with
``created_at <= d``. News dated after a bar can never change that bar's value —
the news stream is processed in chronological order and each bar simply reads the
running EW state as of the last item at or before it. A no-news bar forward-fills
the previous value; bars before any news are 0.0. Result is float64 in [-1, 1],
aligned to ``ctx.frame.index``.

**Registration seam.** The module keeps registering the ``sentiment_score``
*placeholder* at import time (unchanged), so Phase-1 pipeline tests stay green.
``SentimentFeature`` is instantiated with a live ``news_client`` by callers (the
Phase-4 runner / pipeline in Task 13); when its own ``news_client`` is ``None`` it
degrades to the same 0.0 series as the placeholder, so it is safe to swap in
offline without breaking anything.
"""

from __future__ import annotations

from typing import ClassVar

import pandas as pd

from services.trader.features.base import (
    Feature,
    FeatureContext,
    register_feature,
)
from services.trader.news.classifier import NewsClassifier

# EW smoothing: weight on the newest item. 0.5 keeps the series responsive to
# fresh headlines while retaining a decaying memory of prior sentiment.
_EW_ALPHA = 0.5


class PlaceholderFeature(Feature):
    """Feature that always returns 0.0 with `placeholder=True` metadata flag.

    The Phase 1 sentiment column is the only placeholder. Later phases may
    add others; the `placeholder` flag is the discriminator the backtest
    harness checks.
    """

    category: ClassVar[str] = "sentiment"
    placeholder: ClassVar[bool] = True

    def __init__(self, name: str) -> None:
        self.name = name

    def required_history_bars(self) -> int:
        return 0

    def compute(self, ctx: FeatureContext) -> pd.Series:
        return pd.Series([0.0] * len(ctx.frame), dtype="float64")


class SentimentFeature(Feature):
    """Real PIT sentiment feature: EW-decayed mean of classified news sentiment.

    ``news_client`` is any object exposing ``fetch(symbols, start, end) ->
    list[NewsItem]`` (the Phase-4 ``AlpacaNewsClient``, or a fake in tests). When
    ``news_client is None`` (no API key) the feature falls back to the 0.0
    placeholder series so the offline Phase-1 pipeline keeps working.

    Optionally ``items`` may be injected directly (a pre-fetched news list),
    bypassing the client — convenient for tests and for the integration pipeline
    that fetches once and reuses across features.
    """

    category: ClassVar[str] = "sentiment"
    name: ClassVar[str] = "sentiment_score"
    placeholder: ClassVar[bool] = False

    def __init__(
        self,
        news_client: object | None = None,
        classifier: NewsClassifier | None = None,
        items: list | None = None,
    ) -> None:
        self.news_client = news_client
        self.classifier = classifier or NewsClassifier(backend="lexicon")
        self._items = items

    def required_history_bars(self) -> int:
        return 0

    def compute(self, ctx: FeatureContext) -> pd.Series:
        index = ctx.frame.index
        # Offline / no source configured -> placeholder 0.0 series.
        if self.news_client is None and self._items is None:
            return pd.Series([0.0] * len(ctx.frame), dtype="float64", index=index)

        bar_dates = pd.to_datetime(ctx.frame["bar_timestamp"], utc=True)
        asof = pd.Timestamp(ctx.asof)
        asof = asof.tz_localize("UTC") if asof.tzinfo is None else asof.tz_convert("UTC")

        items = self._gather_items(ctx, bar_dates, asof)
        # (created_at, sentiment) pairs, cut at asof, in chronological order.
        stream: list[tuple[pd.Timestamp, float]] = []
        for item in items:
            created = pd.Timestamp(item.created_at)
            created = (
                created.tz_localize("UTC") if created.tzinfo is None else created.tz_convert("UTC")
            )
            if created > asof:
                continue  # PIT cutoff: news after asof is invisible.
            stream.append((created, float(self.classifier.classify(item).sentiment)))
        stream.sort(key=lambda pair: pair[0])

        # Precompute the running EW value after each item (cumulative, ordered).
        ew_after: list[float] = []
        ew = 0.0
        for i, (_created, sentiment) in enumerate(stream):
            ew = sentiment if i == 0 else _EW_ALPHA * sentiment + (1.0 - _EW_ALPHA) * ew
            ew_after.append(ew)

        created_ats = [c for c, _ in stream]
        values: list[float] = []
        for bar_date in bar_dates:
            if bar_date > asof:
                # Bar beyond asof: no PIT value; forward-fill last known (or 0.0).
                values.append(values[-1] if values else 0.0)
                continue
            # Number of items with created_at <= bar_date (searchsorted, right).
            k = _count_le(created_ats, bar_date)
            values.append(ew_after[k - 1] if k > 0 else 0.0)

        series = pd.Series(values, index=index, dtype="float64")
        return series.clip(-1.0, 1.0)

    def _gather_items(
        self,
        ctx: FeatureContext,
        bar_dates: pd.Series,
        asof: pd.Timestamp,
    ) -> list:
        """Return the raw news items for this ticker (injected list or a fetch)."""
        if self._items is not None:
            return list(self._items)
        start = bar_dates.iloc[0].date().isoformat() if len(bar_dates) else asof.date().isoformat()
        end = asof.date().isoformat()
        return list(self.news_client.fetch([ctx.ticker], start, end))  # type: ignore[union-attr]


def _count_le(sorted_ts: list, cutoff: pd.Timestamp) -> int:
    """Count timestamps in the ascending list that are <= cutoff."""
    lo = 0
    hi = len(sorted_ts)
    while lo < hi:
        mid = (lo + hi) // 2
        if sorted_ts[mid] <= cutoff:
            lo = mid + 1
        else:
            hi = mid
    return lo


# ---------------------------------------------------------------------------
# Registry — single sentiment_score placeholder
# ---------------------------------------------------------------------------
#
# Registration choice: the module-level registry keeps the *placeholder* under
# the name ``sentiment_score`` (unchanged from Phase 1) so the offline default
# pipeline and its Phase-1 tests stay green. The real ``SentimentFeature`` shares
# the same name and is NOT auto-registered here (that would collide with the
# placeholder in ``register_feature``); callers configured with a live news
# client instantiate ``SentimentFeature`` and swap it into their feature list.


_REGISTERED_SENTIMENT = [
    register_feature(PlaceholderFeature("sentiment_score")),
]
"""Side-effect registration; importing this module fills BUILTIN_FEATURES."""
