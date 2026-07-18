"""Watchlist + sector map + multi-symbol signal/intent builders (Tier-3 Task 1).

Turns the single-symbol signal path into a real portfolio one: fan the promoted
artifact over a per-symbol daily-bars dict, then fan the resulting signals over
the current book to produce the intent list `Executor.run_cycle` consumes.

Pure functions, no I/O — the runner supplies bars/portfolio/prices/ATRs and owns
all broker interaction. The per-symbol sector map is the one new input the
portfolio-wide firewall needs (it already aggregates the 20% sector cap over the
`Portfolio`; each intent just has to declare which sector it belongs to).
"""

from __future__ import annotations

import logging

import pandas as pd

from services.trader.execution.model import OrderIntent, Portfolio
from services.trader.execution.signal import (
    DailySignal,
    compute_signal,
    intent_from_signal,
)

logger = logging.getLogger(__name__)

# Broad indices + four sector ETFs — enough distinct sectors to exercise the
# 20% sector cap and the 5% single-position cap in a live multi-symbol cycle.
DEFAULT_WATCHLIST: tuple[str, ...] = ("SPY", "QQQ", "IWM", "XLK", "XLE", "XLF", "XLV")

# Maps each watchlist symbol to the sector bucket the firewall aggregates on.
SECTOR_BY_TICKER: dict[str, str] = {
    "SPY": "BROAD",
    "QQQ": "BROAD",
    "IWM": "BROAD",
    "XLK": "TECH",
    "XLE": "ENERGY",
    "XLF": "FINANCIALS",
    "XLV": "HEALTHCARE",
}

_UNKNOWN_SECTOR = "UNKNOWN"

_DEFAULT_ENTRY_WEIGHT = 0.03


def sector_for(ticker: str) -> str:
    """Sector bucket for `ticker`; `"UNKNOWN"` when it is not in the map."""
    return SECTOR_BY_TICKER.get(ticker, _UNKNOWN_SECTOR)


def signals_for(
    artifact: dict, bars_by_symbol: dict[str, pd.DataFrame]
) -> dict[str, DailySignal]:
    """Run `compute_signal` per symbol; keep only the decidable ones.

    A symbol is dropped when `compute_signal` returns None (undefined regime /
    warmup-only frame). Logs a one-line summary of the resolved regimes so the
    live cadence has a legible trace of what each symbol read this bar.
    """
    signals: dict[str, DailySignal] = {}
    for symbol, bars in bars_by_symbol.items():
        sig = compute_signal(artifact, bars)
        if sig is not None:
            signals[symbol] = sig

    summary = ", ".join(
        f"{symbol}={sig.regime}{'/long' if sig.want_long else '/flat'}"
        for symbol, sig in signals.items()
    )
    logger.info(
        "signals_for: %d/%d symbols decidable [%s]",
        len(signals),
        len(bars_by_symbol),
        summary or "-",
    )
    return signals


def intents_for(
    signals: dict[str, DailySignal],
    portfolio: Portfolio,
    prices: dict[str, float],
    atr_by_symbol: dict[str, float | None],
    *,
    weight: float = _DEFAULT_ENTRY_WEIGHT,
) -> list[OrderIntent]:
    """Fan `intent_from_signal` over `signals`; drop the non-actionable ones.

    `weight` maps to `intent_from_signal`'s `entry_weight` kwarg (the BUY-entry
    portfolio weight). The returned list is exactly what `Executor.run_cycle`
    consumes.
    """
    intents: list[OrderIntent] = []
    for symbol, sig in signals.items():
        intent = intent_from_signal(
            sig,
            portfolio,
            symbol,
            prices[symbol],
            atr_by_symbol.get(symbol),
            entry_weight=weight,
        )
        if intent is not None:
            intents.append(intent)
    return intents
