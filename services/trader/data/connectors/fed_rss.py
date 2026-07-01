"""Federal Reserve press-release / speech RSS connector.

Parses the Fed's public RSS feeds with the stdlib `xml.etree.ElementTree`
(no `feedparser` dependency). Each feed is a `(url, kind)` pair; `kind` labels
the resulting `FedItem`s (e.g. "press", "speeches").

Graceful-offline: any fetch or parse error returns `[]`, never raises.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from xml.etree import ElementTree

import httpx
import pandas as pd

logger = logging.getLogger(__name__)

DEFAULT_FEEDS: list[tuple[str, str]] = [
    ("https://www.federalreserve.gov/feeds/press_all.xml", "press"),
    ("https://www.federalreserve.gov/feeds/speeches.xml", "speeches"),
]


@dataclass(frozen=True)
class FedItem:
    """A single Federal Reserve feed entry."""

    title: str
    published: pd.Timestamp
    url: str
    kind: str


class FedRssConnector:
    """Fetches and parses Federal Reserve RSS/Atom feeds."""

    def __init__(self, *, timeout: float = 30.0) -> None:
        self._timeout = timeout

    # --- public ----------------------------------------------------------

    def latest(
        self, feeds: list[tuple[str, str]] = DEFAULT_FEEDS
    ) -> list[FedItem]:
        """Return the entries across `feeds`. Errors on a feed skip it."""
        out: list[FedItem] = []
        for url, kind in feeds:
            try:
                xml = self._get(url)
                out.extend(self._parse_feed(xml, kind))
            except Exception as exc:  # noqa: BLE001 — graceful-offline contract
                logger.warning("Fed RSS fetch/parse failed for %s: %s", url, exc)
                continue
        return out

    # --- transport (overridable in tests) --------------------------------

    def _get(self, url: str) -> str:
        response = httpx.get(url, timeout=self._timeout)
        response.raise_for_status()
        return response.text

    # --- internals -------------------------------------------------------

    def _parse_feed(self, xml: str, kind: str) -> list[FedItem]:
        root = ElementTree.fromstring(xml)
        out: list[FedItem] = []
        # RSS 2.0: channel/item ; Atom: feed/entry.
        for item in root.iter("item"):
            parsed = self._parse_rss_item(item, kind)
            if parsed is not None:
                out.append(parsed)
        return out

    def _parse_rss_item(
        self, item: ElementTree.Element, kind: str
    ) -> FedItem | None:
        title = _text(item, "title")
        link = _text(item, "link")
        pub = _text(item, "pubDate")
        if not title or not pub:
            return None
        published = pd.to_datetime(pub, utc=True)
        return FedItem(title=title, published=published, url=link, kind=kind)


def _text(element: ElementTree.Element, tag: str) -> str:
    child = element.find(tag)
    if child is None or child.text is None:
        return ""
    return child.text.strip()
