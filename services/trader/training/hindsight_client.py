"""Hindsight memory client (Phase-3 Layer-3) — retain / recall / reflect.

Hindsight (bank `mahoraga-trader`) is the system's memory layer: Experience Facts
(iteration outcomes, trade contexts), World Facts, Observations, Mental Models.
This is a thin REST client against the compose `hindsight` service on `:8888`,
bound to the REAL vendored API surface
(`vendor/hindsight/hindsight-api-slim/hindsight_api/api/http.py`):

- retain:  POST /v1/default/banks/{bank_id}/memories          body {"items": [...]}
- recall:  POST /v1/default/banks/{bank_id}/memories/recall   body {"query": ...}
- reflect: POST /v1/default/banks/{bank_id}/reflect           body {"query": ...}

Graceful-offline is the load-bearing contract (CLAUDE.md: every external dependency
degrades gracefully, the `ProvenanceWriter(dsn=None)` / `LLMMutator` fallback being
the template). `base_url=None` → disabled: every method is a no-op returning the
empty default. An *unreachable* endpoint behaves identically — the httpx call is
wrapped in try/except (mirroring `llm.py`) so a flaky or down Hindsight never stalls
or crashes the loop; the FIRST failed call logs a warning (once) so an outage is
visible instead of silent. No network is touched when disabled.
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_REFLECT_QUERY = (
    "Consolidate recent trading experience into observations and mental models."
)


class HindsightClient:
    """REST client for Hindsight; safe no-op when `base_url` is None/unreachable."""

    def __init__(
        self,
        base_url: str | None = None,
        bank: str = "mahoraga-trader",
        *,
        timeout: float = 60.0,
    ) -> None:
        self.base_url = base_url.rstrip("/") if base_url else None
        self.bank = bank
        self.timeout = timeout
        self._warned = False

    def is_enabled(self) -> bool:
        return self.base_url is not None

    def _warn_once(self, op: str, exc: Exception) -> None:
        """One-time visibility for an outage; subsequent failures stay quiet."""
        if not self._warned:
            self._warned = True
            logger.warning(
                "hindsight %s failed (degrading to no-op; further failures "
                "silent): %s",
                op,
                exc,
            )

    # --- public surface -----------------------------------------------------

    def retain(self, text: str, metadata: dict | None = None) -> str | None:
        """Store an Experience Fact. Returns a non-None marker (the operation id
        when the server hands one back, else "ok") on success; None when
        disabled/unreachable. Metadata values are coerced to strings (the API's
        `metadata: dict[str, str]` schema)."""
        if not self.is_enabled():
            return None
        item: dict = {"content": text}
        if metadata:
            item["metadata"] = {k: str(v) for k, v in metadata.items()}
        try:
            resp = self._post(
                f"/v1/default/banks/{self.bank}/memories", {"items": [item]}
            )
        except Exception as exc:  # network / HTTP / parse error -> never stall
            self._warn_once("retain", exc)
            return None
        if not isinstance(resp, dict):
            return None
        if resp.get("operation_id"):
            return str(resp["operation_id"])
        return "ok" if resp.get("success") else None

    def recall(self, query: str, k: int = 5) -> list[dict]:
        """Semantic recall; returns up to `k` result dicts (each may carry the
        user metadata under `metadata`), or [] when disabled/unreachable."""
        if not self.is_enabled():
            return []
        try:
            resp = self._post(
                f"/v1/default/banks/{self.bank}/memories/recall", {"query": query}
            )
        except Exception as exc:
            self._warn_once("recall", exc)
            return []
        results = resp.get("results") if isinstance(resp, dict) else None
        return results[:k] if isinstance(results, list) else []

    def reflect(self, query: str = _DEFAULT_REFLECT_QUERY) -> None:
        """Trigger a reflect pass (Observations/Mental Models); no-op when disabled.
        The real endpoint requires a `query`; the default asks for consolidation."""
        if not self.is_enabled():
            return
        try:
            self._post(f"/v1/default/banks/{self.bank}/reflect", {"query": query})
        except Exception as exc:  # network / HTTP error -> no-op, never stall
            self._warn_once("reflect", exc)

    # --- transport (overridable in tests) -----------------------------------

    def _post(self, path: str, payload: dict) -> dict:
        resp = httpx.post(f"{self.base_url}{path}", json=payload, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()
