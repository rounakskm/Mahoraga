"""Tests for the CME FedWatch rate-move probability connector.

Parses a committed outcomes fixture; no live network.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from services.trader.data.connectors.fedwatch import FedWatchConnector

FIXTURE = Path(__file__).parent / "fixtures" / "fedwatch_sample.json"


def _load() -> dict[str, object]:
    return json.loads(FIXTURE.read_text())


def test_probabilities_parses_fixture() -> None:
    body = _load()
    connector = FedWatchConnector()
    connector._get = lambda url: body  # type: ignore[method-assign]

    probs = connector.probabilities(asof=pd.Timestamp("2026-06-30"))

    assert probs == {"cut_25bp": 0.12, "hold": 0.71, "hike_25bp": 0.17}
    assert abs(sum(probs.values()) - 1.0) < 1e-6


def test_fetch_error_returns_empty() -> None:
    connector = FedWatchConnector()

    def _boom(url: str) -> dict[str, object]:
        raise RuntimeError("network down")

    connector._get = _boom  # type: ignore[method-assign]

    assert connector.probabilities(asof=pd.Timestamp("2026-06-30")) == {}
