# MT5 Setup (macOS)

## 1. Install MT5 (if you haven't)

Download the native macOS build from your broker or metatrader5.com, and
log into your account normally in the terminal, exactly as you always
would. This project never touches your MT5 login/password -- it only
attaches an Expert Advisor to an already-logged-in terminal.

## 2. Install the bridge EA

```bash
./installer/install_mt5_bridge.sh
```

This copies `mt5_bridge/ForexBridgeEA.mq5` and
`mt5_bridge/Include/JsonBridge.mqh` into your MT5 data folder's
`MQL5/Experts` and `MQL5/Include`. If it can't find your MT5 data folder
(e.g. you haven't launched MT5 yet), it prints exactly where to copy the
files manually -- open MT5 -> **File -> Open Data Folder** to find it
yourself at any time.

## 3. Compile and attach the EA

1. In MT5, press **F4** (or Tools -> MetaEditor).
2. In the Navigator, find `ForexBridgeEA` under Experts, open it, and click
   **Compile** (or F7). Fix any path issue MetaEditor reports (it should
   just work if step 2 copied both files to the right folders).
3. Back in the main MT5 window, enable the **Algo Trading** toggle in the
   toolbar.
4. Drag `ForexBridgeEA` from the Navigator onto **any one chart** (symbol/
   timeframe don't matter -- the EA manages its own symbol list from its
   `InpSymbols` input, which defaults to the same seven pairs plus XAUUSD).
5. In the EA's properties dialog, **Common** tab, check "Allow Algo
   Trading" for this EA specifically, then OK.

You should see a smiling-face icon in the chart's corner (EA running) and,
within a couple of seconds, a `heartbeat.json` file appear under
`Common\Files\ForexTradingSystem\` in your MT5 data folder.

## 4. Point the app at it

In the app's Settings tab: Bridge kind = **MT5 File Bridge**, leave the
path override blank unless you have multiple MT5 installs (in which case
set it to the exact `.../Common/Files/ForexTradingSystem` path). Click
**Test Connection** -- it should report your broker, login, and balance.

## 5. What the EA actually does (and doesn't)

- Writes account info, per-symbol specs/quotes, open positions (only ones
  it opened -- filtered by `InpMagicNumber`), and newly-closed M5 bars to
  the shared `Common/Files/ForexTradingSystem/` folder every
  `InpTimerSeconds` (default 1s).
- Polls a `commands/` folder for order/close requests from the Python
  engine and writes matching results to `responses/`.
- Never touches positions it didn't open (matched by magic number), so it
  won't interfere with manual trades or other EAs.
- Places orders using MT5's standard `CTrade`/`OrderSend` API -- the same
  mechanism a "New Order" button click uses. No DLL imports, no sockets;
  see ARCHITECTURE.md for why.

## Troubleshooting

See TROUBLESHOOTING.md for heartbeat/connection issues specifically.
