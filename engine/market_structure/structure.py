"""Deterministic, mathematically-defined market-structure engine.

Every concept below is defined purely from OHLC price geometry and bar
sequence -- there are no conventional technical indicators anywhere in this
module (Rule 7 / Requirement 8). Definitions:

Swing high (fractal): bar[i].high is the strict maximum of the window
    [i-lookback, i+lookback] (both inclusive). Swing low: symmetric on lows.
    A swing can only be confirmed `lookback` bars after it forms (it needs
    bars on both sides), which is why detection lags the live bar by that
    many bars -- this mirrors how a human or any non-repainting algorithm
    would actually confirm a fractal.

Trend state: BULLISH after a close breaks above the last tracked swing high,
    BEARISH after a close breaks below the last tracked swing low, RANGING
    before the first break. Whether a break is a BOS (continuation, in the
    direction of the existing trend) or a CHOCH (character change, against
    the existing trend) depends solely on `self.trend` at the moment of the
    break.

Liquidity pool: a price level where stops/orders are assumed to rest --
    every confirmed swing high/low, and every session high/low. Two swing
    points of the same kind within `equal_tolerance_price` of each other are
    merged into a single EQH/EQL pool with an incremented touch count.

Liquidity sweep: a bar whose wick pierces a liquidity pool's price but whose
    close snaps back to the other side of it (i.e. price cannot hold beyond
    the level) -- the mathematical definition of a stop hunt / manipulation
    candle. A pierce that closes THROUGH the level (no close-back) is a
    genuine break and simply retires the pool without emitting a sweep.

Displacement: a bar whose body is at least `body_multiple` times the average
    body size of the preceding `lookback` bars -- a purely price-derived
    momentum measure with no smoothing/indicator involved.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Optional

from engine.config import SessionConfig, StrategyConfig
from engine.market_structure.sessions import classify_session
from engine.types import (
    Bar,
    LiquidityPool,
    Session,
    StructureEvent,
    StructureEventType,
    SweepEvent,
    SwingPoint,
    SwingType,
    TrendState,
)


class MarketStructureEngine:
    def __init__(self, symbol: str, point: float, strategy_cfg: StrategyConfig, session_cfg: SessionConfig):
        self.symbol = symbol
        self.point = point
        self.cfg = strategy_cfg
        self.session_cfg = session_cfg

        self.bars: list[Bar] = []
        self.swing_points: list[SwingPoint] = []
        self.structure_events: list[StructureEvent] = []
        self.liquidity_pools: list[LiquidityPool] = []
        self.sweep_events: list[SweepEvent] = []

        self.trend: TrendState = TrendState.RANGING
        self.last_swing_high: Optional[SwingPoint] = None
        self.last_swing_low: Optional[SwingPoint] = None
        self._broken_high_indices: set[int] = set()
        self._broken_low_indices: set[int] = set()

        self._active_session: Optional[Session] = None
        self._active_session_high: Optional[float] = None
        self._active_session_low: Optional[float] = None
        self.previous_session_high: dict[Session, float] = {}
        self.previous_session_low: dict[Session, float] = {}
        self.current_session_high: Optional[float] = None
        self.current_session_low: Optional[float] = None
        self.current_session: Session = Session.OFF_HOURS

    # ------------------------------------------------------------------
    @property
    def equal_tolerance_price(self) -> float:
        return self.cfg.equal_level_tolerance_points * self.point

    def update(self, bar: Bar) -> None:
        self.bars.append(bar)
        idx = len(self.bars) - 1
        self._update_sessions(bar, idx)
        self._detect_swing(idx)
        self._detect_structure_events(idx)
        self._detect_sweep(idx)

    # ------------------------------------------------------------------
    def _update_sessions(self, bar: Bar, idx: int) -> None:
        session = classify_session(bar.time, self.session_cfg)
        self.current_session = session

        if session != self._active_session:
            # session boundary crossed: archive the finished session's extremes
            if self._active_session is not None and self._active_session != Session.OFF_HOURS:
                if self._active_session_high is not None:
                    self.previous_session_high[self._active_session] = self._active_session_high
                    self._add_liquidity_pool(
                        LiquidityPool(
                            price=self._active_session_high,
                            kind="SESSION_HIGH",
                            formed_index=idx - 1,
                            formed_time=self.bars[idx - 1].time,
                        )
                    )
                if self._active_session_low is not None:
                    self.previous_session_low[self._active_session] = self._active_session_low
                    self._add_liquidity_pool(
                        LiquidityPool(
                            price=self._active_session_low,
                            kind="SESSION_LOW",
                            formed_index=idx - 1,
                            formed_time=self.bars[idx - 1].time,
                        )
                    )
            self._active_session = session
            self._active_session_high = None
            self._active_session_low = None

        if session != Session.OFF_HOURS:
            self._active_session_high = bar.high if self._active_session_high is None else max(self._active_session_high, bar.high)
            self._active_session_low = bar.low if self._active_session_low is None else min(self._active_session_low, bar.low)
        self.current_session_high = self._active_session_high
        self.current_session_low = self._active_session_low

    # ------------------------------------------------------------------
    def _detect_swing(self, idx: int) -> None:
        L = self.cfg.swing_lookback
        candidate = idx - L
        if candidate < L:
            return
        window = self.bars[candidate - L: candidate + L + 1]
        if len(window) != 2 * L + 1:
            return
        pivot = self.bars[candidate]

        if pivot.high == max(b.high for b in window) and list(b.high for b in window).count(pivot.high) == 1:
            sp = SwingPoint(index=candidate, time=pivot.time, price=pivot.high, kind=SwingType.HIGH)
            self.swing_points.append(sp)
            self.last_swing_high = sp
            self._add_or_merge_liquidity(sp)

        if pivot.low == min(b.low for b in window) and list(b.low for b in window).count(pivot.low) == 1:
            sp = SwingPoint(index=candidate, time=pivot.time, price=pivot.low, kind=SwingType.LOW)
            self.swing_points.append(sp)
            self.last_swing_low = sp
            self._add_or_merge_liquidity(sp)

    # ------------------------------------------------------------------
    def _add_or_merge_liquidity(self, sp: SwingPoint) -> None:
        target_kind = "SWING_HIGH" if sp.kind == SwingType.HIGH else "SWING_LOW"
        tol = self.equal_tolerance_price
        for i, pool in enumerate(self.liquidity_pools):
            if pool.swept or pool.kind not in (target_kind, "EQH", "EQL"):
                continue
            same_side = (target_kind == "SWING_HIGH" and pool.kind in ("SWING_HIGH", "EQH")) or (
                target_kind == "SWING_LOW" and pool.kind in ("SWING_LOW", "EQL")
            )
            if same_side and abs(pool.price - sp.price) <= tol:
                new_kind = "EQH" if target_kind == "SWING_HIGH" else "EQL"
                self.liquidity_pools[i] = replace(
                    pool, price=sp.price, kind=new_kind, touches=pool.touches + 1,
                    formed_index=sp.index, formed_time=sp.time,
                )
                return
        self._add_liquidity_pool(LiquidityPool(price=sp.price, kind=target_kind, formed_index=sp.index, formed_time=sp.time))

    def _add_liquidity_pool(self, pool: LiquidityPool) -> None:
        self.liquidity_pools.append(pool)

    # ------------------------------------------------------------------
    def _detect_structure_events(self, idx: int) -> None:
        bar = self.bars[idx]

        if self.last_swing_high is not None and self.last_swing_high.index not in self._broken_high_indices:
            if bar.close > self.last_swing_high.price:
                event_type = (
                    StructureEventType.BOS_BULLISH if self.trend == TrendState.BULLISH else StructureEventType.CHOCH_BULLISH
                )
                self.structure_events.append(
                    StructureEvent(index=idx, time=bar.time, event_type=event_type, level=self.last_swing_high.price)
                )
                self._broken_high_indices.add(self.last_swing_high.index)
                self.trend = TrendState.BULLISH

        if self.last_swing_low is not None and self.last_swing_low.index not in self._broken_low_indices:
            if bar.close < self.last_swing_low.price:
                event_type = (
                    StructureEventType.BOS_BEARISH if self.trend == TrendState.BEARISH else StructureEventType.CHOCH_BEARISH
                )
                self.structure_events.append(
                    StructureEvent(index=idx, time=bar.time, event_type=event_type, level=self.last_swing_low.price)
                )
                self._broken_low_indices.add(self.last_swing_low.index)
                self.trend = TrendState.BEARISH

    # ------------------------------------------------------------------
    def _detect_sweep(self, idx: int) -> None:
        bar = self.bars[idx]
        for i, pool in enumerate(self.liquidity_pools):
            if pool.swept or pool.formed_index >= idx:
                continue
            is_high_pool = pool.kind in ("SWING_HIGH", "EQH", "SESSION_HIGH")
            is_low_pool = pool.kind in ("SWING_LOW", "EQL", "SESSION_LOW")

            if is_high_pool and bar.high > pool.price:
                closed_back = bar.close < pool.price
                self.liquidity_pools[i] = replace(pool, swept=True)
                if closed_back:
                    self.sweep_events.append(
                        SweepEvent(index=idx, time=bar.time, pool=self.liquidity_pools[i], sweep_price=bar.high, close_back_inside=True)
                    )
            elif is_low_pool and bar.low < pool.price:
                closed_back = bar.close > pool.price
                self.liquidity_pools[i] = replace(pool, swept=True)
                if closed_back:
                    self.sweep_events.append(
                        SweepEvent(index=idx, time=bar.time, pool=self.liquidity_pools[i], sweep_price=bar.low, close_back_inside=True)
                    )

    # ------------------------------------------------------------------
    def is_displacement(self, idx: int) -> bool:
        """True if bars[idx] is a displacement candle (Requirement 11/12)."""
        n = self.cfg.displacement_lookback
        if idx < n:
            return False
        lookback_bars = self.bars[idx - n: idx]
        if not lookback_bars:
            return False
        avg_body = sum(b.body_size for b in lookback_bars) / len(lookback_bars)
        if avg_body <= 0:
            return False
        return self.bars[idx].body_size >= self.cfg.displacement_body_multiple * avg_body

    def recent_sweep(self, idx: int, max_age_bars: Optional[int] = None) -> Optional[SweepEvent]:
        max_age = max_age_bars if max_age_bars is not None else self.cfg.max_bars_since_sweep
        for ev in reversed(self.sweep_events):
            if ev.index > idx:
                continue
            if idx - ev.index <= max_age:
                return ev
            break
        return None

    def unswept_pools(self) -> list[LiquidityPool]:
        return [p for p in self.liquidity_pools if not p.swept]
