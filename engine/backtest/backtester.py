"""Event-driven M5 backtesting engine (Requirement 16/17).

Runs the EXACT SAME strategy, market-structure and risk-engine code used in
paper/live trading against historical bars -- there is no separate
"backtest-only" strategy implementation to drift out of sync with. Every
broker constraint (min/max/step volume, margin, spread, commission,
slippage) that would apply live is simulated here too, which is what makes
the small-account sweep (small_account_sweep.py) meaningful rather than a
naive linear rescale of a large-account result (Requirement 17).

Fill assumptions (documented, not hidden):
 - Entry fills at the signal bar's close, adjusted for simulated spread and
   slippage -- the strategy only acts on CLOSED bars, so this is achievable
   in practice by an EA reacting to the same bar close.
 - If a single bar's range touches BOTH the stop-loss and take-profit, the
   stop-loss is assumed filled first (the conservative assumption).
 - No partial fills; volume is sized once per trade at entry.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from engine.config import RiskConfig, SessionConfig, StrategyConfig
from engine.market_structure.sessions import classify_session
from engine.market_structure.structure import MarketStructureEngine
from engine.risk.risk_engine import RiskEngine, RiskState
from engine.strategy.liquidity_sweep import LiquiditySweepStrategy
from engine.types import (
    AccountInfo, Bar, Direction, NewsWindow, Quote, SetupStatus, SymbolSpec, TradePlan,
)


@dataclass
class BacktestConfig:
    starting_balance: float
    risk_cfg: RiskConfig
    strategy_cfg: StrategyConfig
    session_cfg: SessionConfig
    spread_points: float
    slippage_points: float = 1.0
    commission_per_lot: float = 0.0
    news_events_utc: list[datetime] = field(default_factory=list)
    pre_news_minutes: int = 15
    post_news_minutes: int = 30


@dataclass
class SimTrade:
    symbol: str
    direction: str
    volume: float
    entry_price: float
    stop_loss: float
    take_profit: float
    risk_amount: float
    risk_pct: float
    reward_risk_ratio: float
    open_time: datetime
    session: str
    news_window: str
    close_time: Optional[datetime] = None
    close_price: Optional[float] = None
    profit: Optional[float] = None
    status: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol, "direction": self.direction, "volume": self.volume,
            "entry_price": self.entry_price, "stop_loss": self.stop_loss, "take_profit": self.take_profit,
            "risk_amount": self.risk_amount, "risk_pct": self.risk_pct, "reward_risk_ratio": self.reward_risk_ratio,
            "open_time": self.open_time, "session": self.session, "news_window": self.news_window,
            "close_time": self.close_time, "close_price": self.close_price, "profit": self.profit,
            "status": self.status,
        }


@dataclass
class BacktestResult:
    symbol: str
    starting_balance: float
    trades: list[dict]
    rejected: list[dict]
    equity_curve: list[tuple[datetime, float]]
    metrics: dict


class Backtester:
    def __init__(self, spec: SymbolSpec, config: BacktestConfig):
        self.spec = spec
        self.cfg = config
        self.structure = MarketStructureEngine(spec.symbol, spec.point, config.strategy_cfg, config.session_cfg)
        self.strategy = LiquiditySweepStrategy(self.structure, config.strategy_cfg, config.risk_cfg.min_reward_risk)
        self.risk_engine = RiskEngine(config.risk_cfg)

        self.balance = config.starting_balance
        self.used_margin = 0.0
        self.open_position: Optional[SimTrade] = None
        self.closed_trades: list[SimTrade] = []
        self.rejected: list[dict] = []
        self.equity_curve: list[tuple[datetime, float]] = []

        self.state = RiskState()
        self._current_day = None
        self._current_week = None

    # ------------------------------------------------------------------
    def run(self, bars: list[Bar]) -> BacktestResult:
        for idx, bar in enumerate(bars):
            self._roll_period_counters(bar.time)
            self.structure.update(bar)

            if self.open_position is not None:
                self._manage_open_position(bar)

            if self.open_position is None:
                signal = self.strategy.evaluate(idx)
                if signal.status == SetupStatus.READY:
                    self._try_enter(signal.plan, bar)

            self.equity_curve.append((bar.time, self._equity(bar)))

        if self.open_position is not None and bars:
            self._close_position(self.open_position, bars[-1].close, "CLOSED_END_OF_TEST", bars[-1].time)

        trades = [t.to_dict() for t in self.closed_trades]
        metrics = _compute(trades, self.equity_curve, self.cfg.starting_balance)
        return BacktestResult(
            symbol=self.spec.symbol, starting_balance=self.cfg.starting_balance,
            trades=trades, rejected=self.rejected, equity_curve=self.equity_curve, metrics=metrics,
        )

    # ------------------------------------------------------------------
    def _roll_period_counters(self, t: datetime) -> None:
        day = t.date()
        week = t.isocalendar()[:2]
        if self._current_day != day:
            self._current_day = day
            self.state.trades_today = 0
            self.state.daily_realized_pnl = 0.0
        if self._current_week != week:
            self._current_week = week
            self.state.weekly_realized_pnl = 0.0

    def _news_window(self, t: datetime) -> NewsWindow:
        for ev in self.cfg.news_events_utc:
            if ev - timedelta(minutes=self.cfg.pre_news_minutes) <= t < ev:
                return NewsWindow.PRE_NEWS
            if ev <= t <= ev + timedelta(minutes=2):
                return NewsWindow.NEWS
            if ev + timedelta(minutes=2) < t <= ev + timedelta(minutes=self.cfg.post_news_minutes):
                return NewsWindow.POST_NEWS
        return NewsWindow.NORMAL

    def _spread_price(self) -> float:
        return self.cfg.spread_points * self.spec.point

    def _slippage_price(self) -> float:
        return self.cfg.slippage_points * self.spec.point

    def _equity(self, bar: Bar) -> float:
        if self.open_position is None:
            return self.balance
        pos = self.open_position
        px = bar.close
        ticks = (px - pos.entry_price) / self.spec.tick_size if pos.direction == "BUY" else (pos.entry_price - px) / self.spec.tick_size
        floating = ticks * self.spec.tick_value * pos.volume
        return self.balance + floating

    # ------------------------------------------------------------------
    def _try_enter(self, plan: TradePlan, bar: Bar) -> None:
        spread_price = self._spread_price()
        slip_price = self._slippage_price()

        if plan.direction == Direction.BUY:
            fill = bar.close + spread_price / 2 + slip_price
        else:
            fill = bar.close - spread_price / 2 - slip_price

        actual_plan = TradePlan(
            symbol=plan.symbol, direction=plan.direction, entry=fill, stop_loss=plan.stop_loss,
            take_profit=plan.take_profit, invalidation_price=plan.invalidation_price, reasoning=plan.reasoning,
        )

        if actual_plan.reward_risk_ratio < self.cfg.risk_cfg.min_reward_risk - 1e-9:
            self.rejected.append({
                "time": bar.time, "symbol": plan.symbol, "reason": "Transaction cost eroded R:R below minimum",
                "planned_rr": plan.reward_risk_ratio, "actual_rr": actual_plan.reward_risk_ratio,
            })
            return

        equity = self._equity(bar)
        account = AccountInfo(
            login=0, broker="backtest", account_currency="USD", balance=self.balance, equity=equity,
            margin=self.used_margin, margin_free=max(0.0, equity - self.used_margin), leverage=500,
        )
        quote = Quote(symbol=plan.symbol, time=bar.time, bid=bar.close - spread_price / 2, ask=bar.close + spread_price / 2)

        decision = self.risk_engine.evaluate_trade(account, self.spec, quote, actual_plan, self.state)
        if not decision.approved:
            self.rejected.append({"time": bar.time, "symbol": plan.symbol, "reason": decision.reason, "details": decision.details})
            return

        sizing = decision.position_size
        session = classify_session(bar.time, self.cfg.session_cfg).value
        news_window = self._news_window(bar.time).value

        self.open_position = SimTrade(
            symbol=plan.symbol, direction=plan.direction.value, volume=sizing.volume, entry_price=fill,
            stop_loss=plan.stop_loss, take_profit=plan.take_profit, risk_amount=sizing.actual_risk_amount,
            risk_pct=sizing.actual_risk_pct, reward_risk_ratio=actual_plan.reward_risk_ratio,
            open_time=bar.time, session=session, news_window=news_window,
        )
        self.used_margin = sizing.volume * self.spec.margin_initial_per_lot
        self.state.open_positions = 1
        self.state.trades_today += 1

    def _manage_open_position(self, bar: Bar) -> None:
        pos = self.open_position
        if pos.direction == "BUY":
            hit_sl = bar.low <= pos.stop_loss
            hit_tp = bar.high >= pos.take_profit
        else:
            hit_sl = bar.high >= pos.stop_loss
            hit_tp = bar.low <= pos.take_profit

        if hit_sl:
            self._close_position(pos, pos.stop_loss, "CLOSED_SL", bar.time)
        elif hit_tp:
            self._close_position(pos, pos.take_profit, "CLOSED_TP", bar.time)

    def _close_position(self, pos: SimTrade, price: float, status: str, time: datetime) -> None:
        ticks = (price - pos.entry_price) / self.spec.tick_size if pos.direction == "BUY" else (pos.entry_price - price) / self.spec.tick_size
        gross = ticks * self.spec.tick_value * pos.volume
        commission = self.cfg.commission_per_lot * pos.volume
        profit = gross - commission

        pos.close_time = time
        pos.close_price = price
        pos.profit = profit
        pos.status = status

        self.balance += profit
        self.used_margin = 0.0
        self.state.open_positions = 0
        self.state.daily_realized_pnl += profit
        self.state.weekly_realized_pnl += profit
        self.state.consecutive_losses = (self.state.consecutive_losses + 1) if profit < 0 else 0

        self.closed_trades.append(pos)
        self.open_position = None


def _compute(trades: list[dict], equity_curve: list[tuple[datetime, float]], starting_balance: float) -> dict:
    from engine.backtest.metrics import compute_metrics, segment_metrics
    metrics = compute_metrics(trades, equity_curve, starting_balance)
    metrics["by_session"] = segment_metrics(trades, equity_curve, starting_balance, "session")
    metrics["by_news_window"] = segment_metrics(trades, equity_curve, starting_balance, "news_window")
    metrics["by_direction"] = segment_metrics(trades, equity_curve, starting_balance, "direction")
    return metrics
