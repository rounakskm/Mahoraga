"""Backtest engine (P1.6 B2).

Pure pandas / numpy. Reads PIT-correct OHLCV + features + regime from
the Phase-1 stores, calls `Strategy.generate_signals`, applies the
hard-limit firewall, and emits a `FitnessReport`.

Algorithm per `backtest-harness-spec.md` §3:

1. Validate the strategy against the placeholder-feature gate.
2. Read OHLCV + features + regime at `asof`.
3. Build wide weight frame from signals (rows = bar_timestamp,
   cols = ticker).
4. Apply per-position + per-sector clips.
5. One-bar execution lag — held positions at bar T are the clipped
   weights from bar T-1.
6. Apply halts (regime confidence, prior-day daily loss). Halts zero
   the *held* position for the bar.
7. Mark-to-market against close prices; compute portfolio returns.
8. Apply commission + slippage on weight changes.
9. Compute catastrophic-loss halt timestamp.
10. Assemble FitnessReport.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time

import numpy as np
import pandas as pd

from services.trader.backtest.base import (
    FitnessReport,
    PlaceholderFeatureError,
    Strategy,
    validate_strategy,
)
from services.trader.backtest.risk import (
    catastrophic_drawdown_halt,
    clip_positions,
    clip_sectors,
    halt_daily_loss,
    halt_low_confidence,
)
from services.trader.data.storage.parquet_adapter import ParquetAdapter
from services.trader.features.base import BUILTIN_FEATURES, Feature
from services.trader.features.store import FeatureStore
from services.trader.regime.store import RegimeStore

logger = logging.getLogger(__name__)

TRADING_DAYS_PER_YEAR = 252


@dataclass(frozen=True)
class _Costs:
    commission_bps: float
    slippage_bps: float

    @property
    def total_bps(self) -> float:
        return self.commission_bps + self.slippage_bps


class Backtest:
    """Phase-1 backtest orchestrator."""

    def __init__(
        self,
        *,
        feature_store: FeatureStore,
        regime_store: RegimeStore,
        ohlcv_adapter: ParquetAdapter,
        initial_capital: float = 1_000_000.0,
        commission_bps: float = 1.0,
        slippage_bps: float = 5.0,
        builtin_features: list[Feature] | None = None,
        sector_map: Mapping[str, str] | None = None,
    ) -> None:
        self.feature_store = feature_store
        self.regime_store = regime_store
        self.ohlcv_adapter = ohlcv_adapter
        self.initial_capital = float(initial_capital)
        self.costs = _Costs(
            commission_bps=float(commission_bps),
            slippage_bps=float(slippage_bps),
        )
        self.builtin_features = (
            list(builtin_features) if builtin_features is not None
            else list(BUILTIN_FEATURES)
        )
        self.sector_map = dict(sector_map or {})

    def run(
        self,
        *,
        strategy: Strategy,
        universe: list[str],
        start: date,
        end: date,
        asof: datetime | None = None,
        regime_scope: str = "universe",
        regime_lens_names: list[str] | None = None,
        feature_columns: list[str] | None = None,
    ) -> FitnessReport:
        try:
            validate_strategy(
                strategy, builtin_features=self.builtin_features
            )
        except PlaceholderFeatureError as exc:
            return self._rejected_report(strategy, start, end, str(exc))

        start_dt = datetime.combine(start, time.min, tzinfo=UTC)
        end_dt = datetime.combine(end, time.max, tzinfo=UTC)
        asof_dt = asof or datetime.now(UTC)

        ohlcv = self._read_ohlcv(universe, start_dt, end_dt, asof_dt)
        if ohlcv.empty:
            return self._empty_report(strategy, start, end)

        feature_frame = self._read_features(
            universe, start_dt, end_dt, asof_dt, feature_columns
        )
        regime_frame = self._read_regime(
            regime_scope, start_dt, end_dt, asof_dt, regime_lens_names
        )

        signals = strategy.generate_signals(
            feature_frame=feature_frame, regime_frame=regime_frame
        )

        # Wide weight + price frames, index = bar_timestamp, cols = ticker
        prices = self._wide_prices(ohlcv, universe)
        weights = self._wide_weights(signals, prices.index, universe)

        weights = clip_positions(weights)
        weights = clip_sectors(weights, sector_map=self.sector_map)

        # One-bar execution lag — positions held at bar T = weights[T-1]
        held = weights.shift(1).fillna(0.0)

        # Apply halts on held positions
        halt_lowconf = halt_low_confidence(regime_frame)
        held = self._apply_halt(held, halt_lowconf)

        returns = prices.pct_change().fillna(0.0)
        portfolio_return_pre_cost = (held * returns).sum(axis=1)

        # Daily-loss halt requires the prior day's return — apply
        # iteratively for correctness with the prior-day dependency.
        daily_halt = halt_daily_loss(portfolio_return_pre_cost)
        held = self._apply_halt(held, daily_halt)
        portfolio_return_pre_cost = (held * returns).sum(axis=1)

        weight_changes = held.diff().abs().fillna(held.abs())
        cost_per_bar = weight_changes.sum(axis=1) * self.costs.total_bps / 10_000
        portfolio_return = portfolio_return_pre_cost - cost_per_bar

        equity = (1.0 + portfolio_return).cumprod() * self.initial_capital
        halted_at = catastrophic_drawdown_halt(equity)

        return self._assemble_report(
            strategy=strategy,
            start=start,
            end=end,
            held=held,
            portfolio_return=portfolio_return,
            equity=equity,
            halted_at=halted_at,
            regime_frame=regime_frame,
            weight_changes=weight_changes,
        )

    # --- reads ---------------------------------------------------------

    def _read_ohlcv(
        self, universe: list[str], start: datetime, end: datetime, asof: datetime
    ) -> pd.DataFrame:
        try:
            return self.ohlcv_adapter.read(
                kind="ohlcv",
                keys=universe,
                start=start,
                end=end,
                asof=asof,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("backtest OHLCV read failed: %s", exc)
            return pd.DataFrame()

    def _read_features(
        self,
        universe: list[str],
        start: datetime,
        end: datetime,
        asof: datetime,
        feature_columns: list[str] | None,
    ) -> pd.DataFrame:
        wanted = feature_columns or [f.name for f in self.builtin_features]
        features_to_pass = [f for f in self.builtin_features if f.name in wanted]
        try:
            return self.feature_store.read(
                keys=universe,
                start=start,
                end=end,
                asof=asof,
                features=features_to_pass,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("backtest feature read failed: %s", exc)
            return pd.DataFrame()

    def _read_regime(
        self,
        scope: str,
        start: datetime,
        end: datetime,
        asof: datetime,
        lens_names: list[str] | None,
    ) -> pd.DataFrame:
        names = lens_names or ["meso", "macro"]
        try:
            return self.regime_store.read(
                scopes=[scope],
                start=start,
                end=end,
                asof=asof,
                lens_names=names,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("backtest regime read failed: %s", exc)
            return pd.DataFrame()

    # --- frame construction --------------------------------------------

    def _wide_prices(
        self, ohlcv: pd.DataFrame, universe: list[str]
    ) -> pd.DataFrame:
        df = ohlcv.copy()
        df["bar_timestamp"] = pd.to_datetime(df["bar_timestamp"], utc=True)
        wide = df.pivot_table(
            index="bar_timestamp",
            columns="ticker",
            values="close",
            aggfunc="last",
        )
        # Ensure every requested ticker has a column even if it's all-null
        for t in universe:
            if t not in wide.columns:
                wide[t] = np.nan
        return wide[universe].sort_index()

    def _wide_weights(
        self,
        signals: pd.DataFrame,
        bar_index: pd.DatetimeIndex,
        universe: list[str],
    ) -> pd.DataFrame:
        if signals.empty:
            return pd.DataFrame(0.0, index=bar_index, columns=universe)
        s = signals.copy()
        s["bar_timestamp"] = pd.to_datetime(s["bar_timestamp"], utc=True)
        wide = s.pivot_table(
            index="bar_timestamp",
            columns="ticker",
            values="target_weight",
            aggfunc="last",
        )
        return wide.reindex(index=bar_index, columns=universe).fillna(0.0)

    @staticmethod
    def _apply_halt(held: pd.DataFrame, halt_mask: pd.Series) -> pd.DataFrame:
        """Zero held weights at every bar where `halt_mask` is True."""
        if held.empty or halt_mask.empty:
            return held
        aligned = halt_mask.reindex(held.index).fillna(False).astype(bool)
        out = held.copy()
        out.loc[aligned.values] = 0.0
        return out

    # --- reporting -----------------------------------------------------

    def _assemble_report(
        self,
        *,
        strategy: Strategy,
        start: date,
        end: date,
        held: pd.DataFrame,
        portfolio_return: pd.Series,
        equity: pd.Series,
        halted_at: datetime | None,
        regime_frame: pd.DataFrame,
        weight_changes: pd.DataFrame,
    ) -> FitnessReport:
        if portfolio_return.empty:
            return self._empty_report(strategy, start, end)

        total_return = float(equity.iloc[-1] / self.initial_capital - 1.0)
        sharpe = _sharpe(portfolio_return)
        running_peak = equity.cummax()
        drawdown = equity / running_peak - 1.0
        max_drawdown = float(drawdown.min()) if not drawdown.empty else 0.0

        positive_days = (portfolio_return > 0).sum()
        non_zero_days = (portfolio_return != 0).sum()
        win_rate = (
            float(positive_days / non_zero_days) if non_zero_days > 0 else 0.0
        )
        # Number of trades = sum of |weight changes| / 2 per Phase-1 convention
        num_trades = int(round(weight_changes.values.sum() / 2.0))

        per_regime = _per_regime_stats(portfolio_return, regime_frame)

        return FitnessReport(
            strategy=strategy.name,
            start=start,
            end=end,
            total_return=total_return,
            sharpe=sharpe,
            max_drawdown=max_drawdown,
            num_trades=num_trades,
            win_rate=win_rate,
            halted_at=halted_at,
            per_regime=per_regime,
            rejected_reason=None,
        )

    def _empty_report(
        self, strategy: Strategy, start: date, end: date
    ) -> FitnessReport:
        return FitnessReport(
            strategy=strategy.name,
            start=start,
            end=end,
            total_return=0.0,
            sharpe=0.0,
            max_drawdown=0.0,
            num_trades=0,
            win_rate=0.0,
        )

    def _rejected_report(
        self, strategy: Strategy, start: date, end: date, reason: str
    ) -> FitnessReport:
        return FitnessReport(
            strategy=strategy.name,
            start=start,
            end=end,
            total_return=0.0,
            sharpe=0.0,
            max_drawdown=0.0,
            num_trades=0,
            win_rate=0.0,
            rejected_reason=reason,
        )


def _sharpe(returns: pd.Series) -> float:
    if returns.empty:
        return 0.0
    std = returns.std(ddof=0)
    if std == 0 or math.isnan(std):
        return 0.0
    return float(returns.mean() / std * math.sqrt(TRADING_DAYS_PER_YEAR))


def _per_regime_stats(
    returns: pd.Series, regime_frame: pd.DataFrame
) -> dict[str, dict[str, float]]:
    if returns.empty or regime_frame.empty or "meso_label" not in regime_frame:
        return {}
    asof = pd.to_datetime(regime_frame["asof"], utc=True)
    label_by_bar = pd.Series(
        regime_frame["meso_label"].values, index=asof, name="meso_label"
    )
    aligned = label_by_bar.reindex(returns.index, method="ffill")
    out: dict[str, dict[str, float]] = {}
    for label, sub in returns.groupby(aligned):
        if not isinstance(label, str):
            continue
        out[label] = {
            "return": float((1.0 + sub).prod() - 1.0),
            "sharpe": _sharpe(sub),
            "n_bars": float(len(sub)),
        }
    return out
