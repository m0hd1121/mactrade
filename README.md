# Forex Trading System

A small-account-aware, price-action-only, MT5-based automated trading system
for macOS. It trades EURUSD, GBPUSD, USDJPY, AUDUSD, USDCHF, USDCAD, NZDUSD
(and optionally XAUUSD where the broker's specs make it viable) on the
5-minute chart using a single deterministic liquidity-sweep price-action
strategy -- no RSI, MACD, moving averages, or any other conventional
indicator anywhere in the codebase.

It is built to work honestly on very small accounts ($20-$100), which means
it is also built to say **no trade** whenever the broker's minimum lot size
would force more risk than configured. Capital preservation always wins over
trade frequency.

## What's here

| Path | What it is |
|---|---|
| `engine/market_structure/` | Swing points, BOS/CHOCH, liquidity pools, sweeps, sessions -- pure OHLC math |
| `engine/strategy/` | The one trading strategy (liquidity sweep + displacement + confirmation) |
| `engine/risk/` | Position sizing, small-account viability, the risk gate every trade passes through |
| `engine/bridge/` | Broker abstraction: `MockBridge` (offline demo), `FileBridge` (real MT5 on macOS) |
| `mt5_bridge/` | The MQL5 Expert Advisor that runs inside MT5 and talks to `FileBridge` |
| `engine/backtest/` | Event-driven backtester, small-account sweep, walk-forward, Monte Carlo |
| `engine/orchestrator/` | Paper/live trading loop, kill switch, state resync |
| `engine/db/` | SQLite persistence (trades, signals, risk events, backtests, ...) |
| `ui/` | Local FastAPI dashboard (Dashboard / Market Monitor / Trade Setup / Risk Monitor / Backtesting / Settings) |
| `installer/` | py2app + dmg build scripts to package it as a real macOS app |
| `tests/` | pytest suite covering the engine end-to-end |

## Quick start (development, any OS)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m pytest tests -q          # 25 tests, no MT5 needed
python -m ui.server                # opens the dashboard at http://127.0.0.1:8765
```

With no MT5 connected, the dashboard runs against `MockBridge` (a clearly
labeled offline paper-trading simulator) so you can explore the whole UI
before touching a real account.

## Quick start (your Mac, with real MT5)

1. Read `MT5_SETUP.md` and install the bridge EA (`installer/install_mt5_bridge.sh`).
2. Read `INSTALLATION.md` and either run from source (`scripts/run_paper.py`)
   or build the packaged `.app`/`.dmg` (`installer/build_app.sh`).
3. Open the dashboard, complete the first-run setup wizard, confirm MT5
   connects, review the risk settings, and press **Start** in **PAPER** mode.
4. Only after you've watched it operate in Paper mode do you consider Live
   -- see `INSTALLATION.md` for how that confirmation works.

## The 14 rules this system will not break

See `RISK_MANAGEMENT.md` for the full list and where each is enforced in
code. The short version: every trade needs a predefined SL and TP before it
exists, R:R must be >= 1:3, risk never exceeds the configured percentage no
matter how small the account is, no indicators, no assumed news direction,
live trading never turns itself on, and a failed MT5/account state check
means no order gets sent.

## Further reading

- `ARCHITECTURE.md` -- how the pieces fit together, and why the MT5 bridge
  is file-based rather than a Python API call
- `STRATEGY.md` -- the exact, programmable rules for every trade decision
- `RISK_MANAGEMENT.md` -- the risk engine and the 14 non-negotiable rules
- `SMALL_ACCOUNT.md` -- what "small account optimized" actually means here
- `BACKTESTING.md` -- how to run real backtests (and what the bundled demo data is/isn't)
- `MT5_SETUP.md` -- installing the bridge EA and connecting to your broker
- `INSTALLATION.md` -- building and installing the macOS app
- `TROUBLESHOOTING.md` -- common failure modes and what they mean
