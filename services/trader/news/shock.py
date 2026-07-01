"""NewsShockProtocol — CRITICAL news trips the Layer-3 kill-switch + a forced hold.

A CRITICAL classification (FOMC surprise, halt, war, bankruptcy) is a market shock:
it trips the shared `HaltControl` kill-switch (no new entries until a human `/resume`),
tightens stops on open positions, and sets a forced-exit hold window so nothing is
force-exited into the initial chaos. MATERIAL/BACKGROUND items are no-ops.

This reuses the Phase-3 Layer-3 kill-switch (`ops.halt.HaltControl`) — it does NOT
invent a new halt mechanism, so the existing `/resume` path clears a news halt.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from services.trader.news.classifier import Classification
from services.trader.ops.halt import HaltControl


@dataclass(frozen=True)
class ShockAction:
    """The action taken in response to one classified news item."""

    halted: bool
    tightened_stops: bool
    hold_until: pd.Timestamp | None
    reason: str


class NewsShockProtocol:
    """Trips the kill-switch on CRITICAL news; no-op otherwise."""

    def __init__(self, halt: HaltControl, hold_minutes: int = 10) -> None:
        self._halt = halt
        self._hold_minutes = hold_minutes

    def on_classified(
        self,
        classification: Classification,
        headline: str,
        now: pd.Timestamp,
    ) -> ShockAction:
        if classification.level != "CRITICAL":
            return ShockAction(
                halted=False,
                tightened_stops=False,
                hold_until=None,
                reason="no shock",
            )

        reason = f"news shock: {headline}"
        self._halt.halt(reason)
        return ShockAction(
            halted=True,
            tightened_stops=True,
            hold_until=now + pd.Timedelta(minutes=self._hold_minutes),
            reason=reason,
        )
