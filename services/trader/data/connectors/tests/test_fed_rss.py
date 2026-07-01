"""Tests for the Federal Reserve RSS connector.

Parses a committed RSS fixture with stdlib xml.etree; no live network.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from services.trader.data.connectors.fed_rss import (
    DEFAULT_FEEDS,
    FedItem,
    FedRssConnector,
)

FIXTURE = Path(__file__).parent / "fixtures" / "fed_rss_sample.xml"


def test_latest_parses_fixture() -> None:
    xml = FIXTURE.read_text()
    connector = FedRssConnector()
    connector._get = lambda url: xml  # type: ignore[method-assign]

    items = connector.latest(feeds=[("https://example/feed.xml", "press")])

    assert len(items) == 2
    first = items[0]
    assert isinstance(first, FedItem)
    assert first.title == "Federal Reserve issues FOMC statement"
    assert first.kind == "press"
    assert first.url.endswith("monetary20260429a.htm")
    assert first.published == pd.Timestamp("2026-04-29 18:00:00+00:00")


def test_default_feeds_present() -> None:
    assert len(DEFAULT_FEEDS) >= 2
    for url, kind in DEFAULT_FEEDS:
        assert url.startswith("https://www.federalreserve.gov/")
        assert isinstance(kind, str)


def test_fetch_error_returns_empty() -> None:
    connector = FedRssConnector()

    def _boom(url: str) -> str:
        raise RuntimeError("network down")

    connector._get = _boom  # type: ignore[method-assign]

    assert connector.latest(feeds=[("https://example/feed.xml", "press")]) == []
