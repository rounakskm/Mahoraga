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


def test_probabilities_with_source_real_shape_reports_public_source() -> None:
    """A live fetch of a real-shaped payload → normalized dict + non-'unavailable' source."""
    body = {
        "outcomes": [
            {"label": "cut_25bp", "probability": 0.10},
            {"label": "hold", "probability": 0.65},
            {"label": "hike_25bp", "probability": 0.25},
        ]
    }
    connector = FedWatchConnector()
    connector._get = lambda url: body  # type: ignore[method-assign]

    probs, source = connector.probabilities_with_source(asof=pd.Timestamp("2026-06-30"))

    assert probs == {"cut_25bp": 0.10, "hold": 0.65, "hike_25bp": 0.25}
    assert abs(sum(probs.values()) - 1.0) < 1e-6
    assert source == "cme-public"
    assert source != "unavailable"


def test_probabilities_with_source_error_reports_unavailable() -> None:
    connector = FedWatchConnector()

    def _boom(url: str) -> dict[str, object]:
        raise RuntimeError("network down")

    connector._get = _boom  # type: ignore[method-assign]

    probs, source = connector.probabilities_with_source(asof=pd.Timestamp("2026-06-30"))

    assert probs == {}
    assert source == "unavailable"


def test_probabilities_with_source_empty_outcomes_reports_unavailable() -> None:
    """A reachable endpoint that yields no usable outcomes is 'unavailable', not 'cme-public'."""
    connector = FedWatchConnector()
    connector._get = lambda url: {"outcomes": []}  # type: ignore[method-assign]

    probs, source = connector.probabilities_with_source(asof=pd.Timestamp("2026-06-30"))

    assert probs == {}
    assert source == "unavailable"


def test_probabilities_delegates_to_with_source() -> None:
    body = _load()
    connector = FedWatchConnector()
    connector._get = lambda url: body  # type: ignore[method-assign]

    probs = connector.probabilities(asof=pd.Timestamp("2026-06-30"))
    probs_via_source, _ = connector.probabilities_with_source(
        asof=pd.Timestamp("2026-06-30")
    )

    assert probs == probs_via_source
