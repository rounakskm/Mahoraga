"""YAML loader + read API for universe management.

The on-disk layout (`data/universe/`) and the membership-replay rule are
defined in `docs/superpowers/specs/phase-1-foundation/universe-spec.md`.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from services.trader.universe.models import (
    UniverseAction,
    UniverseEntry,
    UniverseEvent,
    UniverseSeed,
)

logger = logging.getLogger(__name__)


class UniverseSchemaError(Exception):
    """Raised when an on-disk YAML file violates the universe schema."""


# --- internal storage ----------------------------------------------------


@dataclass(frozen=True)
class _NamedHistory:
    seed: UniverseSeed
    events: tuple[UniverseEvent, ...]


# --- public API ----------------------------------------------------------


class Universe:
    """Read-only view over the on-disk universe state.

    Construct via :meth:`Universe.load`. The runtime never hits the network;
    bootstrap scripts are operator-run and write the YAML files this loader
    reads. See `services/trader/universe/README.md` (chunk U2).
    """

    def __init__(
        self,
        *,
        histories: dict[str, _NamedHistory],
        etfs: dict[str, UniverseEntry],
    ) -> None:
        self._histories = dict(histories)
        self._etfs = dict(etfs)

    # --- factory -----------------------------------------------------

    @classmethod
    def load(cls, root: Path | str) -> Universe:
        """Load every universe rooted at `<root>/<name>/{seed,events}.yaml`."""
        root_path = Path(root)
        if not root_path.exists():
            raise UniverseSchemaError(f"universe root {root_path} does not exist")

        histories: dict[str, _NamedHistory] = {}
        for name_dir in sorted(p for p in root_path.iterdir() if p.is_dir()):
            if name_dir.name == "manifests":
                continue
            seed_path = name_dir / "seed.yaml"
            events_path = name_dir / "events.yaml"
            if not seed_path.exists():
                # A bare directory under root is fine; skip silently.
                continue
            seed = _parse_seed(seed_path, expected_name=name_dir.name)
            events = _parse_events(events_path, expected_name=name_dir.name)
            _validate_history(seed, events)
            histories[name_dir.name] = _NamedHistory(seed=seed, events=tuple(events))

        etfs_path = root_path / "etfs.yaml"
        etfs: dict[str, UniverseEntry] = (
            _parse_etfs(etfs_path) if etfs_path.exists() else {}
        )
        return cls(histories=histories, etfs=etfs)

    # --- query API ---------------------------------------------------

    def known_universes(self) -> list[str]:
        names = list(self._histories.keys())
        if self._etfs:
            names.append("etfs")
        return sorted(names)

    def members(self, *, name: str, asof: date) -> set[str]:
        """Return the constituents of `name` active on `asof`.

        For `name="etfs"`, this returns the set of allowlisted tickers active
        on `asof` (i.e. listed_at <= asof < delisted_at-or-infinity).
        """
        if name == "etfs":
            return {ticker for ticker, e in self._etfs.items() if e.is_active(asof)}
        history = self._require_history(name)
        if asof < history.seed.seed_date:
            raise UniverseSchemaError(
                f"asof {asof} is before {name!r}'s seed_date {history.seed.seed_date}; "
                "the seed marks the earliest queryable date."
            )
        members = set(history.seed.members)
        for event in history.events:
            if event.date > asof:
                break  # events are sorted, can short-circuit
            if event.action is UniverseAction.ADD:
                members.add(event.ticker)
            else:  # REMOVE
                members.discard(event.ticker)
        return members

    def is_member(self, *, name: str, asof: date, ticker: str) -> bool:
        try:
            return ticker in self.members(name=name, asof=asof)
        except UniverseSchemaError:
            return False

    def history(self, *, name: str, ticker: str) -> list[UniverseEvent]:
        """Return all events that touched `ticker` in `name`, in chronological order."""
        if name == "etfs":
            return []
        history = self._require_history(name)
        return [e for e in history.events if e.ticker == ticker]

    def etf_allowlist(self, *, asof: date) -> list[UniverseEntry]:
        return sorted(
            (e for e in self._etfs.values() if e.is_active(asof)),
            key=lambda e: e.ticker,
        )

    # --- helpers ------------------------------------------------------

    def _require_history(self, name: str) -> _NamedHistory:
        try:
            return self._histories[name]
        except KeyError as exc:
            available = ", ".join(self.known_universes()) or "<none>"
            raise UniverseSchemaError(
                f"unknown universe {name!r} (available: {available})"
            ) from exc


# --- YAML parsing -------------------------------------------------------


def _load_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise UniverseSchemaError(f"invalid YAML at {path}: {exc}") from exc


def _parse_seed(path: Path, *, expected_name: str) -> UniverseSeed:
    body = _load_yaml(path)
    if not isinstance(body, dict):
        raise UniverseSchemaError(f"{path}: seed must be a mapping, got {type(body).__name__}")
    name = body.get("name")
    seed_date = body.get("seed_date")
    members = body.get("members") or []
    if name != expected_name:
        raise UniverseSchemaError(
            f"{path}: name field {name!r} disagrees with parent directory {expected_name!r}"
        )
    if not isinstance(seed_date, date):
        raise UniverseSchemaError(
            f"{path}: seed_date must be a YAML date, got {type(seed_date).__name__}"
        )
    if not isinstance(members, list) or not all(isinstance(m, str) for m in members):
        raise UniverseSchemaError(f"{path}: members must be a list of tickers")
    return UniverseSeed(name=name, seed_date=seed_date, members=frozenset(members))


def _parse_events(path: Path, *, expected_name: str) -> list[UniverseEvent]:
    if not path.exists():
        return []
    body = _load_yaml(path)
    if body is None:
        return []
    if not isinstance(body, dict):
        raise UniverseSchemaError(f"{path}: events file must be a mapping")
    if body.get("name") != expected_name:
        raise UniverseSchemaError(
            f"{path}: name field disagrees with parent directory {expected_name!r}"
        )
    raw_events = body.get("events") or []
    if not isinstance(raw_events, list):
        raise UniverseSchemaError(f"{path}: 'events' must be a list")
    parsed: list[UniverseEvent] = []
    for i, raw in enumerate(raw_events):
        if not isinstance(raw, dict):
            raise UniverseSchemaError(f"{path}: event #{i} is not a mapping")
        ev_date = raw.get("date")
        ticker = raw.get("ticker")
        action_raw = raw.get("action")
        note = raw.get("note") or ""
        if not isinstance(ev_date, date):
            raise UniverseSchemaError(f"{path}: event #{i} 'date' must be a YAML date")
        if not isinstance(ticker, str) or not ticker:
            raise UniverseSchemaError(f"{path}: event #{i} 'ticker' must be a non-empty string")
        try:
            action = UniverseAction(action_raw)
        except (TypeError, ValueError) as exc:
            raise UniverseSchemaError(
                f"{path}: event #{i} 'action' must be 'add' or 'remove', got {action_raw!r}"
            ) from exc
        parsed.append(
            UniverseEvent(date=ev_date, ticker=ticker, action=action, note=str(note))
        )
    return parsed


def _parse_etfs(path: Path) -> dict[str, UniverseEntry]:
    body = _load_yaml(path)
    if body is None:
        return {}
    if not isinstance(body, dict) or "tickers" not in body:
        raise UniverseSchemaError(f"{path}: top-level 'tickers' list required")
    raw = body["tickers"]
    if not isinstance(raw, list):
        raise UniverseSchemaError(f"{path}: 'tickers' must be a list")
    out: dict[str, UniverseEntry] = {}
    for i, row in enumerate(raw):
        if not isinstance(row, dict):
            raise UniverseSchemaError(f"{path}: row #{i} is not a mapping")
        ticker = row.get("ticker")
        listed_at = row.get("listed_at")
        delisted_at = row.get("delisted_at")
        category = row.get("category") or ""
        if not isinstance(ticker, str) or not ticker:
            raise UniverseSchemaError(f"{path}: row #{i} 'ticker' must be a non-empty string")
        if listed_at is not None and not isinstance(listed_at, date):
            raise UniverseSchemaError(
                f"{path}: row #{i} 'listed_at' must be a YAML date or null"
            )
        if delisted_at is not None and not isinstance(delisted_at, date):
            raise UniverseSchemaError(
                f"{path}: row #{i} 'delisted_at' must be a YAML date or null"
            )
        if ticker in out:
            raise UniverseSchemaError(f"{path}: duplicate ticker {ticker!r}")
        out[ticker] = UniverseEntry(
            ticker=ticker,
            listed_at=listed_at,
            delisted_at=delisted_at,
            category=str(category),
        )
    return out


# --- validation ---------------------------------------------------------


def _validate_history(seed: UniverseSeed, events: list[UniverseEvent]) -> None:
    """Catch malformed event sequences before they corrupt downstream membership lookups."""
    # Events must be sorted by date (loose: ties allowed, but global ordering enforced)
    last_date: date | None = None
    for i, ev in enumerate(events):
        if last_date is not None and ev.date < last_date:
            raise UniverseSchemaError(
                f"{seed.name}: event #{i} date {ev.date} precedes prior event {last_date}; "
                "events must be sorted by date"
            )
        last_date = ev.date
        if ev.date < seed.seed_date:
            raise UniverseSchemaError(
                f"{seed.name}: event #{i} for {ev.ticker} on {ev.date} predates "
                f"seed_date {seed.seed_date}"
            )

    # Replay events to detect double-add and remove-before-add
    members = set(seed.members)
    per_ticker_actions: dict[str, list[UniverseEvent]] = defaultdict(list)
    for ev in events:
        per_ticker_actions[ev.ticker].append(ev)
        if ev.action is UniverseAction.ADD:
            if ev.ticker in members:
                raise UniverseSchemaError(
                    f"{seed.name}: cannot add {ev.ticker!r} on {ev.date} — already a member"
                )
            members.add(ev.ticker)
        else:  # REMOVE
            if ev.ticker not in members:
                raise UniverseSchemaError(
                    f"{seed.name}: cannot remove {ev.ticker!r} on {ev.date} — not a member"
                )
            members.discard(ev.ticker)
