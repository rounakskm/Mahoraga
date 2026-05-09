"""Vault embargo helpers.

The vault is a rolling window covering the most recent N days (default 180,
i.e. roughly 6 months) of any time series. Reads inside that window are
blocked by `ParquetAdapter` so the live deployment in Phase 7+ has a
genuinely out-of-sample validation window.

See `docs/superpowers/specs/phase-1-foundation/vault-embargo-spec.md`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


class VaultEmbargoError(Exception):
    """Raised when a `read` request overlaps the vault without an explicit override."""

    def __init__(
        self,
        *,
        start: datetime,
        end: datetime,
        asof: datetime,
        vault_cutoff: datetime,
    ) -> None:
        self.start = start
        self.end = end
        self.asof = asof
        self.vault_cutoff = vault_cutoff
        super().__init__(
            f"requested window [{start.isoformat()}, {end.isoformat()}] overlaps "
            f"the vault (cutoff {vault_cutoff.isoformat()}, asof {asof.isoformat()}). "
            "Pass vault_override=True with a vault_override_reason if you really mean it."
        )


@dataclass(frozen=True)
class VaultDecision:
    """Outcome of `assess_vault`.

    - `enforced` is True when a `vault_cutoff_days` was configured.
    - `overlaps_vault` is True when `[start, end]` intersects the vault.
    - `cutoff_dt` is the datetime at the older boundary of the vault (i.e.
      `asof - timedelta(days=vault_cutoff_days)`); read-allowed range is
      `[bar_timestamp <= cutoff_dt]`.
    """

    enforced: bool
    overlaps_vault: bool
    cutoff_dt: datetime | None


def assess_vault(
    *,
    start: datetime,
    end: datetime,
    asof: datetime,
    vault_cutoff_days: int | None,
) -> VaultDecision:
    """Decide whether `[start, end]` intersects the vault relative to `asof`."""
    if vault_cutoff_days is None:
        return VaultDecision(enforced=False, overlaps_vault=False, cutoff_dt=None)
    if vault_cutoff_days < 0:
        raise ValueError(f"vault_cutoff_days must be >= 0, got {vault_cutoff_days}")
    cutoff = asof - timedelta(days=vault_cutoff_days)
    overlaps = end > cutoff  # any portion of the requested window is past the cutoff
    return VaultDecision(enforced=True, overlaps_vault=overlaps, cutoff_dt=cutoff)
