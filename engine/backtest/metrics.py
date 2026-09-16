"""Backtest performance statistics (Requirement 16)."""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime
from typing import Any


def _max_drawdown(equity_curve: list[tuple[datetime, float]]) -> tuple[float, float]:
    """Returns (max_drawdown_amount, max_drawdown_pct)."""
    if not equity_curve:
        return 0.0, 0.0
    peak = equity_curve[0][1]
    max_dd_amount = 0.0
    max_dd_pct = 0.0
    for _, equity in equity_curve:
        peak = max(peak, equity)
        dd = peak - equity
        dd_pct = (dd / peak * 100.0) if peak > 0 else 0.0
        max_dd_amount = max(max_dd_amount, dd)
        max_dd_pct = max(max_dd_pct, dd_pct)
    return max_dd_amount, max_dd_pct


def _max_consecutive_losses(trades: list[dict]) -> int:
    worst = cur = 0
    for t in trades:
        if (t.get("profit") or 0) < 0:
            cur += 1
            worst = max(worst, cur)
        else:
            cur = 0
    return worst


def _daily_returns(equity_curve: list[tuple[datetime, float]]) -> list[float]:
    by_day: dict[Any, float] = {}
    for t, eq in equity_curve:
        by_day[t.date()] = eq  # last value of the day wins
    values = [v for _, v in sorted(by_day.items())]
    returns = []
    for i in range(1, len(values)):
        if values[i - 1] != 0:
            returns.append((values[i] - values[i - 1]) / values[i - 1])
    return returns


def _sharpe_ratio(equity_curve: list[tuple[datetime, float]], periods_per_year: float = 252) -> float:
    returns = _daily_returns(equity_curve)
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    std = math.sqrt(variance)
    if std == 0:
        return 0.0
    return (mean / std) * math.sqrt(periods_per_year)


def compute_metrics(trades: list[dict], equity_curve: list[tuple[datetime, float]], starting_balance: float) -> dict:
    closed = [t for t in trades if t.get("profit") is not None]
    total_trades = len(closed)
    wins = [t for t in closed if t["profit"] > 0]
    losses = [t for t in closed if t["profit"] <= 0]
    win_rate = (len(wins) / total_trades * 100.0) if total_trades else 0.0
    avg_win = (sum(t["profit"] for t in wins) / len(wins)) if wins else 0.0
    avg_loss = (sum(t["profit"] for t in losses) / len(losses)) if losses else 0.0
    gross_profit = sum(t["profit"] for t in wins)
    gross_loss = abs(sum(t["profit"] for t in losses))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0)
    expectancy = (sum(t["profit"] for t in closed) / total_trades) if total_trades else 0.0
    avg_rr = (sum(t.get("reward_risk_ratio", 0) or 0 for t in closed) / total_trades) if total_trades else 0.0

    max_dd_amount, max_dd_pct = _max_drawdown(equity_curve)
    ending_balance = equity_curve[-1][1] if equity_curve else starting_balance
    total_return_pct = ((ending_balance - starting_balance) / starting_balance * 100.0) if starting_balance else 0.0
    net_profit = ending_balance - starting_balance
    recovery_factor = (net_profit / max_dd_amount) if max_dd_amount > 0 else (float("inf") if net_profit > 0 else 0.0)

    return {
        "total_trades": total_trades,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "avg_reward_risk_ratio": round(avg_rr, 2),
        "profit_factor": round(profit_factor, 3) if math.isfinite(profit_factor) else None,
        "expectancy": round(expectancy, 4),
        "max_drawdown_amount": round(max_dd_amount, 2),
        "max_drawdown_pct": round(max_dd_pct, 2),
        "max_consecutive_losses": _max_consecutive_losses(closed),
        "total_return_pct": round(total_return_pct, 2),
        "sharpe_ratio": round(_sharpe_ratio(equity_curve), 3),
        "recovery_factor": round(recovery_factor, 3) if math.isfinite(recovery_factor) else None,
        "starting_balance": starting_balance,
        "ending_balance": round(ending_balance, 2),
        "net_profit": round(net_profit, 2),
    }


def segment_metrics(trades: list[dict], equity_curve: list[tuple[datetime, float]], starting_balance: float, key: str) -> dict[str, dict]:
    """Split closed trades by a field (session / news_window / direction) and
    compute independent metrics for each bucket (Requirement 16)."""
    buckets: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        buckets[str(t.get(key))].append(t)
    out = {}
    for name, bucket_trades in buckets.items():
        # segment equity curves aren't independently meaningful (drawdown needs
        # continuity), so segment reports focus on the trade-level stats and
        # reuse overall equity only for context, not a per-segment drawdown.
        m = compute_metrics(bucket_trades, equity_curve, starting_balance)
        out[name] = m
    return out
