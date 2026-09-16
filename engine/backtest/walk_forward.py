"""Walk-forward / out-of-sample validation (Requirement 18).

This strategy has no numeric parameters fitted to history -- market
structure, sweeps and displacement are geometric definitions, not curve-fit
coefficients. Walk-forward here therefore serves a different but still
essential purpose: proving the strategy's edge (or lack of one) is
CONSISTENT across independent, chronologically-ordered periods rather than
concentrated in one lucky stretch, which is the actual overfitting risk for
a rule-based system (Rule 13). If `StrategyConfig`/`RiskConfig` knobs are
ever tuned, re-running this split is how you confirm the tuning wasn't just
fit to one segment.
"""
from __future__ import annotations

from dataclasses import dataclass

from engine.backtest.backtester import Backtester, BacktestConfig
from engine.types import Bar, SymbolSpec


@dataclass
class WalkForwardSegment:
    name: str
    start_time: str
    end_time: str
    bar_count: int
    metrics: dict


def split_bars(bars: list[Bar], train_frac: float = 0.6, validation_frac: float = 0.2) -> dict[str, list[Bar]]:
    n = len(bars)
    train_end = int(n * train_frac)
    val_end = int(n * (train_frac + validation_frac))
    return {
        "training": bars[:train_end],
        "validation": bars[train_end:val_end],
        "out_of_sample": bars[val_end:],
    }


def run_walk_forward(spec: SymbolSpec, bars: list[Bar], config: BacktestConfig) -> list[WalkForwardSegment]:
    segments = split_bars(bars)
    results = []
    for name, segment_bars in segments.items():
        if not segment_bars:
            continue
        bt = Backtester(spec, config)
        result = bt.run(segment_bars)
        results.append(WalkForwardSegment(
            name=name, start_time=segment_bars[0].time.isoformat(), end_time=segment_bars[-1].time.isoformat(),
            bar_count=len(segment_bars), metrics=result.metrics,
        ))
    return results
