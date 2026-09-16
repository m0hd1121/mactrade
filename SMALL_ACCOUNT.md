# Small-Account Optimization

## What "optimized for small accounts" means here

It does **not** mean higher risk percentages, martingale sizing, or forcing
trades to happen. It means: dynamically figuring out, from the broker's
*actual* symbol specifications, whether a trade is executable at all within
your configured risk -- and refusing to trade when it isn't, instead of
silently taking on more risk than you asked for.

## The mechanism

Every symbol spec pulled from MT5 (`engine/types.SymbolSpec`, via
`FileBridge.get_symbol_spec`) carries: minimum/maximum/step volume, contract
size, tick size, tick value, margin per lot, minimum stop distance, trading
mode, and currencies. `engine/risk/position_sizer.py` uses all of it (see
RISK_MANAGEMENT.md for the algorithm) to find the *smallest executable*
position size, and rejects the trade outright if even that minimum would
exceed your configured risk:

```
TRADE REJECTED
Reason: Minimum broker volume would exceed maximum allowed account risk.
Account:            $50.00
Maximum risk:       $0.25   (0.5% configured)
Required minimum risk: $8.70  (broker's 0.01-lot minimum on this symbol)
Result: NO TRADE
```

(`tests/test_risk_engine.py::test_small_account_rejected_when_min_volume_exceeds_risk`
reproduces exactly this scenario.)

## Why the focus is Forex pairs, not XAUUSD, for small accounts

Gold's typical contract size and tick value make its minimum-lot risk much
larger in absolute terms than a major FX pair's, for the same stop
distance in points. The system does not hard-code "gold is bad for small
accounts" -- it computes it, per broker, per account size, via the same
viability check every other symbol goes through
(`GET /api/account-viability`, `engine/risk/symbol_spec.py`). On most
brokers this does mean XAUUSD needs a noticeably larger account than
EURUSD/GBPUSD/USDJPY/etc. to clear the same risk bar, but the UI always
shows you the *computed* answer for your actual broker, never an assumption.

## Minimum practical account size, per symbol

`minimum_practical_balance` in the account-viability output
(`engine/risk/symbol_spec.py::minimum_practical_balance`) answers: "given
this symbol's broker-reported minimum lot and a typical recent stop
distance, what's the smallest balance at which that minimum lot's risk
equals my configured risk percentage?" It's a live number, recomputed from
current broker specs and recent price action -- not a table of hard-coded
constants.

## Small-account backtesting (Requirement 17)

`engine/backtest/small_account_sweep.py::run_small_account_sweep` reruns
the *entire* backtest -- same strategy, same risk engine, same broker
constraints -- at each of a ladder of starting balances (default $20, 30,
50, 75, 100, 250, 500, 1000). This is explicitly **not** a linear rescale of
a large-account result: at $20 the position sizer may reject every single
setup (0 trades, "not viable"), while at $1000 the same historical period
might trade normally. The sweep report shows exactly where that boundary
is, and how many setups were rejected specifically for account-size reasons
(`trades_rejected_for_account_size`) versus every other reason (bad R:R,
spread cost, structure). Run it from the Backtesting tab (check
"Small-account sweep") or `scripts/run_backtest.py --sweep`.

## What this system will never do for a small account

- Increase `risk_per_trade_pct` because the balance is low (Rule 5).
- Force a trade through by ignoring the broker's minimum volume (Rule 6).
- Hide a rejected trade -- every rejection is logged with its exact reason
  (`risk_events` table, Trade Setup tab, `errors`/`signals` logs).
- Assume a fixed "small account minimum" like $100 or $500 -- the real
  number is always computed from your broker's live specs.
