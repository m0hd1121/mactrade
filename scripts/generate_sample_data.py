#!/usr/bin/env python3
"""Write a SYNTHETIC M5 OHLC CSV to data/sample/ for pipeline testing/demos.

This is NOT real market data (see engine/backtest/data_loader.py). For real
backtests, export actual history from your MT5 terminal instead -- see
BACKTESTING.md.

    python3 scripts/generate_sample_data.py --symbol EURUSD --bars 20000
"""
import argparse
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.backtest.data_loader import generate_synthetic_bars
from engine.bridge.specs_defaults import default_symbol_spec


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--symbol", default="EURUSD")
    p.add_argument("--bars", type=int, default=20000)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--out", default=None)
    args = p.parse_args()

    spec = default_symbol_spec(args.symbol)
    bars = generate_synthetic_bars(args.symbol, datetime(2023, 1, 1, tzinfo=timezone.utc), args.bars, point=spec.point, seed=args.seed)

    out_path = Path(args.out) if args.out else Path(__file__).resolve().parent.parent / "data" / "sample" / f"{args.symbol}_M5_SYNTHETIC.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time", "open", "high", "low", "close", "volume"])
        for b in bars:
            w.writerow([b.time.isoformat(), b.open, b.high, b.low, b.close, b.volume])

    print(f"Wrote {len(bars)} SYNTHETIC bars to {out_path}")


if __name__ == "__main__":
    main()
