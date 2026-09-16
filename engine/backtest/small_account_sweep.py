"""Small-account backtesting sweep (Requirement 17 -- mandatory).

Runs the SAME backtest across a ladder of realistic starting balances so the
report shows exactly where and why the strategy becomes non-viable for a
given symbol/broker combination, instead of naively scaling a large-account
result.
"""
from __future__ import annotations

from dataclasses import dataclass

from engine.backtest.backtester import Backtester, BacktestConfig
from engine.types import Bar, SymbolSpec

DEFAULT_BALANCE_LADDER = [20, 30, 50, 75, 100, 250, 500, 1000]


@dataclass
class SweepPoint:
    starting_balance: float
    total_trades: int
    trades_rejected_for_account_size: int
    total_return_pct: float
    max_drawdown_pct: float
    ending_balance: float
    viable: bool


def run_small_account_sweep(
    spec: SymbolSpec, bars: list[Bar], base_config: BacktestConfig, balances: list[float] | None = None,
) -> list[SweepPoint]:
    balances = balances or DEFAULT_BALANCE_LADDER
    results = []
    for balance in balances:
        cfg = BacktestConfig(
            starting_balance=float(balance), risk_cfg=base_config.risk_cfg, strategy_cfg=base_config.strategy_cfg,
            session_cfg=base_config.session_cfg, spread_points=base_config.spread_points,
            slippage_points=base_config.slippage_points, commission_per_lot=base_config.commission_per_lot,
            news_events_utc=base_config.news_events_utc, pre_news_minutes=base_config.pre_news_minutes,
            post_news_minutes=base_config.post_news_minutes,
        )
        bt = Backtester(spec, cfg)
        result = bt.run(bars)

        size_rejections = sum(
            1 for r in result.rejected
            if r.get("reason") and "minimum allowed account risk" in r["reason"]
        )
        total_trades = result.metrics["total_trades"]
        viable = total_trades > 0 or (total_trades == 0 and size_rejections == 0)

        results.append(SweepPoint(
            starting_balance=balance, total_trades=total_trades,
            trades_rejected_for_account_size=size_rejections,
            total_return_pct=result.metrics["total_return_pct"], max_drawdown_pct=result.metrics["max_drawdown_pct"],
            ending_balance=result.metrics["ending_balance"],
            viable=size_rejections == 0,
        ))
    return results
