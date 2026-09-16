#!/usr/bin/env python3
"""Command-line backtest runner (no UI needed).

    python3 scripts/run_backtest.py --symbol EURUSD --csv path/to/history.csv --balance 500 --risk 0.5
    python3 scripts/run_backtest.py --symbol EURUSD --demo --bars 20000   # synthetic demo data

See BACKTESTING.md for exporting real history from MT5.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.backtest.backtester import Backtester, BacktestConfig
from engine.backtest.data_loader import generate_synthetic_bars, load_csv_bars
from engine.backtest.monte_carlo import run_monte_carlo
from engine.backtest.small_account_sweep import run_small_account_sweep
from engine.backtest.walk_forward import run_walk_forward
from engine.bridge.specs_defaults import default_symbol_spec
from engine.config import RiskConfig, SessionConfig, StrategyConfig
from engine.db.database import Database


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--symbol", required=True)
    p.add_argument("--csv", help="Path to a CSV of real M5 history (time,open,high,low,close[,volume])")
    p.add_argument("--demo", action="store_true", help="Use synthetic demo data instead of --csv")
    p.add_argument("--bars", type=int, default=20000)
    p.add_argument("--balance", type=float, default=1000.0)
    p.add_argument("--risk", type=float, default=0.5)
    p.add_argument("--spread-points", type=float, default=10.0)
    p.add_argument("--sweep", action="store_true", help="Also run the small-account sweep")
    p.add_argument("--walk-forward", action="store_true")
    p.add_argument("--monte-carlo", action="store_true")
    p.add_argument("--db", default=None, help="Save the result into this SQLite DB (optional)")
    args = p.parse_args()

    spec = default_symbol_spec(args.symbol)

    if args.csv:
        bars = load_csv_bars(Path(args.csv))
        source = args.csv
    elif args.demo:
        bars = generate_synthetic_bars(args.symbol, datetime(2023, 1, 1, tzinfo=timezone.utc), args.bars, point=spec.point)
        source = "SYNTHETIC DEMO DATA (not real market history)"
    else:
        p.error("Pass --csv <file> for real history, or --demo for synthetic demo data")
        return

    cfg = BacktestConfig(
        starting_balance=args.balance, risk_cfg=RiskConfig(risk_per_trade_pct=args.risk),
        strategy_cfg=StrategyConfig(), session_cfg=SessionConfig(), spread_points=args.spread_points,
    )
    bt = Backtester(spec, cfg)
    result = bt.run(bars)

    print(f"Data source: {source}")
    print(json.dumps(result.metrics, indent=2, default=str))

    if args.sweep:
        sweep = run_small_account_sweep(spec, bars, cfg)
        print("\nSmall-account sweep:")
        for s in sweep:
            print(f"  ${s.starting_balance:>7.0f}  trades={s.total_trades:<4} rejected_size={s.trades_rejected_for_account_size:<4} "
                  f"return={s.total_return_pct:>7.2f}%  viable={'YES' if s.viable else 'NO'}")

    if args.walk_forward:
        wf = run_walk_forward(spec, bars, cfg)
        print("\nWalk-forward:")
        for w in wf:
            print(f"  {w.name:<14} bars={w.bar_count:<6} trades={w.metrics['total_trades']:<4} return={w.metrics['total_return_pct']:>7.2f}%")

    if args.monte_carlo:
        profits = [t["profit"] for t in result.trades if t.get("profit") is not None]
        mc = run_monte_carlo(profits, args.balance)
        print(f"\nMonte Carlo ({mc.iterations} runs): P5=${mc.final_balance_p5} P50=${mc.final_balance_p50} "
              f"P95=${mc.final_balance_p95} ProbRuin={mc.probability_of_ruin * 100:.2f}%")

    if args.db:
        db = Database(Path(args.db))
        db.save_backtest([args.symbol], bars[0].time.isoformat(), bars[-1].time.isoformat(), args.balance, args.risk, result.metrics)
        db.close()


if __name__ == "__main__":
    main()
