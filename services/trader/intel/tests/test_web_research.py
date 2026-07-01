"""WebResearcher (Phase-4 T10) — weekly macro brief synthesis, graceful-offline.

The load-bearing contract mirrors the rest of the intel layer: `llm=None` yields a
deterministic template narrative (no network), and `hindsight=None` retains nothing.
The connectors are STUBS returning fixture-like records in memory (no transport, no
network), so the brief composition + template + single Mental-Model retain can be
asserted without hitting the wire.
"""

from __future__ import annotations

import pandas as pd

from services.trader.data.connectors.edgar import Filing
from services.trader.data.connectors.fed_rss import FedItem
from services.trader.intel.web_research import MacroBrief, WebResearcher
from services.trader.training.hindsight_client import HindsightClient

ASOF = pd.Timestamp("2026-06-30", tz="UTC")


class _StubFedRss:
    """Returns two canned FedItems. No network."""

    def latest(self, feeds: object = None) -> list[FedItem]:
        return [
            FedItem(
                title="FOMC holds rates steady",
                published=pd.Timestamp("2026-06-25", tz="UTC"),
                url="https://www.federalreserve.gov/a",
                kind="press",
            ),
            FedItem(
                title="Chair speaks on inflation outlook",
                published=pd.Timestamp("2026-06-27", tz="UTC"),
                url="https://www.federalreserve.gov/b",
                kind="speeches",
            ),
        ]


class _StubFedWatch:
    """Returns a canned probabilities dict. No network."""

    def probabilities(self, asof: pd.Timestamp) -> dict[str, float]:
        return {"hold": 0.7, "cut_25bp": 0.3}


class _StubEdgar:
    """Returns one canned 8-K filing. No network."""

    def recent_8k(self, ticker: str, since: pd.Timestamp) -> list[Filing]:
        return [
            Filing(
                cik="884394",
                form="8-K",
                filed_at=pd.Timestamp("2026-06-28"),
                url="https://www.sec.gov/x",
                items=["2.02"],
            )
        ]


class _FakeHindsight(HindsightClient):
    """In-memory Hindsight: enabled, records retain calls. No network."""

    def __init__(self) -> None:
        super().__init__(base_url="http://hindsight:8888")
        self.retain_calls: list[tuple[str, dict]] = []

    def retain(self, text: str, metadata: dict | None = None) -> str | None:
        self.retain_calls.append((text, metadata or {}))
        return f"fact-{len(self.retain_calls)}"


# --- offline template path: llm=None → deterministic narrative, no retain ---


def test_weekly_brief_returns_macrobrief_with_sources_and_template() -> None:
    researcher = WebResearcher(
        connectors={
            "fed_rss": _StubFedRss(),
            "fedwatch": _StubFedWatch(),
            "edgar": _StubEdgar(),
        },
        llm=None,
        hindsight=None,
    )

    brief = researcher.weekly_brief(ASOF)

    assert isinstance(brief, MacroBrief)
    assert brief.asof == ASOF
    assert set(brief.sources) == {"fed_rss", "fedwatch", "edgar"}
    assert brief.narrative.strip(), "narrative must be non-empty"
    # template mentions the pulled signals
    assert "FOMC holds rates steady" in brief.narrative
    assert "hold" in brief.narrative
    assert "8-K" in brief.narrative
    assert "fed_rss" in brief.signals
    assert "fedwatch" in brief.signals


def test_sources_only_names_connectors_that_returned_data() -> None:
    class _EmptyFedRss:
        def latest(self, feeds: object = None) -> list[FedItem]:
            return []

    researcher = WebResearcher(
        connectors={"fed_rss": _EmptyFedRss(), "fedwatch": _StubFedWatch()},
        llm=None,
    )
    brief = researcher.weekly_brief(ASOF)
    assert brief.sources == ["fedwatch"]


# --- Hindsight Mental Model: retained exactly once when enabled ---


def test_mental_model_retained_once() -> None:
    hs = _FakeHindsight()
    researcher = WebResearcher(
        connectors={"fedwatch": _StubFedWatch()},
        llm=None,
        hindsight=hs,
    )

    brief = researcher.weekly_brief(ASOF)

    assert len(hs.retain_calls) == 1, "exactly one Mental Model retained"
    text, metadata = hs.retain_calls[0]
    assert text == brief.narrative
    assert metadata["kind"] == "mental_model"
    assert metadata["asof"] == ASOF.isoformat()
    assert metadata["sources"] == brief.sources


def test_hindsight_none_retains_nothing() -> None:
    researcher = WebResearcher(connectors={"fedwatch": _StubFedWatch()}, llm=None)
    # must not raise; nothing to assert beyond no-crash
    researcher.weekly_brief(ASOF)


def test_disabled_hindsight_client_retains_nothing() -> None:
    hs = HindsightClient(None)
    researcher = WebResearcher(
        connectors={"fedwatch": _StubFedWatch()},
        llm=None,
        hindsight=hs,
    )
    researcher.weekly_brief(ASOF)  # no-op retain, no network


# --- llm path: uses the injected llm; falls back to template on error ---


def test_llm_narrative_used_when_provided() -> None:
    def _llm(prompt: str) -> str:
        return "LLM synthesized macro view."

    researcher = WebResearcher(
        connectors={"fedwatch": _StubFedWatch()},
        llm=_llm,
    )
    brief = researcher.weekly_brief(ASOF)
    assert brief.narrative == "LLM synthesized macro view."


def test_llm_failure_falls_back_to_template() -> None:
    def _boom(prompt: str) -> str:
        raise RuntimeError("provider down")

    researcher = WebResearcher(
        connectors={"fedwatch": _StubFedWatch()},
        llm=_boom,
    )
    brief = researcher.weekly_brief(ASOF)
    assert brief.narrative.strip()
    assert "hold" in brief.narrative  # deterministic template


def test_no_connectors_never_raises() -> None:
    brief = WebResearcher(connectors={}, llm=None).weekly_brief(ASOF)
    assert isinstance(brief, MacroBrief)
    assert brief.sources == []
