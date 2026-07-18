"""CME FedWatch rate-move probability connector.

CME FedWatch has no clean, stable, documented public JSON API — the numbers on
cmegroup.com are rendered client-side from an internal service backed by a
licensed data feed (CME/Bloomberg). So this connector is *best-effort*: it hits
the CME published-probabilities URL with a short timeout and, on any failure,
degrades gracefully to `{}`. It never fabricates probabilities.

Wire shape it expects (real or fixture): a JSON document of the form
`{"outcomes": [{"label": ..., "probability": ...}, ...]}` fetched via an
overridable `_get`, normalized to an `outcome -> probability` dict.

# ponytail: best-effort public data. The published CME endpoint is undocumented
# and may change or block; a paid CME/Bloomberg rate-probability feed is the
# upgrade path if this ever needs to be authoritative. Graceful-offline keeps
# the rest of the system correct meanwhile.

Graceful-offline: any fetch or parse error returns `{}` (and source
`"unavailable"`), never raises.
"""

from __future__ import annotations

import logging

import httpx
import pandas as pd

logger = logging.getLogger(__name__)

# Best-effort public source. CME renders FedWatch probabilities client-side from
# this services path; it is undocumented and unstable (hence best-effort).
FEDWATCH_URL = "https://www.cmegroup.com/services/fedwatch/probabilities"

# Source labels returned alongside the probabilities.
SOURCE_CME_PUBLIC = "cme-public"
SOURCE_UNAVAILABLE = "unavailable"


class FedWatchConnector:
    """Fetches implied rate-move probabilities from a FedWatch-shaped endpoint."""

    def __init__(self, *, timeout: float = 5.0) -> None:
        # Short timeout: best-effort public fetch; we would rather fall back to
        # `{}` quickly than block a cycle on an unreliable endpoint.
        self._timeout = timeout

    # --- public ----------------------------------------------------------

    def probabilities(self, asof: pd.Timestamp) -> dict[str, float]:
        """Return `outcome_label -> probability`. Errors yield `{}`."""
        probs, _ = self.probabilities_with_source(asof)
        return probs

    def probabilities_with_source(
        self, asof: pd.Timestamp
    ) -> tuple[dict[str, float], str]:
        """Return `(outcome_label -> probability, source_label)`.

        `source_label` is `"cme-public"` when the best-effort fetch returned
        usable outcomes, else `"unavailable"` (network/parse error, or a
        reachable-but-empty response). Never raises.
        """
        url = f"{FEDWATCH_URL}?asof={asof.date().isoformat()}"
        try:
            body = self._get(url)
            probs = self._parse(body)
        except Exception as exc:  # noqa: BLE001 — graceful-offline contract
            logger.warning("FedWatch fetch/parse failed: %s", exc)
            return {}, SOURCE_UNAVAILABLE
        if not probs:
            return {}, SOURCE_UNAVAILABLE
        return probs, SOURCE_CME_PUBLIC

    # --- transport (overridable in tests) --------------------------------

    def _get(self, url: str) -> dict[str, object]:
        response = httpx.get(url, timeout=self._timeout)
        response.raise_for_status()
        return response.json()

    # --- internals -------------------------------------------------------

    def _parse(self, body: dict[str, object]) -> dict[str, float]:
        outcomes = body.get("outcomes")
        if not isinstance(outcomes, list):
            return {}
        out: dict[str, float] = {}
        for outcome in outcomes:
            if not isinstance(outcome, dict):
                continue
            label = outcome.get("label")
            probability = outcome.get("probability")
            if label is None or probability is None:
                continue
            out[str(label)] = float(probability)
        return out
