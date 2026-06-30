"""Hindsight memory client (Phase-3 Layer-3) — retain / recall / reflect.

Hindsight (bank `mahoraga-trader`) is the system's memory layer: Experience Facts
(iteration outcomes, trade contexts), World Facts, Observations, Mental Models.
This is a thin REST client against the compose `hindsight` service on `:8888`.

Graceful-offline is the load-bearing contract (CLAUDE.md: every external dependency
degrades gracefully, the `ProvenanceWriter(dsn=None)` / `LLMMutator` fallback being
the template). `base_url=None` → disabled: every method is a no-op returning the
empty default. An *unreachable* endpoint behaves identically — the httpx call is
wrapped in try/except (mirroring `llm.py`) so a flaky or down Hindsight never stalls
or crashes the loop. No network is touched when disabled.
"""

from __future__ import annotations

import httpx


class HindsightClient:
    """REST client for Hindsight; safe no-op when `base_url` is None/unreachable."""

    def __init__(
        self,
        base_url: str | None = None,
        bank: str = "mahoraga-trader",
        *,
        timeout: float = 5.0,
    ) -> None:
        self.base_url = base_url.rstrip("/") if base_url else None
        self.bank = bank
        self.timeout = timeout

    def is_enabled(self) -> bool:
        return self.base_url is not None

    # --- public surface -----------------------------------------------------

    def retain(self, text: str, metadata: dict | None = None) -> str | None:
        """Store an Experience Fact; returns its id, or None when disabled/unreachable."""
        if not self.is_enabled():
            return None
        try:
            resp = self._post(
                f"/banks/{self.bank}/facts",
                {"text": text, "metadata": metadata or {}, "bank": self.bank},
            )
        except Exception:  # network / HTTP / parse error -> never stall the loop
            return None
        return resp.get("id") if isinstance(resp, dict) else None

    def recall(self, query: str, k: int = 5) -> list[dict]:
        """Semantic recall; returns the result dicts, or [] when disabled/unreachable."""
        if not self.is_enabled():
            return []
        try:
            resp = self._get(
                f"/banks/{self.bank}/recall",
                {"query": query, "k": k, "bank": self.bank},
            )
        except Exception:
            return []
        results = resp.get("results") if isinstance(resp, dict) else None
        return results if isinstance(results, list) else []

    def reflect(self) -> None:
        """Trigger consolidation (Observations/Mental Models); no-op when disabled."""
        if not self.is_enabled():
            return
        try:
            self._post(f"/banks/{self.bank}/reflect", {"bank": self.bank})
        except Exception:  # network / HTTP error -> silent no-op, never stall
            return

    # --- transport (overridable in tests) -----------------------------------

    def _post(self, path: str, payload: dict) -> dict:
        resp = httpx.post(f"{self.base_url}{path}", json=payload, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def _get(self, path: str, params: dict) -> dict:
        resp = httpx.get(f"{self.base_url}{path}", params=params, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()
