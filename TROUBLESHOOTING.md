# Troubleshooting

## "Not connected" / bridge shows disconnected

- Confirm MT5 is open and logged in.
- Confirm `ForexBridgeEA` is attached to a chart with a smiling-face icon
  (not a sad face / red X) -- a sad face means Algo Trading is disabled
  either globally (toolbar toggle) or for that EA (Common tab checkbox).
- Check for `Common/Files/ForexTradingSystem/heartbeat.json` in your MT5
  data folder (File -> Open Data Folder in MT5, then
  `Common/Files/ForexTradingSystem/`... actually the *shared* Common folder
  is one level up from a specific terminal's data folder -- MT5 shows it at
  File -> Open Data Folder -> "Common" in the sidebar). Its `time` field
  should be within the last ~15 seconds; `FileBridge.is_connected()` treats
  anything older as stale on purpose (Requirement 11: never trade on
  unverifiable state).
- Check the Experts log tab in MT5 for compile/runtime errors from the EA.

## "No fresh heartbeat from the MT5 bridge EA yet"

Same as above -- the Python side is running fine, it just hasn't heard from
the EA. This is the intended fail-safe behavior, not a bug: no order will
ever be attempted while this is true.

## Trades are always REJECTED

Open the Trade Setup or Risk Monitor tab and read the actual reason --
every rejection is logged with one (`risk_events` table / `GET /api/setups`
`reasoning_json`). Common causes, all intentional:

- **"Minimum broker volume would exceed maximum allowed account risk"** --
  your account is too small for this symbol at this risk % right now. See
  SMALL_ACCOUNT.md; the Risk Monitor's Account Viability table shows the
  estimated minimum practical balance.
- **"Spread cost (...%) exceeds configured limit"** -- widen
  `max_spread_fraction_of_risk`/`max_spread_points` in Settings only if you
  understand you're accepting worse trade quality; the default is
  intentionally conservative for small accounts.
- **"R:R ... below minimum"** -- Rule 3 is a hard floor (3.0) and cannot be
  configured lower.
- **Kill switch / daily or weekly loss limit / max trades per day / max
  consecutive losses** -- all working as designed; check the Risk Monitor
  tab for which one is currently active.

## The app won't build (`installer/build_app.sh` fails)

- Must be run on macOS (`py2app` is macOS-only) -- see INSTALLATION.md.
- "python3 not found" -- install from python.org or `brew install python`.
- Test suite failure -- run `python -m pytest tests -v` directly to see
  which test failed; the build refuses to package a broken engine.
- Unsupported macOS version -- native MT5 (and this app's target) needs
  macOS 12 (Monterey) or later; `scripts/inspect_environment.py` reports
  your version.

## Gatekeeper blocks the app ("unidentified developer")

Expected for a locally-built, non-notarized app -- see the code-signing
section of INSTALLATION.md. Right-click -> Open once, or ad-hoc codesign it
yourself.

## Database is locked / UI seems stuck

The SQLite connection uses WAL mode specifically so the UI can read while
the orchestrator writes; if you see lock errors, check whether another
process (e.g. a second `ui.server` instance) has the same
`trading.db` open. Only run one instance of the app at a time.

## I changed a setting and nothing happened

Settings are saved via `POST /api/settings`, which also rebuilds the bridge
and orchestrator (`AppState.rebuild_bridge_and_orchestrator`) -- if the
bridge kind changed (mock <-> MT5 file bridge), give it a few seconds to
reconnect and check the status pill in the header.

## I want to see everything the system has ever logged

- Application logs: `~/Library/Application Support/ForexTradingSystem/logs/fts.log`
  (rotated, 5MB x 5 files).
- Structured history: the SQLite database at
  `~/Library/Application Support/ForexTradingSystem/trading.db` -- open it
  with any SQLite browser, or query via `GET /api/errors`,
  `GET /api/trades`, `GET /api/setups`, `GET /api/backtests`.
