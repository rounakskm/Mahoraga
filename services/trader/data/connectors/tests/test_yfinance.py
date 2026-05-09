"""Tests for the YFinanceConnector.

All tests use an injected fake downloader so we never hit the real Yahoo
endpoint from CI.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

import pandas as pd
import pytest

from services.trader.data.connectors.base import ConnectorError, RateLimiter
from services.trader.data.connectors.yfinance import (
    YFinanceConnector,
    _PermanentError,
    _RetryConfig,
    _TransientError,
)


def _fake_yfinance_frame(rows: int = 3) -> pd.DataFrame:
    idx = pd.date_range("2026-01-02", periods=rows, freq="B", tz="UTC")
    return pd.DataFrame(
        {
            "Open":      [100.0 + i for i in range(rows)],
            "High":      [101.0 + i for i in range(rows)],
            "Low":       [ 99.0 + i for i in range(rows)],
            "Close":     [100.5 + i for i in range(rows)],
            "Adj Close": [100.4 + i for i in range(rows)],
            "Volume":    [1_000_000 + i for i in range(rows)],
        },
        index=idx,
    )


def _make_connector(
    *,
    downloader: Callable[..., pd.DataFrame],
    sleep: Callable[[float], None] | None = None,
    max_attempts: int = 3,
) -> YFinanceConnector:
    return YFinanceConnector(
        rate_limiter=RateLimiter(capacity=10.0, refill_rate_per_sec=100.0),
        downloader=downloader,
        retry_config=_RetryConfig(max_attempts=max_attempts, base_backoff_sec=0.001, backoff_cap_sec=0.01),
        sleep=sleep or (lambda _s: None),
    )


class TestFetchHappyPath:
    def test_returns_normalized_frame(self) -> None:
        def fake(**_kwargs: object) -> pd.DataFrame:
            return _fake_yfinance_frame()

        c = _make_connector(downloader=fake)
        result = c.fetch("SPY", date(2026, 1, 2), date(2026, 1, 6))
        assert result.source == "yfinance"
        assert result.rows == 3
        df = result.frame
        assert list(df.columns) == [
            "ticker", "bar_timestamp",
            "open", "high", "low", "close", "volume", "adj_close",
            "source", "fetched_at", "revision_at",
        ]
        assert (df["ticker"] == "SPY").all()
        assert (df["source"] == "yfinance").all()
        assert df["revision_at"].isna().all()

    def test_handles_multi_index_columns(self) -> None:
        def fake(**_kwargs: object) -> pd.DataFrame:
            base = _fake_yfinance_frame()
            base.columns = pd.MultiIndex.from_product([base.columns, ["SPY"]])
            return base

        c = _make_connector(downloader=fake)
        result = c.fetch("SPY", date(2026, 1, 2), date(2026, 1, 6))
        assert result.rows == 3

    def test_falls_back_to_close_when_adj_close_missing(self) -> None:
        def fake(**_kwargs: object) -> pd.DataFrame:
            df = _fake_yfinance_frame()
            return df.drop(columns=["Adj Close"])

        c = _make_connector(downloader=fake)
        result = c.fetch("XYZ", date(2026, 1, 2), date(2026, 1, 6))
        assert (result.frame["adj_close"] == result.frame["close"]).all()


class TestFetchErrors:
    def test_rejects_invalid_ticker(self) -> None:
        c = _make_connector(downloader=lambda **_k: _fake_yfinance_frame())
        with pytest.raises(ConnectorError, match="invalid ticker"):
            c.fetch("", date(2026, 1, 1), date(2026, 1, 5))

    def test_rejects_inverted_window(self) -> None:
        c = _make_connector(downloader=lambda **_k: _fake_yfinance_frame())
        with pytest.raises(ConnectorError, match="after end"):
            c.fetch("SPY", date(2026, 1, 5), date(2026, 1, 2))

    def test_permanent_error_does_not_retry(self) -> None:
        attempts = {"n": 0}

        def fake(**_kwargs: object) -> pd.DataFrame:
            attempts["n"] += 1
            raise _PermanentError("ticker delisted")

        c = _make_connector(downloader=fake)
        with pytest.raises(ConnectorError, match="delisted"):
            c.fetch("ZZZZ", date(2026, 1, 1), date(2026, 1, 5))
        assert attempts["n"] == 1

    def test_missing_columns_raises(self) -> None:
        def fake(**_kwargs: object) -> pd.DataFrame:
            return pd.DataFrame({"Open": [1.0], "High": [2.0]})  # missing Low/Close/Volume

        c = _make_connector(downloader=fake)
        with pytest.raises(ConnectorError, match="missing columns"):
            c.fetch("SPY", date(2026, 1, 2), date(2026, 1, 6))

    def test_empty_frame_raises(self) -> None:
        def fake(**_kwargs: object) -> pd.DataFrame:
            return pd.DataFrame()

        c = _make_connector(downloader=fake)
        with pytest.raises(ConnectorError, match="no rows"):
            c.fetch("SPY", date(2026, 1, 2), date(2026, 1, 6))


class TestFetchRetries:
    def test_transient_error_retries_then_succeeds(self) -> None:
        calls = {"n": 0}
        sleeps: list[float] = []

        def fake(**_kwargs: object) -> pd.DataFrame:
            calls["n"] += 1
            if calls["n"] < 3:
                raise _TransientError(f"http 429 attempt {calls['n']}")
            return _fake_yfinance_frame()

        c = _make_connector(downloader=fake, sleep=sleeps.append, max_attempts=5)
        result = c.fetch("SPY", date(2026, 1, 2), date(2026, 1, 6))
        assert calls["n"] == 3
        assert result.metadata["attempts"] == 3
        assert len(sleeps) == 2  # backed off twice before success

    def test_transient_error_exhausts_attempts(self) -> None:
        calls = {"n": 0}

        def fake(**_kwargs: object) -> pd.DataFrame:
            calls["n"] += 1
            raise _TransientError(f"http 503 attempt {calls['n']}")

        c = _make_connector(downloader=fake, max_attempts=3)
        with pytest.raises(ConnectorError, match="failed after 3 attempts"):
            c.fetch("SPY", date(2026, 1, 2), date(2026, 1, 6))
        assert calls["n"] == 3
