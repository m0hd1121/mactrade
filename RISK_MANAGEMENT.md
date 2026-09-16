# Risk Management

## The 14 rules, and where each is enforced

| # | Rule | Enforced in |
|---|---|---|
| 1 | Never enter without a predefined SL | `LiquiditySweepStrategy._build_plan` always sets `stop_loss` before a `TradePlan` exists; `RiskEngine`/`Backtester` never accept a plan without one |
| 2 | Never enter without a predefined TP | same -- `take_profit` set in the same step as `stop_loss` |
| 3 | Never enter if R:R < 1:3 | `RiskConfig.min_reward_risk` has a pydantic floor of 3.0 (`engine/config.py`); checked again in the strategy (`LiquiditySweepStrategy.evaluate`) and a third time in `RiskEngine.evaluate_trade` |
| 4 | Never exceed configured risk | `engine/risk/position_sizer.py`: position size is derived FROM the risk cap, never the other way around |
| 5 | Never raise risk because the account is small | there is no code path that reads `account.balance` to choose `risk_per_trade_pct` -- it is only ever the configured value; see `tests/test_risk_engine.py::test_risk_never_widens_for_small_accounts` |
| 6 | If the broker's minimum volume would exceed allowed risk: **no trade** | `calculate_position_size`: computes `required_minimum_risk = volume_min * loss_per_lot` and rejects outright if it exceeds `max_risk_amount` -- this is the exact scenario in the spec, reproduced in `tests/test_risk_engine.py::test_small_account_rejected_when_min_volume_exceeds_risk` |
| 7 | Never use conventional indicators | see STRATEGY.md -- grep the repo, there are none |
| 8 | Never assume news direction | see STRATEGY.md section 4 |
| 9 | Never claim guaranteed profits | see the disclaimers in this file, BACKTESTING.md, and the UI copy |
| 10 | Never auto-activate LIVE | `AppConfig.is_live()` requires `mode=="LIVE"` AND an explicit `live_trading_confirmed=true`, set only through Settings; `TradingOrchestrator._attempt_trade` re-checks it immediately before sending any live order |
| 11 | Never send an order if MT5/account state can't be verified | `FileBridge` raises `BridgeConnectionError` on stale/missing heartbeat or unreadable state files, which the orchestrator logs and skips rather than trading through |
| 12 | Never rely solely on backtest performance | see BACKTESTING.md -- walk-forward, Monte Carlo, and this document's own disclaimers |
| 13 | Never overfit to maximize historical returns | see BACKTESTING.md walk-forward section |
| 14 | Never sacrifice risk management for trade count | there is no "loosen risk to get more trades" setting; `max_trades_per_day` limits frequency, it never relaxes sizing |

## The position-sizing algorithm (Requirement 3/14)

`engine/risk/position_sizer.py::calculate_position_size`:

1. Reject if the symbol's trade mode disallows this direction (`DISABLED`,
   `CLOSEONLY`, or the wrong `LONGONLY`/`SHORTONLY`).
2. `max_risk_amount = account.equity * risk_per_trade_pct / 100`.
3. Reject if the plan's SL distance is narrower than the broker's own
   minimum stop distance (`SYMBOL_TRADE_STOPS_LEVEL`).
4. `loss_per_lot = (risk_price_distance / tick_size) * tick_value` -- this
   is the broker's actual, symbol-specific cost of a 1.0-lot position
   moving that stop distance.
5. `required_minimum_risk = volume_min * loss_per_lot`. **If this exceeds
   `max_risk_amount`, stop here: REJECTED.** This is Rule 6, verbatim.
6. Otherwise, `ideal_volume = max_risk_amount / loss_per_lot`, floored to
   the broker's `volume_step` and clamped to `[volume_min, volume_max]`.
7. Recompute `actual_risk_amount` from the rounded volume, verify it's
   still within margin (`account.margin_free`) and within a small rounding
   tolerance of the configured risk. Approve.

Every number in this algorithm -- `volume_min`, `volume_step`,
`contract_size`, `tick_size`, `tick_value`, `margin_initial_per_lot`,
`stops_level_points`, `trade_mode` -- comes from the broker's live
`SymbolSpec`, fetched fresh from MT5 through the bridge
(`FileBridge.get_symbol_spec`, backed by the EA's `OrderCalcMargin` call for
margin and `SymbolInfoDouble`/`SymbolInfoInteger` for everything else).
Nothing here is a hard-coded assumption about any specific broker.

## Account viability (Requirement 6)

`engine/risk/symbol_spec.py::account_viability` runs the same sizing math in
reverse for every configured symbol using a recent-price-derived "typical"
stop distance (a plain median of recent bar ranges -- not a smoothed
indicator), and reports:

- `tradable`: would the broker's minimum lot fit inside configured risk
  right now?
- `minimum_practical_balance`: the smallest balance at which the broker's
  minimum lot's risk equals the configured risk percentage for that
  symbol's typical stop distance.

This runs on every dashboard load (`GET /api/account-viability`) and in the
setup wizard, so a $50 account sees exactly which of the seven pairs (plus
XAUUSD) are realistically tradable *today*, on *this broker*, not a
generic assumption.

## Other gates in `RiskEngine.evaluate_trade`, in order

Kill switch -> R:R floor -> max concurrent positions -> max trades/day ->
consecutive-loss pause -> daily loss limit -> weekly loss limit -> spread /
transaction-cost check -> position sizing (above). Any single failure
rejects the trade with a specific, logged reason; nothing here ever loosens
a limit to make a trade fit.

## Disclaimer

This system, its backtests, and its risk model are decision-support tools,
not a guarantee of profit. Forex trading carries a real risk of loss,
amplified by leverage, and past performance (backtested or live) does not
predict future results. Nothing in this repository should be read as
investment advice.
