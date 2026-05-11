"""Stub strategies for the Phase 1 backtest harness.

Phase 1 ships a single buy-and-hold stub so the engine has something
deterministic to run end-to-end. Real strategies land in Phase 3 from
the autoresearch loop.
"""

from __future__ import annotations

from typing import ClassVar

import pandas as pd

from services.trader.backtest.base import Strategy


class BuyAndHold(Strategy):
    """Equal-weight buy-and-hold across the requested universe.

    Every bar, every ticker gets `target_weight = 1.0 / len(universe)`.
    Re-running on the same inputs is bit-identical.
    """

    name: ClassVar[str] = "buy_and_hold"
    requires_features: ClassVar[list[str]] = []
    allow_placeholder_features: ClassVar[bool] = False

    def generate_signals(
        self,
        *,
        feature_frame: pd.DataFrame,
        regime_frame: pd.DataFrame,  # noqa: ARG002  (kept for ABC parity)
    ) -> pd.DataFrame:
        if feature_frame.empty:
            return pd.DataFrame(
                columns=["ticker", "bar_timestamp", "target_weight"]
            )
        tickers = feature_frame["ticker"].unique()
        if len(tickers) == 0:
            return pd.DataFrame(
                columns=["ticker", "bar_timestamp", "target_weight"]
            )
        weight = 1.0 / len(tickers)
        return pd.DataFrame(
            {
                "ticker": feature_frame["ticker"].to_numpy(),
                "bar_timestamp": feature_frame["bar_timestamp"].to_numpy(),
                "target_weight": [weight] * len(feature_frame),
            }
        )
