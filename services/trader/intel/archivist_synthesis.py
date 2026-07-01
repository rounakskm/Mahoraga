"""ArchivistSynthesis (Phase-4 L2/L3) — periodic consolidation over Hindsight.

The Archivist's synthesis cadence turns raw memory into structured knowledge:

- **L2 (weekly)** — recall recent Experience Facts, trigger a `reflect()` pass, then
  retain a synthesized **Observation** summarizing the week's patterns.
- **L3 (monthly)** — recall the accumulated L2 Observations, `reflect()`, then retain a
  synthesized **Mental Model** — the curated, higher-order principle.

Graceful-offline is the load-bearing contract (CLAUDE.md, mirroring `HindsightClient`
and `ProvenanceWriter(dsn=None)`): `hindsight=None` — or a disabled/unreachable client —
makes every method a safe no-op returning `None`, touching no network.

Adaptation note: the real `HindsightClient.reflect()` takes no args and returns `None`
(it triggers server-side consolidation, it does not hand back a synthesized dict). So the
synthesis dict is assembled here from the recalled facts, `reflect()` is fired to trigger
consolidation, and `retain()` persists the result — the returned dict is that persisted
synthesis, not a `reflect()` return value.
"""

from __future__ import annotations

from typing import Any

from services.trader.training.hindsight_client import HindsightClient

_L2_RECALL_QUERY = "experience facts recent trade outcomes and regime context"
_L3_RECALL_QUERY = "observation weekly synthesized patterns"


class ArchivistSynthesis:
    """L2/L3 synthesis over Hindsight; safe no-op when `hindsight` is None/disabled."""

    def __init__(self, hindsight: HindsightClient | None = None) -> None:
        self._hindsight = hindsight

    def _enabled(self) -> bool:
        return self._hindsight is not None and self._hindsight.is_enabled()

    def level2_weekly(self, asof: str, k: int = 20) -> dict[str, Any] | None:
        """Weekly: recall Experience Facts → reflect → retain an Observation.

        Returns the persisted Observation dict, or `None` when Hindsight is
        None/disabled.
        """
        if not self._enabled():
            return None
        hindsight = self._hindsight
        assert hindsight is not None  # narrowed by _enabled(); for type-checkers
        facts = hindsight.recall(_L2_RECALL_QUERY, k=k)
        hindsight.reflect()
        observation: dict[str, Any] = {
            "kind": "observation",
            "level": "L2",
            "asof": asof,
            "source_count": len(facts),
            "sources": [f.get("text", "") for f in facts],
        }
        fact_id = hindsight.retain(_summarize(observation), metadata=observation)
        observation["fact_id"] = fact_id
        return observation

    def level3_monthly(self, asof: str, k: int = 20) -> dict[str, Any] | None:
        """Monthly: recall L2 Observations → reflect → retain a Mental Model.

        Returns the persisted Mental Model dict, or `None` when Hindsight is
        None/disabled.
        """
        if not self._enabled():
            return None
        hindsight = self._hindsight
        assert hindsight is not None  # narrowed by _enabled(); for type-checkers
        observations = hindsight.recall(_L3_RECALL_QUERY, k=k)
        hindsight.reflect()
        model: dict[str, Any] = {
            "kind": "mental_model",
            "level": "L3",
            "asof": asof,
            "source_count": len(observations),
            "sources": [o.get("text", "") for o in observations],
        }
        fact_id = hindsight.retain(_summarize(model), metadata=model)
        model["fact_id"] = fact_id
        return model


def _summarize(synthesis: dict[str, Any]) -> str:
    """Human-readable one-liner for the retained fact's `text` field."""
    return (
        f"{synthesis['kind']} ({synthesis['level']}) asof {synthesis['asof']} "
        f"from {synthesis['source_count']} source(s)"
    )
