"""CME FedWatch rate-move probability connector.

CME FedWatch has no clean, stable public JSON endpoint, so this connector models
the shape we need: a JSON document of the form
`{"outcomes": [{"label": ..., "probability": ...}, ...]}` fetched via an
overridable `_get`, normalized to an `outcome -> probability` dict.

Graceful-offline: any fetch or parse error returns `{}`, never raises.
"""

from __future__ import annotations

import logging

import httpx
import pandas as pd

logger = logging.getLogger(__name__)

FEDWATCH_URL = "https://www.cmegroup.com/services/fedwatch/probabilities"


class FedWatchConnector:
    """Fetches implied rate-move probabilities from a FedWatch-shaped endpoint."""

    def __init__(self, *, timeout: float = 30.0) -> None:
        self._timeout = timeout

    # --- public ----------------------------------------------------------

    def probabilities(self, asof: pd.Timestamp) -> dict[str, float]:
        """Return `outcome_label -> probability`. Errors yield `{}`."""
        url = f"{FEDWATCH_URL}?asof={asof.date().isoformat()}"
        try:
            body = self._get(url)
            return self._parse(body)
        except Exception as exc:  # noqa: BLE001 — graceful-offline contract
            logger.warning("FedWatch fetch/parse failed: %s", exc)
            return {}

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
