"""THE strategy (Requirement 7): one deterministic, rule-based price-action
model. No discretion, no indicators.

Pipeline, exactly as specified (Requirement 12):

    Market Structure -> Liquidity Identification -> Liquidity Sweep ->
    Reaction / Displacement -> Structural Confirmation -> Entry -> SL -> TP
    -> R:R >= 3 -> (Risk Validation happens downstream in RiskEngine) -> Order

Rules, all programmable and checked in this exact order for every closed bar:

1. A liquidity pool (equal highs/lows, a swing high/low, or a session
   high/low) must have been SWEPT within `max_bars_since_sweep` bars --
   price wicked through it and closed back on the origin side
   (MarketStructureEngine._detect_sweep).
2. Somewhere between the sweep bar and the current bar, a DISPLACEMENT
   candle must have printed in the direction away from the swept level
   (MarketStructureEngine.is_displacement) -- this is the "reaction" that
   separates a real manipulation move from noise.
3. A structural confirmation (BOS or CHOCH) in the trade direction must have
   occurred at or after the displacement bar -- price must have actually
   broken a swing point in the new direction, not merely wicked one candle.
4. Entry is the close of the bar that produced the structural confirmation.
5. Stop-loss sits `sl_buffer_points` beyond the sweep's extreme wick --
   the level that, if revisited, proves the setup wrong (also the
   invalidation price).
6. Take-profit targets the nearest unswept opposing-side liquidity pool that
   sits beyond the minimum R:R distance; if none exists, TP defaults to
   exactly that minimum distance so every signal that reaches this stage
   already satisfies Rule 3 by construction.
7. If, after all of that, R:R still comes out below the configured minimum
   (can only happen via point rounding), the signal is REJECTED rather than
   silently traded -- Rule 3 is absolute.

This module never touches account size, lot size or broker minimums -- that
is the RiskEngine's job, evaluated strictly after a READY signal exists.
"""
from __future__ import annotations

from engine.config import StrategyConfig
from engine.market_structure.structure import MarketStructureEngine
from engine.types import (
    Direction,
    Signal,
    SetupStatus,
    StructureEventType,
    SweepEvent,
    TradePlan,
)


class LiquiditySweepStrategy:
    def __init__(self, structure: MarketStructureEngine, cfg: StrategyConfig, min_reward_risk: float = 3.0):
        self.structure = structure
        self.cfg = cfg
        self.min_reward_risk = min_reward_risk
        # Indices of sweeps already used to produce a signal, so the same
        # manipulation event never fires twice.
        self._consumed_sweep_indices: set[int] = set()

    # ------------------------------------------------------------------
    def evaluate(self, idx: int) -> Signal:
        eng = self.structure
        bar = eng.bars[idx]

        sweep = eng.recent_sweep(idx, self.cfg.max_bars_since_sweep)
        if sweep is None or sweep.index in self._consumed_sweep_indices:
            return Signal(
                symbol=eng.symbol, time=bar.time, status=SetupStatus.WAITING, structure=eng.trend,
                rejection_reason="No unconsumed liquidity sweep within the confirmation window",
            )

        direction = Direction.SELL if sweep.pool.kind.endswith("HIGH") else Direction.BUY

        displacement_idx = self._find_displacement_after(sweep, idx, direction)
        if displacement_idx is None:
            return Signal(
                symbol=eng.symbol, time=bar.time, status=SetupStatus.WAITING, structure=eng.trend,
                rejection_reason="Sweep detected, awaiting a displacement candle in the reaction direction",
                details={"sweep_index": sweep.index},
            )

        confirmation_idx = self._find_structural_confirmation(displacement_idx, idx, direction)
        if confirmation_idx is None:
            return Signal(
                symbol=eng.symbol, time=bar.time, status=SetupStatus.WAITING, structure=eng.trend,
                rejection_reason="Displacement seen, awaiting structural confirmation (BOS/CHOCH)",
                details={"sweep_index": sweep.index, "displacement_index": displacement_idx},
            )

        if confirmation_idx != idx:
            # confirmation already happened on an earlier bar; this sweep is fully evaluated
            self._consumed_sweep_indices.add(sweep.index)
            return Signal(
                symbol=eng.symbol, time=bar.time, status=SetupStatus.WAITING, structure=eng.trend,
                rejection_reason="Confirmation already consumed on a prior bar",
            )

        plan = self._build_plan(sweep, confirmation_idx, direction)
        self._consumed_sweep_indices.add(sweep.index)

        if plan.reward_risk_ratio < self.min_reward_risk - 1e-9:
            return Signal(
                symbol=eng.symbol, time=bar.time, status=SetupStatus.REJECTED, structure=eng.trend, plan=plan,
                rejection_reason=f"Computed R:R {plan.reward_risk_ratio:.2f} fell below minimum {self.min_reward_risk:.2f}",
                details={"sweep_index": sweep.index, "displacement_index": displacement_idx, "confirmation_index": confirmation_idx},
            )

        return Signal(
            symbol=eng.symbol, time=bar.time, status=SetupStatus.READY, structure=eng.trend, plan=plan,
            details={"sweep_index": sweep.index, "displacement_index": displacement_idx, "confirmation_index": confirmation_idx},
        )

    # ------------------------------------------------------------------
    def _find_displacement_after(self, sweep: SweepEvent, up_to_idx: int, direction: Direction) -> int | None:
        eng = self.structure
        for i in range(sweep.index, up_to_idx + 1):
            if i >= len(eng.bars):
                break
            if not eng.is_displacement(i):
                continue
            bar = eng.bars[i]
            if direction == Direction.SELL and bar.is_bearish:
                return i
            if direction == Direction.BUY and bar.is_bullish:
                return i
        return None

    def _find_structural_confirmation(self, displacement_idx: int, up_to_idx: int, direction: Direction) -> int | None:
        eng = self.structure
        wanted = (
            {StructureEventType.BOS_BEARISH, StructureEventType.CHOCH_BEARISH}
            if direction == Direction.SELL
            else {StructureEventType.BOS_BULLISH, StructureEventType.CHOCH_BULLISH}
        )
        for ev in eng.structure_events:
            if displacement_idx <= ev.index <= up_to_idx and ev.event_type in wanted:
                return ev.index
        return None

    # ------------------------------------------------------------------
    def _build_plan(self, sweep: SweepEvent, confirmation_idx: int, direction: Direction) -> TradePlan:
        eng = self.structure
        entry = eng.bars[confirmation_idx].close
        buffer_price = self.cfg.sl_buffer_points * eng.point

        reasoning = [
            f"Liquidity swept at {sweep.sweep_price:.5f} ({sweep.pool.kind}) on bar #{sweep.index}",
            f"Displacement + structural confirmation ({direction.value}) by bar #{confirmation_idx}",
        ]

        if direction == Direction.SELL:
            stop_loss = sweep.sweep_price + buffer_price
            min_risk = stop_loss - entry
            min_tp = entry - self.min_reward_risk * min_risk
            target = self._nearest_target(entry, direction, min_tp)
            take_profit = min(min_tp, target) if target is not None else min_tp
            invalidation = stop_loss
        else:
            stop_loss = sweep.sweep_price - buffer_price
            min_risk = entry - stop_loss
            min_tp = entry + self.min_reward_risk * min_risk
            target = self._nearest_target(entry, direction, min_tp)
            take_profit = max(min_tp, target) if target is not None else min_tp
            invalidation = stop_loss

        reasoning.append(f"SL {stop_loss:.5f} placed beyond sweep extreme + buffer")
        reasoning.append(f"TP {take_profit:.5f} targets next liquidity / minimum 1:{self.min_reward_risk:.0f}")

        return TradePlan(
            symbol=eng.symbol, direction=direction, entry=entry, stop_loss=stop_loss,
            take_profit=take_profit, invalidation_price=invalidation, reasoning=reasoning,
        )

    def _nearest_target(self, entry: float, direction: Direction, min_tp: float) -> float | None:
        eng = self.structure
        candidates = []
        for pool in eng.unswept_pools()[-self.cfg.target_search_pools:]:
            if direction == Direction.SELL and pool.kind.endswith("LOW") and pool.price < entry and pool.price <= min_tp:
                candidates.append(pool.price)
            if direction == Direction.BUY and pool.kind.endswith("HIGH") and pool.price > entry and pool.price >= min_tp:
                candidates.append(pool.price)
        if not candidates:
            return None
        return max(candidates) if direction == Direction.SELL else min(candidates)
