# Phase 1 — Regime Detector Spec (sub-feature 5)

**Status:** Drafted 2026-05-11
**Parent:** [`spec.md`](spec.md), [`plan.md`](plan.md), [`tasks.md`](tasks.md)
**Predecessors:** P1.1 data-foundation (merged), P1.2 universe (merged), P1.3 vault embargo (merged), P1.4 feature pipeline (merged)
**Owner stream:** C (regime) — sits on top of the feature pipeline output

---

## 1. Goal

Produce a daily, PIT-correct **composite regime label** plus a `0.0–1.0`
**confidence score** for the US-equity universe, derived from the
features the pipeline emits. The output is the input to every Phase-3+
strategy-selection decision and to the Phase-7 hard-limit firewall (no
new entries when `confidence < 0.40`).

Per the project plan §4, regime is tracked at three timescales (MACRO,
MESO, MICRO). Phase 1 scope here is **MACRO + MESO only** — both fit
daily-bar inputs. MICRO needs intraday data and is deferred to Phase 4
when the news/options/intraday-feed work begins.

By exit, downstream code can call:

```python
from services.trader.regime import RegimeDetector
detector = RegimeDetector(feature_store=store, macro_adapter=adapter)
state = detector.classify(asof=datetime(2026, 5, 11, tzinfo=UTC))
# state.label == CompositeRegime(macro="bull", meso="trending_low_vol")
# state.confidence == 0.72
```

Re-running on the same inputs is deterministic; PIT correctness is
inherited from the feature/macro reads.

## 2. Regime taxonomy

### MACRO lens (3 labels, project-plan §4)

- `bull` — risk-on backdrop (e.g. positive 2s10s slope, declining VIX
  trailing, DXY weakening)
- `bear` — risk-off backdrop (e.g. inverted curve, elevated VIX,
  rising DXY)
- `transitioning` — at least one MACRO signal in the opposite direction
  of the others; confidence drops accordingly

Update cadence: weekly in production; per-day in backtests.

### MESO lens (4 labels — 2×2 cross of trend × vol)

- `trending_low_vol` — ADX-14 ≥ 25 **AND** `realized_vol_pct_60 ≤ 0.40`
- `trending_high_vol` — ADX-14 ≥ 25 **AND** `realized_vol_pct_60 > 0.40`
- `ranging_low_vol` — ADX-14 < 25 **AND** `realized_vol_pct_60 ≤ 0.40`
  (mean-reverting environment)
- `ranging_high_vol` — ADX-14 < 25 **AND** `realized_vol_pct_60 > 0.40`
  (choppy environment)

Update cadence: daily.

### Composite label

`CompositeRegime(macro: str, meso: str)` — a value type with both
labels and a derived numeric `confidence` (next section). Phase 1 keeps
the MICRO slot empty for forward compatibility; the dataclass has it as
`Optional[str] = None`.

## 3. Confidence score (0.0–1.0)

Confidence is a function of how cleanly the inputs fall inside the rule
buckets. Each lens contributes a per-lens confidence; the composite
confidence is the **minimum** of the two (a conservative rule: when
either lens is uncertain, the composite is uncertain).

### MESO confidence

For each axis (trend, vol), compute the distance to the threshold:

- Trend axis: `meso_trend_conf = clip((adx_14 - 25) / 25, -1, 1)`. Sign
  encodes direction; magnitude encodes how far from the threshold.
- Vol axis: `meso_vol_conf = clip((realized_vol_pct_60 - 0.40) / 0.40, -1, 1)`.

MESO confidence:
`meso_conf = min(abs(meso_trend_conf), abs(meso_vol_conf))` ∈ [0, 1].

### MACRO confidence

Three binary signals contribute:
- `curve_signal`: +1 if `yield_2s10s > 0`, −1 if inverted
- `vix_signal`: +1 if `vix_level < 18` (low-fear), −1 if `vix_level > 25`
- `dxy_signal`: +1 if `dxy_change_20d < 0` (USD weakening), −1 otherwise

`macro_score = (curve_signal + vix_signal + dxy_signal) / 3` ∈ [-1, 1].

- `bull` when `macro_score >= 0.50`
- `bear` when `macro_score <= -0.50`
- `transitioning` otherwise

`macro_conf = abs(macro_score)`.

### Composite confidence

`composite_conf = min(meso_conf, macro_conf)`.

Phase 1 acceptance:
- Confidence sits in `[0, 1]` for every output row.
- A flat-line synthetic series (ADX → 0, vol → median) produces
  `composite_conf < 0.20` → demonstrably uncertain.
- A clean bull-trend synthetic series (ADX > 50, vol percentile < 0.2,
  flat yield curve, low VIX) produces `composite_conf > 0.80`.

## 4. Architecture

```
services/trader/regime/
├── __init__.py            public RegimeDetector + CompositeRegime types
├── base.py                Lens ABC + ClassificationResult + CompositeRegime dataclass
├── meso.py                MesoLens (rule-based, uses ADX + realized_vol_pct_60)
├── macro.py               MacroLens (rule-based, uses 2s10s + VIX + DXY)
├── detector.py            RegimeDetector orchestrator (composes lenses)
├── store.py               RegimeStore parquet writer + PIT read
└── tests/                 per-lens unit tests + composite integration tests
```

Storage layout (mirrors features + OHLCV):

```
data/parquet/regime/
└── <SCOPE>/                   "universe" for portfolio-wide, or <TICKER> for per-name lenses
    └── <YEAR>.parquet
```

Schema:

```
scope:                string             non-null   "universe" or ticker
asof:                 timestamp[us, UTC] non-null
macro_label:          string             non-null   bull|bear|transitioning
meso_label:           string             non-null   trending_low_vol|trending_high_vol|ranging_low_vol|ranging_high_vol
macro_conf:           float64            non-null   [0, 1]
meso_conf:            float64            non-null   [0, 1]
composite_conf:       float64            non-null   min(meso_conf, macro_conf)
inputs:               map<string,float>  null OK    raw feature values that drove the labels (audit)
source:               string             non-null   "regime-detector"
fetched_at:           timestamp[us, UTC] non-null
```

The `inputs` column lets a reviewer reconstruct exactly which feature
values produced each label without re-reading the feature store. It is
the regime detector's audit trail; the hash-chained `audit.events` row
covers run-level integrity.

## 5. Lens ABC

```python
class Lens(ABC):
    name: str                            # "macro" | "meso" | "micro"

    @abstractmethod
    def required_features(self) -> list[str]:
        """Feature column names this lens needs from the feature store."""

    @abstractmethod
    def classify(
        self,
        *,
        feature_row: pd.Series,
        macro_row: pd.Series | None,
    ) -> ClassificationResult:
        """Return (label, confidence, inputs_snapshot) for one bar."""
```

`ClassificationResult`:

```python
@dataclass(frozen=True)
class ClassificationResult:
    label: str
    confidence: float                    # [0, 1]
    inputs: dict[str, float]             # feature_name → value
```

Constraints:

- **Pure function of inputs.** No filesystem / network / global reads
  inside `classify`. The detector wires the feature/macro reads in
  the orchestrator and passes already-PIT-correct rows down.
- **NaN-safe.** If any required feature is `null` for the bar, the
  lens returns `confidence=0.0` and `label="undefined"`; the
  detector surfaces the gap in the manifest.

## 6. Detector orchestrator

```python
class RegimeDetector:
    def __init__(
        self,
        *,
        feature_store: FeatureStore,
        macro_adapter: ParquetAdapter,
        store: RegimeStore | None = None,
        lenses: list[Lens] | None = None,
        manifest_root: str | None = None,
        audit_writer: PostgresAuditWriter | None = None,
        audit_actor: str = "regime-detector",
    ) -> None: ...

    def classify(
        self,
        *,
        scope: str = "universe",
        asof: datetime,
        start: date | None = None,
        end: date | None = None,
    ) -> RegimeRunResult: ...
```

Algorithm:

1. Read the feature row(s) at `asof` from the feature store, restricted
   to the features named by `Lens.required_features()` across all
   active lenses (deduplicated).
2. Read the macro row(s) at `asof` from `macro_adapter`.
3. For each lens, call `classify(feature_row, macro_row)`; collect
   `ClassificationResult`s.
4. Compose `CompositeRegime(macro, meso, composite_conf=min(...))`.
5. Write a row per `(scope, asof)` to `RegimeStore`.
6. Emit a manifest row + hash-chained `audit.events` row identical in
   shape to the feature-pipeline manifest (P1.4 F5).

The orchestrator reuses `ManifestWriter` + `PostgresAuditWriter` from
P1.1 / P1.4 — no new audit chokepoint. Idempotent re-runs dedupe on
`(scope, asof)` keeping the row with the latest `fetched_at`.

## 7. Substrate-portability + PIT discipline + audit

- Pure Python at `services/trader/regime/`. No NemoClaw imports.
- Each run writes a hash-chained `audit.events` row with
  `actor='regime-detector'`, `action='classify'`, payload covering
  `(scope, window, lens names, confidence stats)`.
- Hindsight ingestion (Phase 3+): each regime transition becomes a
  World Fact in the `mahoraga-trader` bank — out of scope here, but
  the manifest schema is forward-compatible.

PIT: the detector reads features and macro via the same vault-aware
adapters the rest of P1 uses. `asof` is mandatory at the public entry
point; internal reads pass it down unchanged.

## 8. Acceptance / exit criteria

- ✅ `services/trader/regime/` package exists with the layout in §4
- ✅ `Lens` ABC + `MesoLens` + `MacroLens` + `RegimeDetector`
- ✅ Per-lens unit tests with synthetic inputs covering every label
  bucket + the undefined-on-null path
- ✅ Composite confidence test: flat synthetic → low; clean bull →
  high; clear bear → high (sign-flipped)
- ✅ Re-runs idempotent on `(scope, asof)`; later run wins on
  `fetched_at`
- ✅ Integration test under Postgres: full path feature pipeline →
  regime detector → parquet + manifest + audit-events; hash chain
  verifies end-to-end
- ✅ Vault embargo blocks recent windows; override path requires
  reason
- ✅ All tests in `tests/integration/phase-1/regime/` green in CI

## 9. Open questions

| Question | Default if undecided |
|---|---|
| Per-ticker regime vs universe regime in Phase 1 | Universe-level only (scope=`"universe"`). Per-ticker regimes ride on the same machinery but ship in Phase 3 when strategy selection needs them. |
| HMM / clustering vs rule-based | Rule-based for Phase 1. State-of-art HMM/regime-switching models ship in Phase 4 once we have label noise data to fit against. Rule-based is interpretable and fail-loud. |
| What to do when `realized_vol_pct_60` is NaN (warmup) | Lens returns `undefined / 0.0` for that bar; the manifest records the gap. Same convention as feature-pipeline coverage. |
| MICRO lens stub in Phase 1 | None. The composite dataclass has an optional MICRO slot for forward compatibility, but Phase 1 ships no MICRO lens implementation. |
| Confidence calibration against expert labels | Out of scope for Phase 1 (no labeled dataset yet). Phase 3 backtest harness will supply the labels via synthetic regime injection; Phase 4 calibrates against them. |

## 10. Plan summary (four chunks)

| # | Branch | What |
|---|---|---|
| R1 | `phase-1-regime-skeleton` | Lens ABC + CompositeRegime + RegimeDetector skeleton + MESO lens + per-lens tests |
| R2 | `phase-1-regime-macro` | MACRO lens + composite confidence wiring + per-lens tests |
| R3 | `phase-1-regime-store-and-audit` | RegimeStore parquet writer + manifest + audit-events integration |
| R4 | `phase-1-regime-integration` | End-to-end integration test (feature pipeline → regime) + CI extension |

Each chunk lands as its own PR per the cadence in `plan.md` §7. P1.6
(backtest harness) waits on R4.

## 11. Risks specific to this sub-feature

- **Threshold drift** — rule-based thresholds (ADX=25, vol percentile=0.40, etc.) may misclassify historical regimes. Mitigation: a `tests/integration/phase-1/regime/test_known_regimes.py` fixture asserts labels for hand-picked windows (2020-Q1 = `bear / trending_high_vol`, 2017-summer = `bull / ranging_low_vol`, 2018-Q4 = `transitioning`). Move thresholds only with a justifying commit.
- **NaN cascade from feature warmup** — first ~60 bars after a ticker enters the universe have `realized_vol_pct_60 == NaN`. Mitigation: lens returns `undefined / 0.0`; the detector logs and continues; downstream code is built to treat `undefined` as a halt-new-entries signal.
- **Audit chain breaks when classification runs in parallel** — a single hash chain doesn't tolerate concurrent writers. Mitigation: Phase 1 runs the detector serially; Phase 3 introduces a per-actor chain shard if parallelism becomes load-bearing.
- **Composite confidence collapses to 0 when one lens is undefined** — by design (`min` rule). Document loudly; the operator notices when MACRO has no data.
