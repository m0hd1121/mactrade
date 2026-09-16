"""Historical M5 bar loading.

Real backtests need REAL broker history -- this project does not ship any
market data. Export it from your own MT5 terminal (Strategy Tester -> History
Center -> export CSV, or use the bridge's own bars/<SYMBOL>_M5.csv files once
you have run it live for a while) and point `load_csv_bars` at the file. See
BACKTESTING.md.

`generate_synthetic_bars` produces clearly-labelled SYNTHETIC price data
(a random walk with regime shifts, not fitted to any real instrument) used
only for unit tests and for letting the app demonstrate itself before the
user has supplied real history. Its results must never be interpreted as
evidence of real-world profitability (Rule 12).
"""
from __future__ import annotations

import csv
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from engine.types import Bar


def load_csv_bars(path: Path, time_format: str = "auto") -> list[Bar]:
    """Load bars from a CSV with columns: time,open,high,low,close[,volume].

    `time` may be an epoch-seconds integer or an ISO-8601 string; both are
    auto-detected when time_format="auto".
    """
    bars: list[Bar] = []
    with open(path, newline="") as f:
        reader = csv.reader(f)
        rows = list(reader)
    if rows and not _is_number(rows[0][0]):
        rows = rows[1:]  # skip header row

    for row in rows:
        if len(row) < 5:
            continue
        t = _parse_time(row[0])
        bars.append(Bar(
            time=t, open=float(row[1]), high=float(row[2]), low=float(row[3]), close=float(row[4]),
            volume=float(row[5]) if len(row) > 5 and row[5] != "" else 0.0,
        ))
    bars.sort(key=lambda b: b.time)
    return bars


def _is_number(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def _parse_time(raw: str) -> datetime:
    if _is_number(raw):
        return datetime.fromtimestamp(float(raw), tz=timezone.utc)
    raw = raw.replace("Z", "+00:00")
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def generate_synthetic_bars(
    symbol: str, start: datetime, bar_count: int, start_price: float = 1.1000,
    point: float = 0.0001, seed: int = 42, regime_shift_every: int = 500,
) -> list[Bar]:
    """SYNTHETIC data only -- see module docstring. Deterministic given `seed`."""
    rng = random.Random(seed)
    bars: list[Bar] = []
    price = start_price
    drift = 0.0
    t = start
    for i in range(bar_count):
        if i % regime_shift_every == 0:
            drift = rng.uniform(-1, 1) * point * 0.3
        step = rng.gauss(drift, point * 8)
        o = price
        c = max(point, o + step)
        wick_up = abs(rng.gauss(0, point * 5))
        wick_down = abs(rng.gauss(0, point * 5))
        h = max(o, c) + wick_up
        l = max(point, min(o, c) - wick_down)
        bars.append(Bar(time=t, open=o, high=h, low=l, close=c, volume=rng.randint(50, 500)))
        price = c
        t = t + timedelta(minutes=5)
    return bars
