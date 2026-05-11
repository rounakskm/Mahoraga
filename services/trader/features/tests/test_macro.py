"""Macro-feature tests with synthetic fixtures.

These features rely on `ctx.macro_fetcher` and `ctx.ohlcv_fetcher` to pull
PIT-correct macro and cross-ticker OHLCV. We inject closure-based fakes
rather than hitting Postgres so the suite stays in the unit-tests CI job.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from services.trader.features.base import FeatureContext
from services.trader.features.macro import (
    DXY_SERIES_ID,
    QQQ_TICKER,
    SPY_TICKER,
    TREASURY_2Y_SERIES_ID,
    TREASURY_10Y_SERIES_ID,
    VIX_SERIES_ID,
    DXYChange20D,
    DXYLevel,
    SpyQqqRS20D,
    VIXChange5D,
    VIXLevel,
    VIXRegime,
    Yield2s10s,
    YieldCurveRegime,
)

# ---------------------------------------------------------------------------
# fixture helpers
# ---------------------------------------------------------------------------


def _bars(n: int = 40, start_date: date = date(2024, 1, 5)) -> pd.DataFrame:
    """Build the OHLCV frame the FeatureContext expects (only bar_timestamp matters)."""
    ts = [datetime.combine(start_date + timedelta(days=i), datetime.min.time(), tzinfo=UTC) for i in range(n)]
    return pd.DataFrame(
        {
            "ticker":        "TST",
            "bar_timestamp": pd.to_datetime(ts, utc=True),
            "open":          [100.0] * n,
            "high":          [101.0] * n,
            "low":           [99.0] * n,
            "close":         [100.0] * n,
            "volume":        [1_000_000] * n,
            "adj_close":     [100.0] * n,
            "source":        "test",
            "fetched_at":    pd.to_datetime(ts, utc=True),
            "revision_at":   pd.NaT,
        }
    )


def _macro_frame(
    indicator: str,
    *,
    values: list[float],
    start_release: date,
) -> pd.DataFrame:
    """Macro frame with daily release dates and one value each.

    `as_of_release_date == reference_date` (typical for VIX, treasury yields).
    """
    n = len(values)
    return pd.DataFrame(
        {
            "indicator":          indicator,
            "reference_date":     [start_release + timedelta(days=i) for i in range(n)],
            "as_of_release_date": [start_release + timedelta(days=i) for i in range(n)],
            "value":              values,
            "unit":               "Pct" if indicator != VIX_SERIES_ID else "Index",
            "source":             "test",
            "fetched_at":         pd.Timestamp(datetime(2024, 6, 1, tzinfo=UTC)),
        }
    )


def _macro_fetcher(*frames: tuple[str, pd.DataFrame]):  # type: ignore[no-untyped-def]
    """Build a fetcher that returns canned macro frames by series_id."""
    by_id = {name: df for name, df in frames}

    def fetcher(series_id: str) -> pd.DataFrame:
        return by_id.get(series_id, pd.DataFrame())

    return fetcher


def _ohlcv_frame(ticker: str, *, dates: pd.DatetimeIndex, closes: np.ndarray) -> pd.DataFrame:
    fetched = datetime(2024, 6, 1, tzinfo=UTC)
    return pd.DataFrame(
        {
            "ticker":        ticker,
            "bar_timestamp": dates,
            "open":          closes,
            "high":          closes + 1.0,
            "low":           closes - 1.0,
            "close":         closes,
            "volume":        [1_000_000] * len(dates),
            "adj_close":     closes,
            "source":        "test",
            "fetched_at":    fetched,
            "revision_at":   pd.NaT,
        }
    )


def _ohlcv_fetcher(*frames: tuple[str, pd.DataFrame]):  # type: ignore[no-untyped-def]
    by_ticker = {t: df for t, df in frames}

    def fetcher(ticker: str) -> pd.DataFrame:
        return by_ticker.get(ticker, pd.DataFrame())

    return fetcher


def _ctx(
    bars_df: pd.DataFrame,
    *,
    macro_fetcher=None,  # type: ignore[no-untyped-def]
    ohlcv_fetcher=None,  # type: ignore[no-untyped-def]
) -> FeatureContext:
    asof = bars_df["bar_timestamp"].max() + pd.Timedelta(days=1)
    return FeatureContext(
        ticker="TST",
        frame=bars_df,
        asof=asof.to_pydatetime(),
        macro_fetcher=macro_fetcher,
        ohlcv_fetcher=ohlcv_fetcher,
    )


# ---------------------------------------------------------------------------
# Missing fetcher
# ---------------------------------------------------------------------------


class TestMissingFetcher:
    def test_vix_level_returns_nan_when_no_macro_fetcher(self) -> None:
        ctx = _ctx(_bars(n=10), macro_fetcher=None)
        out = VIXLevel().compute(ctx).reset_index(drop=True)
        assert out.isna().all()

    def test_spy_qqq_returns_nan_when_no_ohlcv_fetcher(self) -> None:
        ctx = _ctx(_bars(n=30), ohlcv_fetcher=None)
        out = SpyQqqRS20D().compute(ctx).reset_index(drop=True)
        assert out.isna().all()


# ---------------------------------------------------------------------------
# VIX
# ---------------------------------------------------------------------------


class TestVIX:
    def test_vix_level_joins_to_bars(self) -> None:
        bars = _bars(n=10, start_date=date(2024, 3, 1))
        macro = _macro_frame(
            VIX_SERIES_ID,
            values=[15.0 + i for i in range(10)],
            start_release=date(2024, 3, 1),
        )
        ctx = _ctx(bars, macro_fetcher=_macro_fetcher((VIX_SERIES_ID, macro)))
        out = VIXLevel().compute(ctx).reset_index(drop=True)
        assert out.tolist() == pytest.approx([15.0 + i for i in range(10)])

    def test_vix_pit_uses_latest_release_at_or_before_bar(self) -> None:
        # Bars at Mar 1, 2, 3 …; macro releases on Mar 1 + Mar 4 only.
        bars = _bars(n=6, start_date=date(2024, 3, 1))
        macro = pd.DataFrame(
            {
                "indicator":          VIX_SERIES_ID,
                "reference_date":     [date(2024, 3, 1), date(2024, 3, 4)],
                "as_of_release_date": [date(2024, 3, 1), date(2024, 3, 4)],
                "value":              [15.0, 18.0],
                "unit":               "Index",
                "source":             "test",
                "fetched_at":         pd.Timestamp(datetime(2024, 6, 1, tzinfo=UTC)),
            }
        )
        ctx = _ctx(bars, macro_fetcher=_macro_fetcher((VIX_SERIES_ID, macro)))
        out = VIXLevel().compute(ctx).reset_index(drop=True)
        # Mar 1-3 see only the Mar 1 release (15); Mar 4-6 see the new release (18)
        assert out.tolist() == [15.0, 15.0, 15.0, 18.0, 18.0, 18.0]

    def test_vix_change_5d(self) -> None:
        bars = _bars(n=10, start_date=date(2024, 3, 1))
        macro = _macro_frame(
            VIX_SERIES_ID,
            values=[10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0, 19.0],
            start_release=date(2024, 3, 1),
        )
        ctx = _ctx(bars, macro_fetcher=_macro_fetcher((VIX_SERIES_ID, macro)))
        out = VIXChange5D().compute(ctx).reset_index(drop=True)
        # change[5] = vix[5]-vix[0] = 15-10 = 5; index 6 = 16-11 = 5, etc.
        assert pd.isna(out.iloc[4])
        assert (out.iloc[5:] == 5.0).all()

    def test_vix_regime_thresholds(self) -> None:
        bars = _bars(n=4, start_date=date(2024, 3, 1))
        macro = _macro_frame(
            VIX_SERIES_ID,
            values=[10.0, 18.0, 30.0, 45.0],
            start_release=date(2024, 3, 1),
        )
        ctx = _ctx(bars, macro_fetcher=_macro_fetcher((VIX_SERIES_ID, macro)))
        out = VIXRegime().compute(ctx).reset_index(drop=True)
        assert out.tolist() == [0.0, 1.0, 2.0, 3.0]


# ---------------------------------------------------------------------------
# Yields
# ---------------------------------------------------------------------------


class TestYields:
    def _yield_ctx(self) -> FeatureContext:
        start = date(2024, 3, 1)
        bars = _bars(n=5, start_date=start)
        y2 = _macro_frame(
            TREASURY_2Y_SERIES_ID,
            values=[4.0, 4.1, 4.2, 4.3, 4.4],
            start_release=start,
        )
        y10 = _macro_frame(
            TREASURY_10Y_SERIES_ID,
            values=[4.5, 4.5, 4.5, 4.5, 4.5],
            start_release=start,
        )
        return _ctx(
            bars,
            macro_fetcher=_macro_fetcher(
                (TREASURY_2Y_SERIES_ID, y2),
                (TREASURY_10Y_SERIES_ID, y10),
            ),
        )

    def test_yield_2s10s_slope(self) -> None:
        ctx = self._yield_ctx()
        out = Yield2s10s().compute(ctx).reset_index(drop=True)
        # 10y - 2y per bar: [0.5, 0.4, 0.3, 0.2, 0.1]
        assert out.tolist() == pytest.approx([0.5, 0.4, 0.3, 0.2, 0.1])

    def test_yield_curve_regime(self) -> None:
        start = date(2024, 3, 1)
        bars = _bars(n=4, start_date=start)
        y2 = _macro_frame(
            TREASURY_2Y_SERIES_ID,
            values=[3.0, 4.0, 4.5, 5.0],
            start_release=start,
        )
        y10 = _macro_frame(
            TREASURY_10Y_SERIES_ID,
            values=[4.5, 4.3, 4.5, 4.5],
            start_release=start,
        )
        ctx = _ctx(
            bars,
            macro_fetcher=_macro_fetcher(
                (TREASURY_2Y_SERIES_ID, y2),
                (TREASURY_10Y_SERIES_ID, y10),
            ),
        )
        out = YieldCurveRegime().compute(ctx).reset_index(drop=True)
        # bar 0: slope = 1.5 → normal (0)
        # bar 1: slope = 0.3 → flat (1)
        # bar 2: slope = 0.0 → flat (1)
        # bar 3: slope = -0.5 → inverted (2)
        assert out.tolist() == [0.0, 1.0, 1.0, 2.0]


# ---------------------------------------------------------------------------
# DXY
# ---------------------------------------------------------------------------


class TestDXY:
    def test_dxy_level_join(self) -> None:
        bars = _bars(n=5, start_date=date(2024, 3, 1))
        dxy = _macro_frame(
            DXY_SERIES_ID,
            values=[100.0, 101.0, 102.0, 103.0, 104.0],
            start_release=date(2024, 3, 1),
        )
        ctx = _ctx(bars, macro_fetcher=_macro_fetcher((DXY_SERIES_ID, dxy)))
        out = DXYLevel().compute(ctx).reset_index(drop=True)
        assert out.tolist() == [100.0, 101.0, 102.0, 103.0, 104.0]

    def test_dxy_change_20d(self) -> None:
        bars = _bars(n=25, start_date=date(2024, 3, 1))
        # DXY goes from 100 to 100+24*0.1 = 102.4
        dxy = _macro_frame(
            DXY_SERIES_ID,
            values=[100.0 + i * 0.1 for i in range(25)],
            start_release=date(2024, 3, 1),
        )
        ctx = _ctx(bars, macro_fetcher=_macro_fetcher((DXY_SERIES_ID, dxy)))
        out = DXYChange20D().compute(ctx).reset_index(drop=True)
        # bar 20: dxy[20]=102, dxy[0]=100, change = (102-100)/100 = 0.02
        assert pd.isna(out.iloc[19])
        assert out.iloc[20] == pytest.approx(0.02, abs=1e-9)


# ---------------------------------------------------------------------------
# SPY/QQQ relative strength
# ---------------------------------------------------------------------------


class TestSpyQqqRS:
    def test_constant_ratio_unity_after_warmup(self) -> None:
        bars = _bars(n=30, start_date=date(2024, 3, 1))
        # Both SPY and QQQ grow by 0.1/bar starting at 100 → ratio constant → RS = 1
        dates = pd.to_datetime(bars["bar_timestamp"], utc=True)
        spy = _ohlcv_frame(SPY_TICKER, dates=dates, closes=np.array([100.0 + i for i in range(30)]))
        qqq = _ohlcv_frame(QQQ_TICKER, dates=dates, closes=np.array([100.0 + i for i in range(30)]))
        ctx = _ctx(bars, ohlcv_fetcher=_ohlcv_fetcher((SPY_TICKER, spy), (QQQ_TICKER, qqq)))
        out = SpyQqqRS20D().compute(ctx).reset_index(drop=True)
        # Bars 0-19 are NaN; bar 20 onward: ratio stays equal (both same growth) so RS = 1.0
        non_null = out.iloc[20:].dropna()
        assert len(non_null) > 0
        assert (non_null.sub(1.0).abs() < 1e-9).all()

    def test_qqq_outpaces_spy_rs_above_one(self) -> None:
        bars = _bars(n=30, start_date=date(2024, 3, 1))
        dates = pd.to_datetime(bars["bar_timestamp"], utc=True)
        spy = _ohlcv_frame(SPY_TICKER, dates=dates, closes=np.array([100.0] * 30))
        qqq = _ohlcv_frame(QQQ_TICKER, dates=dates, closes=np.array([100.0 + i * 0.5 for i in range(30)]))
        ctx = _ctx(bars, ohlcv_fetcher=_ohlcv_fetcher((SPY_TICKER, spy), (QQQ_TICKER, qqq)))
        out = SpyQqqRS20D().compute(ctx).reset_index(drop=True)
        # Bar 20: (qqq[20]/spy[20]) / (qqq[0]/spy[0]) = 1.1 / 1.0 = 1.1
        assert out.iloc[20] == pytest.approx(1.1, abs=1e-9)
