"""Trade-resampling Monte Carlo analysis (Requirement 18).

Takes the closed-trade P/L sequence from a completed backtest and reshuffles
its order (and optionally bootstraps with replacement) thousands of times to
see how much the reported equity curve depended on the particular sequence
history handed us, versus the underlying per-trade expectancy. A strategy
whose 5th-percentile outcome is still solvent is far more trustworthy than
one whose single historical run happened to work out.
"""
from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass
class MonteCarloResult:
    iterations: int
    starting_balance: float
    final_balance_p5: float
    final_balance_p50: float
    final_balance_p95: float
    max_drawdown_pct_p50: float
    max_drawdown_pct_p95: float
    probability_of_ruin: float  # fraction of runs where equity <= 0 at any point


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * (pct / 100.0)
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def run_monte_carlo(
    trade_profits: list[float], starting_balance: float, iterations: int = 2000,
    bootstrap: bool = True, seed: int = 0,
) -> MonteCarloResult:
    rng = random.Random(seed)
    finals: list[float] = []
    max_dds: list[float] = []
    ruins = 0

    if not trade_profits:
        return MonteCarloResult(0, starting_balance, starting_balance, starting_balance, starting_balance, 0.0, 0.0, 0.0)

    n = len(trade_profits)
    for _ in range(iterations):
        if bootstrap:
            sample = [trade_profits[rng.randrange(n)] for _ in range(n)]
        else:
            sample = trade_profits[:]
            rng.shuffle(sample)

        equity = starting_balance
        peak = starting_balance
        max_dd_pct = 0.0
        ruined = False
        for p in sample:
            equity += p
            if equity <= 0:
                ruined = True
            peak = max(peak, equity)
            dd_pct = (peak - equity) / peak * 100.0 if peak > 0 else 0.0
            max_dd_pct = max(max_dd_pct, dd_pct)

        finals.append(equity)
        max_dds.append(max_dd_pct)
        if ruined:
            ruins += 1

    return MonteCarloResult(
        iterations=iterations, starting_balance=starting_balance,
        final_balance_p5=round(_percentile(finals, 5), 2), final_balance_p50=round(_percentile(finals, 50), 2),
        final_balance_p95=round(_percentile(finals, 95), 2),
        max_drawdown_pct_p50=round(_percentile(max_dds, 50), 2), max_drawdown_pct_p95=round(_percentile(max_dds, 95), 2),
        probability_of_ruin=round(ruins / iterations, 4),
    )
