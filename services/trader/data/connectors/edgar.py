"""SEC EDGAR recent-8-K connector.

Pulls a company's recent filings from the SEC submissions API
(`data.sec.gov/submissions/CIK##########.json`) and filters to material-event
8-K filings on or after a cutoff date.

The SEC requires a descriptive `User-Agent` on every request
(https://www.sec.gov/os/webmaster-faq#developers). Callers must pass one.

Graceful-offline: any fetch or parse error returns `[]`, never raises.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx
import pandas as pd

logger = logging.getLogger(__name__)

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data"

# A minimal ticker→CIK map for the symbols Mahoraga trades. The full universe is
# resolvable via https://www.sec.gov/files/company_tickers.json; kept small here
# to avoid a network dependency at import time.
TICKER_TO_CIK: dict[str, int] = {
    "AAPL": 320193,
    "MSFT": 789019,
    "AMZN": 1018724,
    "GOOGL": 1652044,
    "NVDA": 1045810,
    "SPY": 884394,
}


@dataclass(frozen=True)
class Filing:
    """A single SEC filing record."""

    cik: str
    form: str
    filed_at: pd.Timestamp
    url: str
    items: list[str]


class EdgarConnector:
    """Fetches recent 8-K filings from the SEC EDGAR submissions API."""

    def __init__(
        self,
        user_agent: str = "Mahoraga research contact@example.com",
        *,
        timeout: float = 30.0,
    ) -> None:
        self._user_agent = user_agent
        self._timeout = timeout

    # --- public ----------------------------------------------------------

    def recent_8k(self, ticker: str, since: pd.Timestamp) -> list[Filing]:
        """Return 8-K filings for `ticker` filed on or after `since`.

        Any fetch or parse error yields `[]`.
        """
        cik = TICKER_TO_CIK.get(ticker.upper())
        if cik is None:
            logger.warning("no CIK mapping for ticker %s", ticker)
            return []
        url = SUBMISSIONS_URL.format(cik=cik)
        try:
            body = self._get(url)
            return self._parse_8k(body, since)
        except Exception as exc:  # noqa: BLE001 — graceful-offline contract
            logger.warning("EDGAR fetch/parse failed for %s: %s", ticker, exc)
            return []

    # --- transport (overridable in tests) --------------------------------

    def _get(self, url: str) -> dict[str, object]:
        headers = {"User-Agent": self._user_agent, "Accept": "application/json"}
        response = httpx.get(url, headers=headers, timeout=self._timeout)
        response.raise_for_status()
        return response.json()

    # --- internals -------------------------------------------------------

    def _parse_8k(self, body: dict[str, object], since: pd.Timestamp) -> list[Filing]:
        cik_raw = body.get("cik")
        cik = str(cik_raw) if cik_raw is not None else ""
        filings = body.get("filings")
        if not isinstance(filings, dict):
            return []
        recent = filings.get("recent")
        if not isinstance(recent, dict):
            return []

        forms = recent.get("form") or []
        dates = recent.get("filingDate") or []
        accessions = recent.get("accessionNumber") or []
        primaries = recent.get("primaryDocument") or []
        items_col = recent.get("items") or []

        out: list[Filing] = []
        for i, form in enumerate(forms):
            if form != "8-K":
                continue
            filed_at = pd.Timestamp(dates[i])
            if filed_at < since:
                continue
            accession = str(accessions[i]) if i < len(accessions) else ""
            primary = str(primaries[i]) if i < len(primaries) else ""
            raw_items = str(items_col[i]) if i < len(items_col) else ""
            items = [tok.strip() for tok in raw_items.split(",") if tok.strip()]
            out.append(
                Filing(
                    cik=cik,
                    form=form,
                    filed_at=filed_at,
                    url=self._filing_url(cik, accession, primary),
                    items=items,
                )
            )
        return out

    def _filing_url(self, cik: str, accession: str, primary: str) -> str:
        cik_int = int(cik) if cik.isdigit() else cik
        no_dashes = accession.replace("-", "")
        return f"{ARCHIVES_BASE}/{cik_int}/{no_dashes}/{primary}"
