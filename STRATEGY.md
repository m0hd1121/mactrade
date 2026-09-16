# Strategy Specification

One deterministic, rule-based price-action model. Every condition below is
implemented in `engine/market_structure/structure.py` and
`engine/strategy/liquidity_sweep.py` -- there is no discretionary judgment
call anywhere in the pipeline, and no conventional technical indicator
(RSI, MACD, EMA/SMA/WMA, VWAP, Bollinger Bands, Stochastic, ATR, ADX, CCI,
Ichimoku, or any other) is used anywhere in this codebase.

## 1. Market structure (mathematical definitions)

**Swing high** at bar `i`: `bars[i].high` is the strict maximum of the
`2*lookback+1`-bar window centered on `i` (`StrategyConfig.swing_lookback`,
default 3). **Swing low** is the symmetric definition on lows. Because a
swing needs bars on both sides to confirm, detection always lags the live
bar by `lookback` bars -- this is a non-repainting definition.

**Trend state**: `RANGING` until the first break, then `BULLISH` after a
bar closes above the last tracked swing high, `BEARISH` after a close below
the last tracked swing low.

**BOS vs. CHOCH**: identical break mechanics (a close through the last
swing high/low); the label depends only on the trend state *at the moment
of the break*. Breaking a swing high while already `BULLISH` is a **BOS**
(continuation); breaking it while `BEARISH`/`RANGING` is a **CHOCH**
(character change). Symmetric on the downside.

**Liquidity pool**: every confirmed swing high/low, plus every completed
session's high/low (`Session` = ASIAN/LONDON/NEW_YORK by UTC hour, see
`engine/market_structure/sessions.py`). Two swing points of the same kind
within `equal_level_tolerance_points` of each other merge into a single
**EQH**/**EQL** pool with an incremented touch count.

**Liquidity sweep**: a bar whose wick pierces a pool's price but whose
*close* snaps back to the origin side of it -- the definition of a stop
hunt / manipulation candle. A pierce that closes *through* the level (no
close-back) is a genuine break; it retires the pool without producing a
sweep event.

**Displacement**: a bar whose body is at least `displacement_body_multiple`
times the average body size of the preceding `displacement_lookback` bars
-- a raw price-geometry momentum measure, not a smoothed indicator.

## 2. Entry pipeline (Requirement 12)

```
Market Structure -> Liquidity Identification -> Liquidity Sweep ->
Reaction / Displacement -> Structural Confirmation -> Entry -> SL -> TP ->
R:R >= 3 -> Risk Validation (engine/risk) -> Order
```

Concretely, for every closed M5 bar (`LiquiditySweepStrategy.evaluate`):

1. **Sweep**: was a liquidity pool swept within `max_bars_since_sweep`
   bars (default 12), and not already consumed by an earlier signal?
   If not: status `WAITING`.
2. **Displacement**: did a displacement candle print, in the direction away
   from the swept level, between the sweep bar and now? If not: `WAITING`.
3. **Structural confirmation**: did a BOS or CHOCH in the trade direction
   occur at or after the displacement bar? If not: `WAITING`.
4. **Entry**: the close of the bar that produced the structural
   confirmation.
5. **Stop-loss** (= invalidation price): `sl_buffer_points` beyond the
   sweep's extreme wick. If price ever returns there, the premise --
   "that level was defended" -- is proven wrong.
6. **Take-profit**: the nearest unswept opposing-side liquidity pool beyond
   the minimum-R:R distance; if none exists, exactly the minimum-R:R
   distance, so every signal that reaches this stage already satisfies
   Rule 3 by construction.
7. **R:R gate**: if, after all of the above, R:R is still below
   `min_reward_risk` (only possible from point-rounding at the edges),
   status is `REJECTED` with the computed ratio in the reason -- never
   silently traded.

A `READY` signal then goes to `engine/risk/risk_engine.py`
(`RiskEngine.evaluate_trade`) for position sizing and every other risk gate
-- see RISK_MANAGEMENT.md. The strategy module itself never looks at
account size, lot size, or broker minimums.

## 3. What the UI shows for a rejected/waiting setup

Every `Signal` (READY, WAITING, or REJECTED) is logged to the `signals`
table and the latest one per symbol is upserted into `setups`
(`engine/db/database.py`), with the full reasoning trail
(`TradePlan.reasoning`) so the Trade Setup tab can show exactly why a
symbol is or isn't trading right now, not just a pass/fail flag.

## 4. News handling (Requirement 13)

`NewsWindow` (`NORMAL` / `PRE_NEWS` / `NEWS` / `POST_NEWS`) is derived from
an optional local list of event timestamps
(`BacktestConfig.news_events_utc`, or `NewsConfig.calendar_file` live) --
never a live news feed, and never used to decide direction. Its only job is
to let the backtester and future risk rules segment or restrict around
news, exactly as Requirement 13 specifies: news changes *liquidity
conditions* the same sweep/displacement/confirmation pipeline still has to
satisfy, it never itself triggers a BUY or SELL.

## 5. Deliberately out of scope

No martingale, no grid, no averaging down, no multi-timeframe indicator
confluence, no news-direction trading, no discretionary override in code.
If a change to any of these rules is ever wanted, it must be made here and
in `engine/strategy/liquidity_sweep.py` together, with the test suite
(`tests/test_strategy.py`, `tests/test_market_structure.py`) updated to
match -- never as a live-only patch.
