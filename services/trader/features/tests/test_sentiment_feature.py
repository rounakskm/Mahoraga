"""Real PIT ``SentimentFeature`` tests — including the mandatory leak canary.

The feature turns classified news history into a per-bar EW-decayed sentiment
series. It is point-in-time correct: at ``ctx.asof`` a bar dated ``d`` sees only
news with ``created_at <= d`` (and ``d <= ctx.asof``). Future-dated news must
never move a past bar's value — the leak canary asserts exactly that.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from services.trader.features.sentiment import PlaceholderFeature, SentimentFeature
from services.trader.features.tests.conftest import make_ctx, synthetic_ohlcv
from services.trader.news.alpaca_news import NewsItem


class _FakeNewsClient:
    """Injected news source returning a fixed list of ``NewsItem``s."""

    def __init__(self, items: list[NewsItem]) -> None:
        self._items = items
        self.calls: list[tuple[str, str, str]] = []

    def fetch(self, symbols, start, end, limit: int = 50) -> list[NewsItem]:  # type: ignore[no-untyped-def]
        self.calls.append((",".join(symbols), start, end))
        return list(self._items)


def _item(item_id: int, when: datetime, headline: str, summary: str = "") -> NewsItem:
    ts = pd.Timestamp(when)
    created = ts.tz_convert("UTC") if ts.tzinfo else ts.tz_localize("UTC")
    return NewsItem(
        id=item_id,
        created_at=created,
        headline=headline,
        summary=summary,
        symbols=["TST"],
        source="test",
        url="",
    )


def _news_across_frame(df: pd.DataFrame) -> list[NewsItem]:
    """Positive item early, strong-negative item mid-frame — so the series
    varies over time (rises, then falls)."""
    ts = df["bar_timestamp"]
    early = ts.iloc[5].to_pydatetime()
    mid = ts.iloc[25].to_pydatetime()
    return [
        _item(1, early, "Company reports record profit and strong beat, raises guidance"),
        _item(
            2,
            mid,
            "SEC probe: company faces bankruptcy risk after guidance cut and fraud",
            "shares halted",
        ),
    ]


class TestSentimentFeatureMetadata:
    def test_metadata(self) -> None:
        feat = SentimentFeature()
        assert feat.name == "sentiment_score"
        assert feat.category == "sentiment"
        assert feat.placeholder is False


class TestSentimentFeatureCompute:
    def test_series_in_range_and_varies(self) -> None:
        df = synthetic_ohlcv(bars=40)
        client = _FakeNewsClient(_news_across_frame(df))
        feat = SentimentFeature(news_client=client)
        ctx = make_ctx(df, asof=df["bar_timestamp"].iloc[-1].to_pydatetime())

        series = feat.compute(ctx)

        assert len(series) == len(df)
        assert list(series.index) == list(df.index)
        assert str(series.dtype) == "float64"
        assert ((series >= -1.0) & (series <= 1.0)).all()
        # A positive item then a strong-negative item => the series must move.
        assert series.nunique() > 1
        # Before any news the value is 0.0; after the positive item it is > 0.
        assert series.iloc[0] == 0.0
        assert series.iloc[10] > 0.0
        # After the strong-negative item the running EW mean is pulled down.
        assert series.iloc[-1] < series.iloc[10]

    def test_no_news_before_first_item_is_zero_then_ffill(self) -> None:
        df = synthetic_ohlcv(bars=40)
        client = _FakeNewsClient(_news_across_frame(df))
        feat = SentimentFeature(news_client=client)
        ctx = make_ctx(df, asof=df["bar_timestamp"].iloc[-1].to_pydatetime())

        series = feat.compute(ctx)
        # Bars 0..4 precede the first item (dated at bar 5) -> forward-filled 0.0.
        assert (series.iloc[:5] == 0.0).all()
        # A no-news bar carries the previous bar's value (forward fill).
        assert series.iloc[15] == series.iloc[10]

    def test_asof_cutoff_excludes_future_news(self) -> None:
        df = synthetic_ohlcv(bars=40)
        client = _FakeNewsClient(_news_across_frame(df))
        feat = SentimentFeature(news_client=client)
        # asof BEFORE the negative item (bar 25) -> negative item is invisible.
        asof = df["bar_timestamp"].iloc[20].to_pydatetime()
        ctx = make_ctx(df, asof=asof)

        series = feat.compute(ctx)
        # Bars <= asof reflect only the positive item -> stays >= 0.
        computed = series[df["bar_timestamp"] <= pd.Timestamp(asof)]
        assert (computed >= 0.0).all()

    def test_leak_canary_future_news_cannot_change_the_past(self) -> None:
        df = synthetic_ohlcv(bars=40)
        base_items = _news_across_frame(df)
        client = _FakeNewsClient(base_items)
        feat = SentimentFeature(news_client=client)
        asof = df["bar_timestamp"].iloc[-1].to_pydatetime()
        ctx = make_ctx(df, asof=asof)

        baseline = feat.compute(ctx)

        # Add ONE extreme item dated AFTER bar d=30. Values at every bar <= d
        # must be byte-for-byte identical: the future cannot rewrite the past.
        d = 30
        future_when = df["bar_timestamp"].iloc[d + 3].to_pydatetime()
        leaked = [
            *base_items,
            _item(99, future_when, "catastrophic bankruptcy fraud SEC halt war", "crash"),
        ]
        leaked_client = _FakeNewsClient(leaked)
        leaked_feat = SentimentFeature(news_client=leaked_client)
        with_future = leaked_feat.compute(make_ctx(df, asof=asof))

        pd.testing.assert_series_equal(
            baseline.iloc[: d + 1],
            with_future.iloc[: d + 1],
            check_names=False,
        )


class TestSentimentFeatureOfflineFallback:
    def test_no_client_is_all_zero(self) -> None:
        df = synthetic_ohlcv(bars=20)
        feat = SentimentFeature(news_client=None)
        ctx = make_ctx(df)
        series = feat.compute(ctx)
        assert len(series) == len(df)
        assert (series == 0.0).all()

    def test_no_client_matches_placeholder(self) -> None:
        df = synthetic_ohlcv(bars=20)
        ctx = make_ctx(df)
        offline = SentimentFeature(news_client=None).compute(ctx).reset_index(drop=True)
        placeholder = PlaceholderFeature("sentiment_score").compute(ctx).reset_index(drop=True)
        pd.testing.assert_series_equal(offline, placeholder, check_names=False)
