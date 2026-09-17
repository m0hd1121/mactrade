# Architecture

## Why a file-based MT5 bridge (Requirement 20, Phase 1/2)

This system was designed against a specific, verifiable constraint: the
official `MetaTrader5` Python package wraps a **Windows DLL** exported by the
Windows MT5 terminal. Native macOS MT5 (the app you get from
metatrader5.com or your broker, running without Wine/CrossOver/a VPS) has no
such DLL for Python to call, and MQL5 running inside it **cannot import
external DLLs either** (no `wsock32.dll`, no raw sockets) -- so the other
common bridge trick, a socket-based EA, isn't reliably available on macOS
the way it is on Windows.

What MQL5 CAN always do, on every MT5 build including native macOS, is read
and write plain files in its own sandboxed `MQL5/Files/` folder. So that's
the bridge:

```
 Python engine (this repo)              MT5 terminal (already installed)
 ┌─────────────────────────┐            ┌──────────────────────────────┐
 │ FileBridge               │  writes   │  ForexBridgeEA.mq5            │
 │  - reads account.json    │ <──────── │   - account.json (each tick)  │
 │  - reads symbols/*.json  │ <──────── │   - symbols/<SYM>.json         │
 │  - reads bars/*.csv      │ <──────── │   - bars/<SYM>_M5.csv          │
 │  - reads positions.json  │ <──────── │   - positions.json             │
 │  - writes commands/*.json│ ────────> │   - polls commands/, executes  │
 │  - reads responses/*.json│ <──────── │   - writes responses/*.json    │
 └─────────────────────────┘            └──────────────────────────────┘
      both sides only touch  <MT5 terminal data folder>/MQL5/Files/ForexTradingSystem/
```

That's the terminal's own `MQL5/Files/` folder, not MQL5's separate
cross-terminal "Common\Files" folder (reachable via the `FILE_COMMON` flag).
An earlier version of this bridge used Common\Files; it was dropped because
this only ever needs to work for the one terminal the user actually trades
through, and MT5's exact on-disk path to a terminal's own `MQL5/` folder is
far more reliably locatable than the separate Common folder's path, which
varies by install (see `engine/mt5_paths.py`, which searches for it rather
than assuming a fixed layout).

No Wine, no Docker, no VPS, no Windows -- explicitly ruled out by
Requirement 20, and unnecessary given the file bridge works. The full
message schema is documented in `engine/bridge/protocol.py` (the single
source of truth both `FileBridge` and the EA are written against) and
`MT5_SETUP.md`.

`MockBridge` implements the exact same `BrokerBridge` interface
(`engine/bridge/base.py`) with an in-memory simulator, so the strategy, risk
engine, orchestrator and UI never know or care which bridge is underneath.
It exists for local development/demo before MT5 is connected -- it is never
used for BACKTEST (real history only) or LIVE (real MT5 only).

## Data flow, end to end

```
MT5 (via FileBridge)                                    SQLite (engine/db)
      │  new M5 bar                                            ▲
      ▼                                                         │ every signal,
MarketStructureEngine  ──►  LiquiditySweepStrategy  ──►  Signal │ rejection,
 (swings, BOS/CHOCH,          (sweep→displacement→                │ risk event,
  liquidity, sessions)         confirmation→entry/SL/TP)          │ trade, error
      │                              │                            │
      │                        Signal.status == READY             │
      │                              ▼                            │
      │                        RiskEngine.evaluate_trade  ────────┤
      │                          (symbol spec, account,           │
      │                           position sizing, limits)        │
      │                              │ approved                   │
      │                              ▼                            │
      │                   TradingOrchestrator: PAPER sim ──────────┘
      │                     or LIVE bridge.send_order()
      ▼
 (UI polls the DB + bridge every few seconds -- ui/server.py -> ui/static/)
```

`Backtester` (`engine/backtest/backtester.py`) runs the identical
`MarketStructureEngine` + `LiquiditySweepStrategy` + `RiskEngine` code
against historical bars instead of live ticks -- there is no separate
backtest-only strategy implementation to drift out of sync.

## Module map

- `engine/types.py` -- every shared dataclass (Bar, SymbolSpec, TradePlan,
  Signal, ...). No third-party dependencies; imported everywhere.
- `engine/config.py` -- `AppConfig` (pydantic), loaded from/saved to
  `~/Library/Application Support/ForexTradingSystem/config.json` on macOS.
- `engine/market_structure/` -- see STRATEGY.md for the exact definitions.
- `engine/strategy/liquidity_sweep.py` -- the one strategy.
- `engine/risk/` -- see RISK_MANAGEMENT.md.
- `engine/bridge/` -- see above.
- `engine/db/` -- SQLite schema + typed access layer.
- `engine/backtest/` -- see BACKTESTING.md.
- `engine/orchestrator/` -- ties it together for PAPER/LIVE; not used by
  BACKTEST, which drives `Backtester` directly.
- `ui/server.py` + `ui/static/` -- the dashboard.
- `mt5_bridge/` -- the MQL5 EA.
- `installer/` -- macOS packaging (py2app, dmg, entitlements).

## Why SQLite, why FastAPI+vanilla JS, why no ORM

Requirement 25 asks for low resource usage: a single-file embedded database
needs no server process, `pydantic` + stdlib `sqlite3` cover validation and
persistence without an ORM's overhead, and the dashboard is a single static
HTML/CSS/JS bundle served by FastAPI locally on `127.0.0.1` -- no build
step, no JS framework, no external CDN dependency at runtime.

## Trading modes

- **BACKTEST**: `Backtester` only; never touches the bridge or a live
  account.
- **PAPER** (default): `TradingOrchestrator` connects to the REAL MT5
  bridge for real quotes/specs/account balance, but fills and P/L are
  simulated locally (`engine/orchestrator/paper_execution.py`) -- no
  `ORDER` command is ever sent to MT5.
- **LIVE**: same orchestrator, but `send_order`/`close_position` actually
  reach the EA. Gated by `AppConfig.is_live()`, which requires both
  `mode == "LIVE"` AND an explicit `live_trading_confirmed = true` set
  through the Settings tab -- never inferred, never defaulted (Rule 10).
