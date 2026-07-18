"""Researcher pipeline (Tier-3 Task 3) — macro sources → structured hypotheses.

Pulls the macro connectors (Fed RSS, SEC EDGAR 8-Ks, CME FedWatch), maps notable
items to structured single-change `Hypothesis` records the fleet Planner can seed
on, dedups them, and — when Hindsight is enabled — grounds the output against a
recalled "do-not-repeat" set (dropping stale hypotheses) while retaining each
surviving one as a World Fact.

Design mirrors `intel/web_research.py`: `connectors` is a dict of any subset of
`{"fed_rss", "edgar", "fedwatch"}`; each pull is best-effort in its own try/except
so one erroring/absent connector never sinks the scan. Every connector already
degrades to `[]`/`{}` on error, and this layer additionally guards each pull —
offline / all-erroring → `[]`, never raises. `hindsight=None`/disabled → no
retain and no recall (nothing is dropped as stale).
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# Valid `signal_kind` values a Hypothesis may carry.
SIGNAL_KINDS = frozenset(
    {"macro_risk", "rate_path", "sector_rotation", "event"}
)

# How far back the EDGAR pull looks for material 8-Ks.
LOOKBACK = pd.Timedelta(days=30)

# Small watchlist whose recent 8-Ks the scan samples (EDGAR resolves each to a
# CIK internally; unmapped tickers simply yield nothing). Absent EDGAR connector
# → skipped entirely.
DEFAULT_WATCHLIST: list[str] = ["SPY", "AAPL", "MSFT", "NVDA"]

# Fed-communication keywords → keyword strength (drives the rate_path
# confidence). Presence of any promotes a title to a rate_path hypothesis; the
# strongest matched term sets the confidence.
_HAWKISH_TERMS: dict[str, float] = {
    "hike": 0.7,
    "raise rates": 0.7,
    "tighten": 0.65,
    "hawkish": 0.7,
    "restrictive": 0.6,
    "inflation": 0.55,
    "higher for longer": 0.75,
}

# FedWatch: an outcome whose probability clears this bar becomes a high-confidence
# rate_path hypothesis (the confidence is the probability itself).
_FEDWATCH_THRESHOLD = 0.6

# How many do-not-repeat entries to recall when grounding.
_RECALL_K = 20


@dataclass(frozen=True)
class Hypothesis:
    """A single structured research hypothesis (one change, one source)."""

    source: str
    text: str
    signal_kind: str
    confidence: float


class Researcher:
    """Scans the macro connectors and emits structured hypotheses.

    `connectors` is a dict of any subset of
    `{"fed_rss": FedRssConnector, "edgar": EdgarConnector, "fedwatch": FedWatchConnector}`.
    `hindsight` is an optional client exposing `is_enabled()`, `recall(query, k)`
    and `retain(text, metadata)`; `None`/disabled → no grounding, no retain.
    """

    def __init__(
        self,
        connectors: dict[str, Any],
        hindsight: Any | None = None,
        *,
        watchlist: list[str] | None = None,
    ) -> None:
        self._connectors = connectors
        self._hindsight = hindsight
        self._watchlist = (
            watchlist if watchlist is not None else DEFAULT_WATCHLIST
        )

    # --- public ----------------------------------------------------------

    def scan(self, asof: pd.Timestamp) -> list[Hypothesis]:
        """Pull the macro connectors and return deduped, Hindsight-grounded
        hypotheses. Any offline / erroring path degrades to `[]`; never raises.
        """
        hyps: list[Hypothesis] = []
        hyps.extend(self._pull_fed_rss())
        hyps.extend(self._pull_fedwatch(asof))
        hyps.extend(self._pull_edgar(asof))

        hyps = self._dedup(hyps)
        hyps = self._ground(hyps)
        self._retain(hyps)
        return hyps

    # --- connector pulls (each best-effort, own try/except) --------------

    def _pull_fed_rss(self) -> list[Hypothesis]:
        conn = self._connectors.get("fed_rss")
        if conn is None:
            return []
        try:
            items = conn.latest()
        except Exception as exc:  # noqa: BLE001 — graceful-offline contract
            logger.warning("researcher fed_rss pull failed: %s", exc)
            return []
        out: list[Hypothesis] = []
        for item in items:
            hyp = self._fed_item_to_hypothesis(item)
            if hyp is not None:
                out.append(hyp)
        return out

    def _pull_fedwatch(self, asof: pd.Timestamp) -> list[Hypothesis]:
        conn = self._connectors.get("fedwatch")
        if conn is None:
            return []
        try:
            probs = conn.probabilities(asof)
        except Exception as exc:  # noqa: BLE001 — graceful-offline contract
            logger.warning("researcher fedwatch pull failed: %s", exc)
            return []
        out: list[Hypothesis] = []
        for label, prob in probs.items():
            if prob > _FEDWATCH_THRESHOLD:
                out.append(
                    Hypothesis(
                        source="fedwatch",
                        text=(
                            f"FedWatch implies '{label}' with {prob:.0%} "
                            "probability — a likely near-term rate outcome."
                        ),
                        signal_kind="rate_path",
                        confidence=round(float(prob), 4),
                    )
                )
        return out

    def _pull_edgar(self, asof: pd.Timestamp) -> list[Hypothesis]:
        conn = self._connectors.get("edgar")
        if conn is None:
            return []
        since = asof - LOOKBACK
        out: list[Hypothesis] = []
        for ticker in self._watchlist:
            try:
                filings = conn.recent_8k(ticker, since)
            except Exception as exc:  # noqa: BLE001 — graceful-offline contract
                logger.warning(
                    "researcher edgar pull failed for %s: %s", ticker, exc
                )
                continue
            for filing in filings:
                if not filing.items:
                    continue
                out.append(
                    Hypothesis(
                        source="edgar",
                        text=(
                            f"{ticker} filed a material 8-K on "
                            f"{filing.filed_at.date().isoformat()} "
                            f"(items {', '.join(filing.items)}) — a company-"
                            "specific event to assess."
                        ),
                        signal_kind="event",
                        confidence=0.5,
                    )
                )
        return out

    # --- mapping ---------------------------------------------------------

    def _fed_item_to_hypothesis(self, item: Any) -> Hypothesis | None:
        """A Fed title carrying hawkish/hike/inflation terms → a rate_path
        hypothesis; confidence is the strongest matched keyword's strength.
        Non-matching titles yield None (no hypothesis)."""
        lowered = item.title.lower()
        matched = [
            strength
            for term, strength in _HAWKISH_TERMS.items()
            if term in lowered
        ]
        if not matched:
            return None
        confidence = max(matched)
        return Hypothesis(
            source="fed_rss",
            text=(
                f"Fed communication signals a hawkish rate path: {item.title}"
            ),
            signal_kind="rate_path",
            confidence=round(confidence, 4),
        )

    # --- dedup / grounding / persistence ---------------------------------

    def _dedup(self, hyps: list[Hypothesis]) -> list[Hypothesis]:
        seen: set[tuple[str, str]] = set()
        out: list[Hypothesis] = []
        for hyp in hyps:
            key = (hyp.signal_kind, hyp.text)
            if key in seen:
                continue
            seen.add(key)
            out.append(hyp)
        return out

    def _ground(self, hyps: list[Hypothesis]) -> list[Hypothesis]:
        """Drop hypotheses whose text (or text-hash) is in the recalled
        do-not-repeat set. No-op when Hindsight is disabled."""
        stale = self._do_not_repeat()
        if not stale:
            return hyps
        return [h for h in hyps if not self._is_stale(h.text, stale)]

    def _do_not_repeat(self) -> set[str]:
        hindsight = self._hindsight
        if hindsight is None or not hindsight.is_enabled():
            return set()
        try:
            results = hindsight.recall("do-not-repeat research", k=_RECALL_K)
        except Exception as exc:  # noqa: BLE001 — graceful-offline contract
            logger.warning("researcher recall failed: %s", exc)
            return set()
        stale: set[str] = set()
        for result in results:
            content = result.get("content") if isinstance(result, dict) else None
            if content:
                stale.add(str(content))
        return stale

    @staticmethod
    def _is_stale(text: str, stale: set[str]) -> bool:
        if text in stale:
            return True
        return _text_hash(text) in stale

    def _retain(self, hyps: list[Hypothesis]) -> None:
        hindsight = self._hindsight
        if hindsight is None or not hindsight.is_enabled():
            return
        for hyp in hyps:
            try:
                hindsight.retain(
                    hyp.text,
                    metadata={
                        "kind": "research_hypothesis",
                        "signal_kind": hyp.signal_kind,
                        "source": hyp.source,
                        "confidence": hyp.confidence,
                        "text_hash": _text_hash(hyp.text),
                    },
                )
            except Exception as exc:  # noqa: BLE001 — graceful-offline contract
                logger.warning("researcher retain failed: %s", exc)


def to_planner_queue(hyps: list[Hypothesis]) -> list[dict]:
    """Shape hypotheses into the seed records the fleet Planner reads."""
    return [
        {
            "hypothesis": h.text,
            "kind": h.signal_kind,
            "confidence": h.confidence,
            "source": h.source,
        }
        for h in hyps
    ]


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()
