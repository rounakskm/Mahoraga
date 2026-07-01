"""AlpacaNewsClient — real news archive (REST) + live stream (websocket) client.

Mirrors the `ProvenanceWriter(None)` graceful-offline pattern: with no API key the
client is *disabled* — `is_enabled()` is False and `fetch()` returns `[]` without any
network call. The REST transport lives in an overridable `_get(path, params)` so unit
tests inject fixtures instead of hitting `data.alpaca.markets`.

Alpaca `/v1beta1/news` response shape:
    {"news": [ {id, author, created_at, updated_at, headline, summary, source,
                symbols, url, images}, ... ], "next_page_token": "..."|null}
Auth via `APCA-API-KEY-ID` / `APCA-API-SECRET-KEY` headers; pagination via
`next_page_token` echoed back as the `page_token` param.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

import pandas as pd

_NEWS_PATH = "/v1beta1/news"


@dataclass(frozen=True)
class NewsItem:
    """One classified-ready news article. `created_at` is tz-aware UTC."""

    id: int
    created_at: pd.Timestamp
    headline: str
    summary: str
    symbols: list[str]
    source: str
    url: str


class AlpacaNewsClient:
    """Alpaca news archive + stream client. No key -> disabled, safe no-op."""

    def __init__(
        self,
        key: str | None = None,
        secret: str | None = None,
        data_url: str = "https://data.alpaca.markets",
    ) -> None:
        self.key = key
        self.secret = secret
        self.data_url = data_url.rstrip("/")

    def is_enabled(self) -> bool:
        return bool(self.key and self.secret)

    def fetch(
        self,
        symbols: Sequence[str],
        start: str,
        end: str,
        limit: int = 50,
    ) -> list[NewsItem]:
        """Fetch the news archive for `symbols` in [start, end], paginating fully.

        Disabled (no-key) clients short-circuit to `[]` before any network call.
        """
        if not self.is_enabled():
            return []
        params: dict[str, object] = {
            "symbols": ",".join(symbols),
            "start": start,
            "end": end,
            "limit": limit,
        }
        items: list[NewsItem] = []
        page_token: str | None = None
        while True:
            if page_token:
                params["page_token"] = page_token
            payload = self._get(_NEWS_PATH, params)
            items.extend(self._parse_news(payload))
            page_token = payload.get("next_page_token")
            if not page_token:
                break
        return items

    def _get(self, path: str, params: dict) -> dict:
        """REST transport (overridable in tests). Lazy httpx import."""
        import httpx  # noqa: PLC0415 (lazy: only on a real network call)

        resp = httpx.get(
            f"{self.data_url}{path}",
            headers={
                "APCA-API-KEY-ID": self.key or "",
                "APCA-API-SECRET-KEY": self.secret or "",
            },
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _parse_news(payload: dict) -> list[NewsItem]:
        """Map an Alpaca `/v1beta1/news` payload to `NewsItem`s (tz-aware UTC)."""
        out: list[NewsItem] = []
        for raw in payload.get("news", []):
            created = pd.Timestamp(raw["created_at"])
            created = created.tz_localize("UTC") if created.tzinfo is None else created.tz_convert("UTC")
            out.append(
                NewsItem(
                    id=int(raw["id"]),
                    created_at=created,
                    headline=raw.get("headline", ""),
                    summary=raw.get("summary", ""),
                    symbols=list(raw.get("symbols", [])),
                    source=raw.get("source", ""),
                    url=raw.get("url", ""),
                )
            )
        return out

    def stream(
        self,
        symbols: Sequence[str],
        on_item: Callable[[NewsItem], None],
    ) -> None:
        """Open the live news websocket, invoking `on_item` per article.

        Stub: disabled clients return immediately. The websocket loop (auth,
        subscribe, reconnect + polling fallback) uses a lazy websockets/httpx
        import and is not exercised in unit tests.
        """
        if not self.is_enabled():
            return
        raise NotImplementedError("live news stream is wired in a later Phase-4 step")
