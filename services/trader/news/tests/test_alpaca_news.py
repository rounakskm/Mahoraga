"""AlpacaNewsClient: fixture parsing + graceful no-key disabled path. No network —
the fixture stands in for a real `/v1beta1/news` response and the disabled client
must short-circuit before any transport call.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from services.trader.news.alpaca_news import AlpacaNewsClient, NewsItem

_FIXTURE = Path(__file__).parent / "fixtures" / "spy_news_sample.json"


def _payload() -> dict:
    return json.loads(_FIXTURE.read_text())


def test_parse_news_yields_three_items() -> None:
    items = AlpacaNewsClient(None, None)._parse_news(_payload())
    assert len(items) == 3
    assert all(isinstance(it, NewsItem) for it in items)


def test_parsed_created_at_is_tz_aware_utc() -> None:
    items = AlpacaNewsClient(None, None)._parse_news(_payload())
    first = items[0]
    assert isinstance(first.created_at, pd.Timestamp)
    assert first.created_at.tzinfo is not None
    assert str(first.created_at.tz) == "UTC"


def test_parsed_items_carry_spy_symbol_and_fields() -> None:
    items = AlpacaNewsClient(None, None)._parse_news(_payload())
    for it in items:
        assert "SPY" in it.symbols
        assert it.headline
        assert it.source
        assert it.url
    assert items[0].id == 38471002


def test_disabled_client_is_no_op() -> None:
    client = AlpacaNewsClient(None, None)
    assert client.is_enabled() is False
    # fetch must return [] without touching the network (no transport override).
    assert client.fetch(["SPY"], "2024-01-01", "2024-12-31") == []


def test_enabled_client_reports_enabled() -> None:
    assert AlpacaNewsClient("key", "secret").is_enabled() is True


def test_fetch_paginates_via_injected_transport() -> None:
    payload = _payload()
    page1 = {"news": payload["news"][:2], "next_page_token": "tok2"}
    page2 = {"news": payload["news"][2:], "next_page_token": None}
    pages = [page1, page2]
    calls: list[dict] = []

    class _Client(AlpacaNewsClient):
        def _get(self, path: str, params: dict) -> dict:
            calls.append(params)
            return pages[len(calls) - 1]

    client = _Client("key", "secret")
    items = client.fetch(["SPY"], "2024-03-01", "2024-03-05", limit=2)
    assert len(items) == 3
    assert len(calls) == 2
    assert calls[1]["page_token"] == "tok2"
