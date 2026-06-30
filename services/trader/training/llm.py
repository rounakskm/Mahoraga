"""LLM mutator (Phase 3, Layer 2) — Nemotron proposes regime-conditional mutations.

Replaces the mechanical hill-climb: an LLM reads the current best strategy + the
recent attempt history (what was promoted / rejected and why) and proposes the next
per-regime SMA windows. The fortress + vault still judge every proposal and
provenance records it — the LLM explores smarter without bypassing any guard.

Robustness: any failure (network, bad JSON, out-of-range, wrong keys) falls back to
the mechanical mutation, so a flaky or hallucinating LLM never stalls or corrupts
the loop. Calls an OpenAI-compatible chat endpoint — NVIDIA Build by default; set
MAHORAGA_LLM_BASE_URL to route through the LiteLLM gateway instead.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Sequence

import httpx

from services.trader.training.strategy_template import (
    ADX_T_MAX,
    ADX_T_MIN,
    REGIMES,
    VOL_T_MAX,
    VOL_T_MIN,
    WINDOW_MAX,
    WINDOW_MIN,
    RegimeConditionalStrategy,
)

_SYSTEM = (
    "You optimize a regime-conditional SPY strategy. In each regime "
    "(trending_low_vol, trending_high_vol, ranging_low_vol, ranging_high_vol) it holds "
    "SPY when price is above that regime's SMA window, else stays flat. Windows are "
    f"integers in [{WINDOW_MIN},{WINDOW_MAX}]; larger = slower / longer trends, smaller = "
    "faster reaction. Propose ONE improved set of windows to raise the Sharpe ratio "
    "while staying robust to overfitting. Respond with ONLY a JSON object mapping the "
    "4 regimes to integers — no prose, no markdown."
)

# When the detector is also learnable, the LLM additionally tunes the two MESO
# thresholds that decide which regime each bar is in (trend vs ADX, vol split).
_SYSTEM_DETECTOR = (
    _SYSTEM[:-len(" — no prose, no markdown.")]
    + f", plus two extra keys: adx_threshold (float in [{ADX_T_MIN},{ADX_T_MAX}]: the ADX "
    f"level above which a bar is 'trending') and vol_threshold (float in [{VOL_T_MIN},"
    f"{VOL_T_MAX}]: the realized-vol percentile splitting low/high vol). Tuning these "
    "changes the regime labels themselves. Respond with ONLY a JSON object with the 4 "
    "regime keys plus adx_threshold and vol_threshold — no prose, no markdown."
)


class LLMMutator:
    """Callable mutator: (current, iterations, rng) -> RegimeConditionalStrategy."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        temperature: float = 0.7,
        learn_detector: bool = False,
    ) -> None:
        self.learn_detector = learn_detector
        self.base_url = (
            base_url
            or os.environ.get("MAHORAGA_LLM_BASE_URL")
            or "https://integrate.api.nvidia.com/v1"
        ).rstrip("/")
        self.api_key = api_key or os.environ.get("NVIDIA_API_KEY", "")
        self.model = model or os.environ.get(
            "MAHORAGA_LLM_MODEL", "nvidia/nemotron-3-super-120b-a12b"
        )
        self.temperature = temperature

    def __call__(self, current, iterations: Sequence, rng) -> RegimeConditionalStrategy:
        try:
            cand = self._validate(self._parse(self._chat(self._user_prompt(current, iterations))))
            if cand is not None and cand != current:  # any field moved (windows or thresholds)
                return cand
        except Exception:  # network / parse / API error -> never stall the loop
            pass
        return current.mutate(rng, mutate_detector=self.learn_detector)  # mechanical fallback

    def _user_prompt(self, current, iterations: Sequence) -> str:
        hist = (
            "; ".join(
                f"{it.windows} -> "
                + (f"promoted {it.sharpe:.4f}" if it.promoted else f"rejected ({it.reason[:40]})")
                for it in list(iterations)[-6:]
            )
            or "none yet"
        )
        detector = (
            f" Current detector: adx_threshold={current.adx_threshold}, "
            f"vol_threshold={current.vol_threshold}."
            if self.learn_detector else ""
        )
        return (
            f"Current best windows: {json.dumps(current.windows)}.{detector} "
            f"Recent attempts: {hist}. Propose the next configuration as a JSON object."
        )

    def _chat(self, user: str) -> str:
        resp = httpx.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "temperature": self.temperature,
                "max_tokens": 900,
                "messages": [
                    {"role": "system",
                     "content": _SYSTEM_DETECTOR if self.learn_detector else _SYSTEM},
                    {"role": "user", "content": user},
                ],
            },
            timeout=90,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"].get("content") or ""

    @staticmethod
    def _parse(text: str) -> dict:
        match = re.search(r"\{[^{}]*\}", text)  # flat JSON object
        return json.loads(match.group(0)) if match else {}

    def _validate(self, params: dict) -> RegimeConditionalStrategy | None:
        extra = {"adx_threshold", "vol_threshold"} if self.learn_detector else set()
        if set(params) != set(REGIMES) | extra:
            return None
        try:
            windows = {k: int(round(float(params[k]))) for k in REGIMES}
        except (TypeError, ValueError):
            return None
        if any(not (WINDOW_MIN <= w <= WINDOW_MAX) for w in windows.values()):
            return None
        if not self.learn_detector:
            return RegimeConditionalStrategy(windows)
        try:  # thresholds are clamped (not rejected) — keep a usable proposal
            adx = min(ADX_T_MAX, max(ADX_T_MIN, float(params["adx_threshold"])))
            vol = min(VOL_T_MAX, max(VOL_T_MIN, float(params["vol_threshold"])))
        except (TypeError, ValueError):
            return None
        return RegimeConditionalStrategy(windows, adx_threshold=adx, vol_threshold=vol)
