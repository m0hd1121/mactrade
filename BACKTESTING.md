# Backtesting

## Getting real data (do this first)

This repository ships **no real market data**. `data/sample/*_SYNTHETIC.csv`
is a labeled synthetic random walk used only to exercise the pipeline in
tests/CI and to let the app demo itself before you've supplied real
history -- **never treat its results as evidence the strategy works.**

To backtest for real, export actual MT5 history:

1. In MT5: **View -> Symbols** (or the Strategy Tester's History Center),
   select your symbol, timeframe M5, and export to CSV. Or:
2. Once you've run this system live/paper for a while, its own
   `bars/<SYMBOL>_M5.csv` files (written by the bridge EA under
   `Common/Files/ForexTradingSystem/bars/`) are already in the right format.

CSV columns expected: `time,open,high,low,close[,volume]` (`time` as
epoch seconds or ISO-8601; a header row is auto-detected and skipped).

## Running a backtest

**From the UI**: Backtesting tab -> pick symbol, starting balance, risk %,
optionally check small-account sweep / walk-forward / Monte Carlo -> Run.
Without a CSV path, it uses synthetic demo data (clearly labeled in the
result).

**From the CLI**:
```bash
python3 scripts/run_backtest.py --symbol EURUSD --csv path/to/history.csv \
    --balance 500 --risk 0.5 --sweep --walk-forward --monte-carlo
```

## What's actually simulated (`engine/backtest/backtester.py`)

The backtester runs the **exact same** `MarketStructureEngine`,
`LiquiditySweepStrategy`, and `RiskEngine` code that PAPER/LIVE trading
uses -- not a separate reimplementation. Per bar:

- Entry fills at the signal bar's close, adjusted for a configured spread
  (split around the close) and slippage -- achievable in practice since the
  strategy only acts on already-closed bars.
- If one bar's range touches both SL and TP, **SL is assumed to fill
  first** -- the conservative assumption, so results aren't flattered by
  favorable same-bar ordering.
- Every broker constraint that would apply live also applies here: minimum/
  step/max volume, margin, the broker's minimum stop distance, commission,
  and the same R:R/spread-cost/loss-limit gates as `RiskEngine`.
- Commission and slippage are configurable (`BacktestConfig`); they default
  to a conservative non-zero slippage.

## Metrics reported

Total trades, win rate, average win/loss, average R:R, profit factor,
expectancy, maximum drawdown (amount + %), maximum consecutive losses,
total return, Sharpe ratio (from daily equity returns), recovery factor,
plus everything segmented by **session** (Asian/London/New York/off-hours),
**news window** (normal/pre/during/post, if `news_events_utc` is supplied),
and **direction** (long/short) -- see `engine/backtest/metrics.py`.

## Small-account backtesting (mandatory, Requirement 17)

See SMALL_ACCOUNT.md. Short version:
`run_small_account_sweep` reruns the full backtest at $20/30/50/75/100/250/
500/1000 with real broker constraints at each level -- not a linear rescale
-- and reports how many setups become impossible purely because of account
size at each balance.

## Avoiding overfitting (Requirement 18)

This strategy has no numeric parameters fitted to history -- market
structure, sweeps, and displacement are geometric definitions
(STRATEGY.md), not curve-fit coefficients. Two tools still matter:

- **Walk-forward** (`engine/backtest/walk_forward.py`): splits the data
  chronologically into training (60%) / validation (20%) / out-of-sample
  (20%) and backtests each independently. A real edge should look broadly
  similar across all three; if performance is concentrated in one segment,
  that's a warning sign, not confirmation.
- **Monte Carlo** (`engine/backtest/monte_carlo.py`): bootstraps/reshuffles
  the closed-trade P/L sequence thousands of times to show the *range* of
  plausible equity curves (P5/P50/P95 final balance, P50/P95 max drawdown,
  probability of ruin) rather than the one specific sequence history
  happened to produce.

If you ever tune `StrategyConfig`/`RiskConfig` knobs (swing lookback,
displacement multiple, sweep window, etc.), re-run walk-forward across the
same data to confirm the tuning generalizes rather than fitting one period.

## Disclaimer (Rule 12)

No backtest, however careful, is proof of future profitability. Spread,
slippage, and commission assumptions are estimates; real execution will
differ. Treat every backtest result as one data point among several
(walk-forward segments, Monte Carlo range, live paper-trading results), not
as a verdict.
