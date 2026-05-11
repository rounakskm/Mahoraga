# Phase 1 — Backtest Harness Spec (sub-feature 6)

**Status:** Drafted 2026-05-11
**Parent:** [`spec.md`](spec.md), [`plan.md`](plan.md), [`tasks.md`](tasks.md)
**Predecessors:** P1.1 data-foundation, P1.2 universe, P1.3 vault embargo, P1.4 feature pipeline, P1.5 regime detector (all merged)
**Closes:** Phase 1

---

## 1. Goal

Ship a **vectorized, PIT-correct, hard-limit-aware backtest skeleton**
that takes a `Strategy`, reads features + regime classifications via
the PIT primitives, applies signals to OHLCV, and emits a
`FitnessReport`. Phase 1 deliverable is a working skeleton + a stub
buy-and-hold strategy; Phase 3+ extends with the autoresearch loop's
mutation engine.

Phase 1 deliberately uses **pure pandas / numpy** for the engine —
vectorbt (the original sketch in `spec.md`) introduces a heavy C
dependency that doesn't justify itself at this scope. The engine has
two responsibilities: convert per-bar signals to a position series,
and track PnL. Phase 2 can swap the engine for vectorbt if the
overnight-experiment budget needs the throughput.

By exit, downstream code can call:

```python
from services.trader.backtest import Backtest, BuyAndHold
from services.trader.features import FeatureStore
from services.trader.regime import RegimeStore

bt = Backtest(
    feature_store=FeatureStore("data/parquet"),
    regime_store=RegimeStore("data/parquet"),
    ohlcv_adapter=ParquetAdapter("data/parquet"),
)
report = bt.run(
    strategy=BuyAndHold(),
    universe=["SPY", "QQQ"],
    start=date(2020, 1, 1),
    end=date(2025, 12, 31),
)
print(report.total_return, report.sharpe, report.max_drawdown)
```

Re-running on the same inputs is deterministic; PIT correctness is
inherited from the underlying stores.

## 2. Strategy ABC

```python
class Strategy(ABC):
    name: str
    requires_features: list[str]               # feature column names
    allow_placeholder_features: bool = False   # P1.4 sentiment gate

    @abstractmethod
    def generate_signals(
        self,
        *,
        feature_frame: pd.DataFrame,           # one row per (ticker, bar)
        regime_frame: pd.DataFrame,            # one row per (scope, asof)
    ) -> pd.DataFrame:
        """Return per-bar position weights in [-1, 1] per ticker.

        Columns: ticker, bar_timestamp, target_weight. The engine
        converts these to trade fills, applies risk limits, and tracks
        PnL.
        """
```

Constraints (enforced by the harness, not the strategy):

- **PIT correctness.** Strategies receive frames already filtered to
  the requested asof; they cannot peek into the future.
- **No look-ahead.** Signals at bar T must be computable from rows ≤ T.
  The harness applies a one-bar execution lag (`target_weight[T]`
  becomes the position held at the close of bar `T+1`).
- **Placeholder gate.** If `requires_features` contains any column
  with `placeholder=True` (sentiment_score in Phase 1) and
  `allow_placeholder_features` is `False`, the harness rejects the
  strategy at scoring time. Forces Phase 4 to ship real sentiment
  before any sentiment-dependent strategy can train.

## 3. Backtest engine

```python
class Backtest:
    def __init__(
        self,
        *,
        feature_store: FeatureStore,
        regime_store: RegimeStore,
        ohlcv_adapter: ParquetAdapter,
        initial_capital: float = 1_000_000.0,
        commission_bps: float = 1.0,            # 1 basis point per trade
        slippage_bps: float = 5.0,
    ) -> None: ...

    def run(
        self,
        *,
        strategy: Strategy,
        universe: list[str],
        start: date,
        end: date,
        asof: datetime | None = None,
        regime_scope: str = "universe",
    ) -> FitnessReport: ...
```

Algorithm:

1. Validate the strategy: check `requires_features` against the
   registry; reject if it has placeholder features without the opt-in.
2. Read PIT-correct OHLCV (`ohlcv_adapter.read(kind="ohlcv", asof, ...)`),
   features (`feature_store.read(asof, features=...)`), and regime
   (`regime_store.read(scopes=[regime_scope], asof, lens_names=...)`)
   for the universe + window.
3. Call `strategy.generate_signals(feature_frame, regime_frame)` →
   per-bar target weights.
4. Apply a **one-bar execution lag**: weights at bar `T` become
   positions held at close of bar `T+1`.
5. Apply **risk limits** (next section) — clip per-position and
   per-sector weights, skip new entries on halt conditions.
6. Mark-to-market against close prices; track daily PnL.
7. Apply commission + slippage costs on trades.
8. Compute `FitnessReport` (next section).

## 4. Risk-limit firewall (Phase-1 stub)

The architecture spec calls for **infrastructure-level** hard limits;
Phase 7 lives them at the execution boundary in production. Phase 1's
backtest harness enforces a subset in code so the project plan's
guard-rails are exercised end-to-end during training:

| Limit | Phase 1 enforcement |
|---|---|
| Max single position 5% | Clip per-ticker target weight to ±0.05 |
| Max sector exposure 20% | Clip per-sector aggregate weight to ±0.20 (sector mapping stub — defaults to "unknown") |
| Daily loss halt 2% | Block new entries on any day where the prior day's PnL ≤ -2% |
| Regime confidence < 40% | Halt new entries on any bar where `regime_frame.composite_conf < 0.40` |
| Stop-loss 2× ATR | Stub: not yet enforced; documented for Phase 3 |
| Catastrophic loss 10% monthly | Stub: emits a `FitnessReport.halted_at` timestamp when trailing-30-day drawdown ≤ -10% |

The "Phase-1 enforcement" column is what lands in code for this
sub-feature. Phase 7's firewall is the production-grade version.

## 5. FitnessReport

```python
@dataclass(frozen=True)
class FitnessReport:
    strategy: str
    start: date
    end: date
    total_return: float                  # final equity / initial - 1
    sharpe: float                        # annualized
    max_drawdown: float                  # negative number
    num_trades: int
    win_rate: float
    halted_at: datetime | None           # if catastrophic-loss limit fired
    per_regime: dict[str, dict[str, float]]
    rejected_reason: str | None          # placeholder-features gate, etc.
```

The `per_regime` dict carries `{meso_label: {"return": ..., "sharpe":
..., "n_bars": ...}}` so the strategy registry (Phase 3+) can pick
the best-fit strategy per regime without re-running the backtest.

## 6. Architecture

```
services/trader/backtest/
├── __init__.py            public Backtest + Strategy + FitnessReport
├── base.py                Strategy ABC + FitnessReport dataclass
├── engine.py              Backtest orchestrator (PnL math, lag, costs)
├── risk.py                Hard-limit firewall (clip + halt rules)
├── strategies.py          BuyAndHold stub strategy
└── tests/                 per-component unit tests + an end-to-end test
```

The engine is substrate-portable Python; no NemoClaw / OpenClaw /
OpenShell imports. The `audit-xls` reviewer prompt at
`services/trader/prompts/reviewer/audit-xls.md` catches look-ahead
bias on every backtest output (already merged).

## 7. Acceptance / exit criteria

- ✅ `services/trader/backtest/` package exists with the layout in §6
- ✅ `Strategy` ABC + `BuyAndHold` stub
- ✅ `Backtest.run()` returns a `FitnessReport` for the stub on
  synthetic SPY data in <30 s
- ✅ Placeholder-features gate rejects a strategy that requires
  `sentiment_score` without `allow_placeholder_features=True`
- ✅ Hard-limit clipping unit tests prove per-position 5% cap +
  per-sector 20% cap behave correctly under contrived signals
- ✅ One-bar execution lag verified by a fixture: signal at T is
  executed at close of T+1
- ✅ Integration test under Postgres + Phase-1 stores: full chain
  ingest → features → regime → backtest produces a non-trivial report
  + emits one `audit.events` row with `actor='backtest-harness'`,
  `action='run'`

## 8. Open questions

| Question | Default if undecided |
|---|---|
| Vectorbt vs pure pandas engine | Pure pandas for Phase 1; Phase 2 reconsiders if throughput matters |
| Sector mapping source | Stub: all tickers map to "unknown" until Phase 3 wires real GICS metadata (out of P1.6 scope) |
| Strategy parameter grids in Phase 1 | No grid search yet — that's the autoresearch loop's job (Phase 3); P1.6 ships a single strategy run |
| Cross-sectional vs time-series strategy frames | Engine accepts both; signals can target any subset of the universe at any bar |
| Reading regime per-ticker vs scope | Phase 1: `regime_scope="universe"` (the only scope written by P1.5). Phase 3+ adds per-ticker regimes. |

## 9. Plan summary (three chunks)

| # | Branch | What |
|---|---|---|
| B1 | `phase-1-backtest-skeleton` | Strategy ABC + FitnessReport + BuyAndHold stub + tests for ABC contract / placeholder-features gate |
| B2 | `phase-1-backtest-engine-and-risk` | Backtest engine + risk-limit firewall (clip + halt) + per-component unit tests |
| B3 | `phase-1-backtest-integration` | End-to-end integration test (ingest → features → regime → backtest) + audit-events row + CI extension. Closes Phase 1. |

Each chunk lands as its own PR per the P1.1 / P1.4 / P1.5 cadence.

## 10. Risks specific to this sub-feature

- **Look-ahead bug in the engine.** Mitigation: dedicated
  `test_no_lookahead.py` fixture injects a "future" sentinel at bar
  `T+1`; if the strategy's PnL at bar T depends on it, the test
  catches it. The audit-xls reviewer also runs on every report.
- **Risk-limit math is subtle.** Mitigation: per-clip + per-halt
  fixtures with hand-derived expected outputs.
- **Vault-aware reads in backtest mode.** Mitigation: backtest reads
  are always inside the vault by definition (training data); the
  default is `vault_override=True` with reason
  `"backtest-training-window"` recorded on every run. Live trading
  (Phase 5+) does not override; that boundary is enforced in the
  Phase-7 firewall.
- **Pandas vs vectorbt drift.** Out of scope; if Phase 2 swaps the
  engine, FitnessReport stays the contract.
