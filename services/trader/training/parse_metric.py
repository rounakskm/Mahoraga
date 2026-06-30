"""Deterministic FitnessReport from a kernel EvalResult — the stable record the
promote pipeline + notebook + Hindsight all key on. No LLM, pure serialization."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

from services.trader.training.eval import EvalResult
from services.trader.training.provenance import candidate_hash


@dataclass(frozen=True)
class FitnessReport:
    candidate_hash: str
    params: dict
    sharpe: float
    fitness: float
    quarterly_win_rate: float
    max_drawdown: float
    promoted: bool
    reason: str

def report_from_eval(ev: EvalResult, params: dict) -> FitnessReport:
    f = ev.fitness
    return FitnessReport(
        candidate_hash(params), dict(params), float(ev.sharpe), float(f.score),
        float(f.quarterly_win_rate), float(f.max_drawdown),
        bool(ev.report.promoted), ev.report.reason,
    )

def report_hash(r: FitnessReport) -> str:
    payload = {k: v for k, v in asdict(r).items() if k != "params"}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]
