"""ArchivistSynthesis (Phase-4 L2/L3) — recall → reflect → retain, graceful-offline.

The load-bearing contract mirrors `HindsightClient`: `hindsight=None` (or a disabled
client) makes every method a safe no-op returning `None`, touching no network. The
enabled path is exercised with a `_FakeHindsight` that stubs `recall`/`retain` in
memory (no transport, no network), so we can assert the recall→persist→return shape.
"""

from __future__ import annotations

from services.trader.intel.archivist_synthesis import ArchivistSynthesis
from services.trader.training.hindsight_client import HindsightClient


class _FakeHindsight(HindsightClient):
    """In-memory Hindsight: enabled, canned recall, records retain calls. No network."""

    def __init__(self) -> None:
        super().__init__(base_url="http://hindsight:8888")
        self.recall_calls: list[tuple[str, int]] = []
        self.retain_calls: list[tuple[str, dict]] = []
        self.reflect_calls: int = 0
        self.recall_return: list[dict] = [
            {"text": "SPY long paid off in trending regime", "score": 0.91},
            {"text": "mean-reversion faded in high-vol regime", "score": 0.84},
        ]

    def recall(self, query: str, k: int = 5) -> list[dict]:
        self.recall_calls.append((query, k))
        return list(self.recall_return)

    def retain(self, text: str, metadata: dict | None = None) -> str | None:
        self.retain_calls.append((text, metadata or {}))
        return f"fact-{len(self.retain_calls)}"

    def reflect(self) -> None:
        self.reflect_calls += 1


# --- disabled contract: hindsight=None → every method is a None no-op ---


def test_level2_none_when_no_hindsight() -> None:
    assert ArchivistSynthesis(hindsight=None).level2_weekly("2026-06-30") is None


def test_level3_none_when_no_hindsight() -> None:
    assert ArchivistSynthesis(hindsight=None).level3_monthly("2026-06-30") is None


def test_disabled_client_is_no_op() -> None:
    syn = ArchivistSynthesis(hindsight=HindsightClient(None))
    assert syn.level2_weekly("2026-06-30") is None
    assert syn.level3_monthly("2026-06-30") is None


# --- enabled path: recall → synthesize → retain → return the dict ---


def test_level2_weekly_recalls_persists_and_returns() -> None:
    hs = _FakeHindsight()
    syn = ArchivistSynthesis(hindsight=hs)

    obs = syn.level2_weekly("2026-06-30")

    assert obs is not None
    assert hs.recall_calls, "level2 must recall Experience Facts"
    query, _k = hs.recall_calls[0]
    assert "experience" in query.lower()
    assert hs.reflect_calls == 1, "level2 must trigger reflect()"
    assert hs.retain_calls, "level2 must persist the Observation"
    assert obs["kind"] == "observation"
    assert obs["asof"] == "2026-06-30"
    assert obs["source_count"] == len(hs.recall_return)


def test_level3_monthly_recalls_persists_and_returns() -> None:
    hs = _FakeHindsight()
    syn = ArchivistSynthesis(hindsight=hs)

    model = syn.level3_monthly("2026-06-30")

    assert model is not None
    assert hs.recall_calls, "level3 must recall Observations"
    query, _k = hs.recall_calls[0]
    assert "observation" in query.lower()
    assert hs.reflect_calls == 1, "level3 must trigger reflect()"
    assert hs.retain_calls, "level3 must persist the Mental Model"
    assert model["kind"] == "mental_model"
    assert model["asof"] == "2026-06-30"
    assert model["source_count"] == len(hs.recall_return)


def test_level2_empty_recall_still_returns_dict() -> None:
    hs = _FakeHindsight()
    hs.recall_return = []
    obs = ArchivistSynthesis(hindsight=hs).level2_weekly("2026-06-30")
    assert obs is not None
    assert obs["source_count"] == 0
