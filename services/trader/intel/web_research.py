"""WebResearcher (Phase-4 T10) — weekly macro brief → Hindsight Mental Model.

Pulls the macro connectors (SEC EDGAR 8-Ks, Fed RSS, CME FedWatch), composes a
structured `signals` dict, and synthesizes a narrative. When an `llm` callable is
injected it produces the narrative (LiteLLM synthesis path); any failure falls back
to a deterministic template built purely from the pulled signals — so the brief is
always produced offline, never raises. When Hindsight is enabled the narrative is
retained once as a Mental Model.

Graceful-offline is the load-bearing contract (CLAUDE.md, mirroring `llm.py` /
`hindsight_client.py`): every connector already degrades to `[]`/`{}` on error, the
`llm` call is wrapped in try/except, and `hindsight=None`/disabled retains nothing.
No network is touched by the template path.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pandas as pd

from services.trader.training.hindsight_client import HindsightClient

logger = logging.getLogger(__name__)

# Tickers whose recent 8-Ks the weekly brief samples (kept small; EDGAR resolves
# each to a CIK internally). Absent EDGAR connector → this is simply skipped.
DEFAULT_WATCHLIST: list[str] = ["SPY", "AAPL", "MSFT", "NVDA"]

# How far back each connector looks for the weekly brief.
LOOKBACK = pd.Timedelta(days=7)


@dataclass(frozen=True)
class MacroBrief:
    """A synthesized weekly macro brief."""

    asof: pd.Timestamp
    narrative: str
    sources: list[str]
    signals: dict[str, Any]


class WebResearcher:
    """Composes a weekly macro brief from the macro connectors.

    `connectors` is a dict of any subset of
    `{"edgar": EdgarConnector, "fed_rss": FedRssConnector, "fedwatch": FedWatchConnector}`.
    `llm` is an optional `Callable[[str], str]` (LiteLLM synthesis); `None` → template.
    `hindsight` is an optional `HindsightClient`; `None`/disabled → no retain.
    """

    def __init__(
        self,
        connectors: dict[str, Any],
        llm: Callable[[str], str] | None = None,
        hindsight: HindsightClient | None = None,
        *,
        watchlist: list[str] | None = None,
    ) -> None:
        self._connectors = connectors
        self._llm = llm
        self._hindsight = hindsight
        self._watchlist = watchlist if watchlist is not None else DEFAULT_WATCHLIST

    # --- public ----------------------------------------------------------

    def weekly_brief(self, asof: pd.Timestamp) -> MacroBrief:
        """Pull the connectors, synthesize a narrative, retain a Mental Model."""
        signals: dict[str, Any] = {}
        sources: list[str] = []

        self._pull_fed_rss(signals, sources)
        self._pull_fedwatch(signals, sources, asof)
        self._pull_edgar(signals, sources, asof)

        narrative = self._synthesize(asof, signals, sources)
        brief = MacroBrief(
            asof=asof, narrative=narrative, sources=sources, signals=signals
        )
        self._retain(brief)
        return brief

    # --- connector pulls (each graceful; already degrade to []/{}) --------

    def _pull_fed_rss(self, signals: dict[str, Any], sources: list[str]) -> None:
        conn = self._connectors.get("fed_rss")
        if conn is None:
            return
        items = conn.latest()
        if not items:
            return
        signals["fed_rss"] = [
            {
                "title": item.title,
                "published": item.published.isoformat(),
                "kind": item.kind,
                "url": item.url,
            }
            for item in items
        ]
        sources.append("fed_rss")

    def _pull_fedwatch(
        self, signals: dict[str, Any], sources: list[str], asof: pd.Timestamp
    ) -> None:
        conn = self._connectors.get("fedwatch")
        if conn is None:
            return
        probs = conn.probabilities(asof)
        if not probs:
            return
        signals["fedwatch"] = dict(probs)
        sources.append("fedwatch")

    def _pull_edgar(
        self, signals: dict[str, Any], sources: list[str], asof: pd.Timestamp
    ) -> None:
        conn = self._connectors.get("edgar")
        if conn is None:
            return
        since = asof - LOOKBACK
        filings: list[dict[str, Any]] = []
        for ticker in self._watchlist:
            for filing in conn.recent_8k(ticker, since):
                filings.append(
                    {
                        "ticker": ticker,
                        "form": filing.form,
                        "filed_at": filing.filed_at.isoformat(),
                        "items": list(filing.items),
                        "url": filing.url,
                    }
                )
        if not filings:
            return
        signals["edgar"] = filings
        sources.append("edgar")

    # --- synthesis -------------------------------------------------------

    def _synthesize(
        self, asof: pd.Timestamp, signals: dict[str, Any], sources: list[str]
    ) -> str:
        template = self._template(asof, signals, sources)
        if self._llm is None:
            return template
        try:
            narrative = self._llm(self._prompt(asof, signals, sources))
        except Exception as exc:  # noqa: BLE001 — graceful-offline contract
            logger.warning("web-research LLM synthesis failed: %s", exc)
            return template
        return narrative if narrative and narrative.strip() else template

    def _prompt(
        self, asof: pd.Timestamp, signals: dict[str, Any], sources: list[str]
    ) -> str:
        return (
            "You are a macro strategist. Write a concise weekly macro brief for a "
            f"regime-aware trading system as of {asof.date().isoformat()}. Base it "
            "ONLY on the structured signals below (Fed communications, rate-move "
            "probabilities, recent material 8-K filings). Note the policy stance, "
            "rate expectations, and any company-specific material events, and their "
            "implication for market regime. No preamble.\n\n"
            f"Sources present: {', '.join(sources) or 'none'}\n"
            f"Signals: {signals}"
        )

    def _template(
        self, asof: pd.Timestamp, signals: dict[str, Any], sources: list[str]
    ) -> str:
        """Deterministic narrative built purely from the pulled signals."""
        lines = [f"Weekly macro brief as of {asof.date().isoformat()}."]

        fed = signals.get("fed_rss")
        if fed:
            lines.append(f"Fed communications ({len(fed)}):")
            lines.extend(f"  - [{i['kind']}] {i['title']}" for i in fed)

        fedwatch = signals.get("fedwatch")
        if fedwatch:
            probs = ", ".join(
                f"{label} {prob:.0%}" for label, prob in fedwatch.items()
            )
            lines.append(f"Rate-move probabilities: {probs}.")

        edgar = signals.get("edgar")
        if edgar:
            lines.append(f"Recent material 8-K filings ({len(edgar)}):")
            lines.extend(
                f"  - {f['ticker']} {f['form']} {f['filed_at']} items={f['items']}"
                for f in edgar
            )

        if not sources:
            lines.append("No macro signals available this week.")

        return "\n".join(lines)

    # --- persistence -----------------------------------------------------

    def _retain(self, brief: MacroBrief) -> None:
        hindsight = self._hindsight
        if hindsight is None or not hindsight.is_enabled():
            return
        hindsight.retain(
            brief.narrative,
            metadata={
                "kind": "mental_model",
                "asof": brief.asof.isoformat(),
                "sources": brief.sources,
            },
        )
