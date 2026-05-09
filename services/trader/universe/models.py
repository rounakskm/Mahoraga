"""Dataclasses + enum types for universe management.

The runtime data shape is intentionally tiny: a `seed` set of tickers active
on `seed_date`, plus an ordered list of `add` / `remove` events. Membership
on any date Y is `seed ∪ {add events ≤ Y} ∖ {remove events ≤ Y}`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum


class UniverseAction(StrEnum):
    ADD = "add"
    REMOVE = "remove"


@dataclass(frozen=True)
class UniverseEvent:
    """One add or remove event for a ticker in a named universe."""

    date: date
    ticker: str
    action: UniverseAction
    note: str = ""


@dataclass(frozen=True)
class UniverseEntry:
    """An ETF allowlist entry. Active = listed_at <= asof < (delisted_at or +inf)."""

    ticker: str
    listed_at: date | None = None
    delisted_at: date | None = None
    category: str = ""

    def is_active(self, asof: date) -> bool:
        if self.listed_at is not None and asof < self.listed_at:
            return False
        return not (self.delisted_at is not None and asof >= self.delisted_at)


@dataclass(frozen=True)
class UniverseSeed:
    """Initial constituent set for a named universe on a specific date."""

    name: str
    seed_date: date
    members: frozenset[str] = field(default_factory=frozenset)
