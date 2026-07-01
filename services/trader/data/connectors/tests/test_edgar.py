"""Tests for the SEC EDGAR 8-K connector.

Parses a committed submissions fixture; no live network.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from services.trader.data.connectors.edgar import EdgarConnector, Filing

FIXTURE = Path(__file__).parent / "fixtures" / "edgar_submissions_sample.json"


def _load() -> dict[str, object]:
    return json.loads(FIXTURE.read_text())


def test_recent_8k_parses_fixture() -> None:
    body = _load()
    connector = EdgarConnector(user_agent="Mahoraga research contact@example.com")
    connector._get = lambda url: body  # type: ignore[method-assign]

    filings = connector.recent_8k("AAPL", since=pd.Timestamp("2026-01-01"))

    assert len(filings) == 1
    filing = filings[0]
    assert isinstance(filing, Filing)
    assert filing.form == "8-K"
    assert filing.cik == "0000320193"
    assert filing.filed_at == pd.Timestamp("2026-05-02")
    assert filing.items == ["2.02", "9.01"]
    assert filing.url.startswith("https://www.sec.gov/Archives/edgar/data/")


def test_since_filter_excludes_older_filings() -> None:
    body = _load()
    connector = EdgarConnector(user_agent="Mahoraga research contact@example.com")
    connector._get = lambda url: body  # type: ignore[method-assign]

    filings = connector.recent_8k("AAPL", since=pd.Timestamp("2026-06-01"))

    assert filings == []


def test_fetch_error_returns_empty() -> None:
    connector = EdgarConnector(user_agent="Mahoraga research contact@example.com")

    def _boom(url: str) -> dict[str, object]:
        raise RuntimeError("network down")

    connector._get = _boom  # type: ignore[method-assign]

    assert connector.recent_8k("AAPL", since=pd.Timestamp("2026-01-01")) == []
