"""Shared data types used across the engine.

No third-party dependencies here on purpose: this module is imported by the
strategy, risk, backtest, bridge and UI layers alike, and keeping it stdlib-only
keeps startup cost and coupling low (see requirement: low resource usage).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Market data
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Bar:
    """One M5 OHLC candle. `time` is the bar OPEN time, UTC, tz-aware."""

    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    def __post_init__(self):
        if self.time.tzinfo is None:
            object.__setattr__(self, "time", self.time.replace(tzinfo=timezone.utc))

    @property
    def is_bullish(self) -> bool:
        return self.close > self.open

    @property
    def is_bearish(self) -> bool:
        return self.close < self.open

    @property
    def body_high(self) -> float:
        return max(self.open, self.close)

    @property
    def body_low(self) -> float:
        return min(self.open, self.close)

    @property
    def body_size(self) -> float:
        return abs(self.close - self.open)

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def upper_wick(self) -> float:
        return self.high - self.body_high

    @property
    def lower_wick(self) -> float:
        return self.body_low - self.low

    @property
    def mid(self) -> float:
        return (self.high + self.low) / 2.0


@dataclass(frozen=True)
class Quote:
    symbol: str
    time: datetime
    bid: float
    ask: float

    @property
    def spread(self) -> float:
        return self.ask - self.bid

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0


# ---------------------------------------------------------------------------
# Broker / symbol specification (mirrors MT5 SymbolInfo fields we need)
# ---------------------------------------------------------------------------

class TradeMode(str, Enum):
    DISABLED = "DISABLED"
    LONGONLY = "LONGONLY"
    SHORTONLY = "SHORTONLY"
    CLOSEONLY = "CLOSEONLY"
    FULL = "FULL"


@dataclass(frozen=True)
class SymbolSpec:
    symbol: str
    digits: int
    point: float
    contract_size: float
    tick_size: float
    tick_value: float          # profit currency value of one tick move for 1.0 lot
    volume_min: float
    volume_max: float
    volume_step: float
    margin_initial_per_lot: float   # approx account-currency margin required for 1.0 lot
    trade_mode: TradeMode
    stops_level_points: float  # broker minimum SL/TP distance, in points
    freeze_level_points: float
    currency_base: str
    currency_profit: str
    currency_margin: str
    swap_long: float = 0.0
    swap_short: float = 0.0

    def normalize_volume(self, raw_volume: float) -> float:
        """Round a raw lot size down to the nearest valid step, clamped to [min, max]."""
        if raw_volume <= 0:
            return 0.0
        steps = int(raw_volume / self.volume_step + 1e-9)
        vol = round(steps * self.volume_step, 8)
        vol = max(self.volume_min, min(self.volume_max, vol))
        # re-clamp: if flooring pushed us below min, and min itself is the only
        # representable size, min is returned (caller decides if risk allows it)
        return round(vol, 8)


@dataclass(frozen=True)
class AccountInfo:
    login: int
    broker: str
    account_currency: str
    balance: float
    equity: float
    margin: float
    margin_free: float
    leverage: float
    server_time: datetime = field(default_factory=utcnow)


# ---------------------------------------------------------------------------
# Market structure primitives
# ---------------------------------------------------------------------------

class SwingType(str, Enum):
    HIGH = "HIGH"
    LOW = "LOW"


@dataclass(frozen=True)
class SwingPoint:
    index: int
    time: datetime
    price: float
    kind: SwingType


class StructureLabel(str, Enum):
    HH = "HH"   # higher high
    HL = "HL"   # higher low
    LH = "LH"   # lower high
    LL = "LL"   # lower low
    EQH = "EQH"  # equal high
    EQL = "EQL"  # equal low


class TrendState(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    RANGING = "RANGING"


class StructureEventType(str, Enum):
    BOS_BULLISH = "BOS_BULLISH"
    BOS_BEARISH = "BOS_BEARISH"
    CHOCH_BULLISH = "CHOCH_BULLISH"
    CHOCH_BEARISH = "CHOCH_BEARISH"


@dataclass(frozen=True)
class StructureEvent:
    index: int
    time: datetime
    event_type: StructureEventType
    level: float


@dataclass(frozen=True)
class LiquidityPool:
    """A resting-liquidity level: equal highs/lows, a session high/low, or a swing."""

    price: float
    kind: str          # "EQH" | "EQL" | "SESSION_HIGH" | "SESSION_LOW" | "SWING_HIGH" | "SWING_LOW"
    formed_index: int
    formed_time: datetime
    touches: int = 1
    swept: bool = False


@dataclass(frozen=True)
class SweepEvent:
    index: int
    time: datetime
    pool: LiquidityPool
    sweep_price: float      # the extreme (wick) price that took liquidity
    close_back_inside: bool  # candle closed back on the other side of the pool


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

class Session(str, Enum):
    ASIAN = "ASIAN"
    LONDON = "LONDON"
    NEW_YORK = "NEW_YORK"
    OFF_HOURS = "OFF_HOURS"


class NewsWindow(str, Enum):
    NORMAL = "NORMAL"
    PRE_NEWS = "PRE_NEWS"
    NEWS = "NEWS"
    POST_NEWS = "POST_NEWS"


# ---------------------------------------------------------------------------
# Strategy / signal
# ---------------------------------------------------------------------------

class Direction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class SetupStatus(str, Enum):
    READY = "READY"
    WAITING = "WAITING"
    REJECTED = "REJECTED"
    INVALIDATED = "INVALIDATED"


@dataclass
class TradePlan:
    symbol: str
    direction: Direction
    entry: float
    stop_loss: float
    take_profit: float
    invalidation_price: float
    reasoning: list[str] = field(default_factory=list)

    @property
    def risk_price(self) -> float:
        return abs(self.entry - self.stop_loss)

    @property
    def reward_price(self) -> float:
        return abs(self.take_profit - self.entry)

    @property
    def reward_risk_ratio(self) -> float:
        if self.risk_price <= 0:
            return 0.0
        return self.reward_price / self.risk_price


@dataclass
class Signal:
    symbol: str
    time: datetime
    status: SetupStatus
    structure: TrendState
    plan: Optional[TradePlan] = None
    rejection_reason: Optional[str] = None
    details: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Risk / sizing
# ---------------------------------------------------------------------------

@dataclass
class PositionSizeResult:
    approved: bool
    volume: float = 0.0
    actual_risk_amount: float = 0.0
    actual_risk_pct: float = 0.0
    reason: Optional[str] = None
    details: dict = field(default_factory=dict)


@dataclass
class SymbolViability:
    symbol: str
    tradable: bool
    reason: Optional[str]
    minimum_practical_balance: Optional[float]  # smallest balance at which min-lot risk <= configured risk


# ---------------------------------------------------------------------------
# Orders / positions
# ---------------------------------------------------------------------------

class OrderResultStatus(str, Enum):
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    ERROR = "ERROR"


@dataclass
class OrderRequest:
    symbol: str
    direction: Direction
    volume: float
    entry: float
    stop_loss: float
    take_profit: float
    comment: str = ""
    client_id: str = ""


@dataclass
class OrderResult:
    status: OrderResultStatus
    order_id: Optional[str] = None
    filled_price: Optional[float] = None
    message: str = ""


@dataclass
class Position:
    ticket: str
    symbol: str
    direction: Direction
    volume: float
    entry_price: float
    stop_loss: float
    take_profit: float
    open_time: datetime
    profit: float = 0.0
