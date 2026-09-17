# Installation

## Two ways to run this

1. **From source** (works today, any platform, good for development and
   for trying paper trading before you build the packaged app).
2. **Packaged macOS app** (`.app` / `.dmg`) -- built with the scripts in
   `installer/`. **These build scripts only run on macOS** (py2app and
   `hdiutil` are macOS-only); they cannot be cross-compiled from Linux or
   Windows, so you build the app on your own Mac.

## Option 1: From source

```bash
git clone <this repo> && cd mactrade
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m pytest tests -q            # confirms the engine works on your machine
python -m ui.server                  # or scripts/run_paper.py / run_live.py
```

Open http://127.0.0.1:8765. With no MT5 connected yet you'll see the
offline mock-bridge demo; follow MT5_SETUP.md to connect for real.

## Option 2: Build the packaged macOS app

```bash
./installer/build_app.sh     # creates a venv, runs tests, builds the .app with py2app
./installer/make_dmg.sh      # packages it into installer/dist/ForexTradingSystem.dmg
```

`build_app.sh` fails loudly (not silently) if:
- it isn't run on macOS,
- Python 3 isn't found,
- the test suite doesn't pass,
- py2app doesn't produce an `.app` bundle.

The result: `installer/dist/Forex Trading System.app` and
`installer/dist/ForexTradingSystem.dmg`.

### Installing the built app

```
Open ForexTradingSystem.dmg
  -> drag "Forex Trading System.app" onto the Applications shortcut
  -> open it from Applications (or Spotlight)
  -> first-run setup wizard runs automatically
  -> MT5 detected? -> Test Connection -> confirm risk settings -> Start Paper Trading
```

### Code signing / Gatekeeper

The app is not notarized or signed with a paid Apple Developer certificate
by default (there's no CI environment here with your signing identity). For
**local personal use on the Mac that built it**, an ad-hoc signature is
enough to satisfy Gatekeeper:

```bash
codesign --force --deep --sign - "installer/dist/Forex Trading System.app"
```

If macOS still says the app "can't be opened because it is from an
unidentified developer," right-click the app -> Open, once, to override
Gatekeeper for that app.

To distribute the `.dmg` to other machines without that prompt, you'd need
an Apple Developer ID and to codesign with `installer/entitlements.plist` +
notarize via `xcrun notarytool` -- see comments in that file for the exact
command. This is optional and not required for running it yourself.

## First-run setup wizard

Launching the app (packaged or `python -m ui.server`) the first time shows:

1. **Welcome** -- version/introduction.
2. **MT5 Connection** -- runs the same environment check as
   `scripts/inspect_environment.py`, reports whether MT5 and the bridge
   heartbeat are detected, and lets you Test Connection.
3. **Risk Management** -- pick risk-per-trade (0.25/0.5/0.75/1%, default
   0.5%) and daily loss limit.
4. **Trading Mode** -- Backtest / Paper (default, recommended) / Live.
   Choosing Live here does **not** activate live trading by itself -- see
   below.

## Activating live trading (Rule 10 -- never automatic)

Two separate things must both be true, and neither is ever set for you:

1. Settings -> Mode = `LIVE`.
2. Settings -> "Live trading confirmed?" = Yes.

`TradingOrchestrator` checks both again, in code, immediately before
sending any real order (`_attempt_trade` in
`engine/orchestrator/live_orchestrator.py`) -- there's no path that skips
this check.

## Remote access (checking the dashboard from your phone)

By default the server only binds to `127.0.0.1` -- your Mac itself -- and
**there is no login/password on the API**. That's deliberate for a
strictly-local tool, but it matters a lot if you open it up: every control
on this dashboard (Start/Pause, the Kill Switch, Close All, and Settings --
including switching to LIVE mode) is reachable to anything that can reach
the bound address, with nothing in front of it.

The recommended way to reach it from your phone without exposing it to your
whole home network or the public internet is a personal VPN mesh like
[Tailscale](https://tailscale.com) (free for personal use):

1. Install Tailscale on your Mac (`brew install --cask tailscale` or from
   tailscale.com) and on your phone (App Store / Play Store), and sign into
   the same account on both.
2. Find your Mac's Tailscale address: `tailscale ip -4` (looks like
   `100.x.y.z`).
3. Launch the server bound to all interfaces (so it's reachable via
   Tailscale, and still works locally too) instead of the localhost-only
   default:
   ```bash
   FTS_HOST=0.0.0.0 python -m ui.server
   ```
   (or, for the packaged app, launch it from Terminal instead of double-
   clicking: `FTS_HOST=0.0.0.0 "installer/dist/Forex Trading System.app/Contents/MacOS/Forex Trading System"`
   -- environment variables only apply when launched this way, not from
   Finder/Spotlight.)
4. On your phone, with Tailscale connected, open
   `http://100.x.y.z:8765` in a browser (add it to your home screen for an
   app-like shortcut).

`FTS_HOST=0.0.0.0` also makes it reachable from anyone else on your home
Wi-Fi, not just via Tailscale -- if you want it Tailscale-only, bind to that
specific `100.x.y.z` address instead of `0.0.0.0` (note this also removes
plain `127.0.0.1` access on the Mac itself, since a socket bound to one
specific interface only accepts connections on that interface).

This setup intentionally has no auth layer in front of it -- reasonable
given Tailscale already restricts reachability to devices logged into your
own account, but worth reconsidering (a shared passphrase gate on the API
would be a small addition) if you ever add other people to your tailnet or
switch to broader LAN exposure.

## Uninstalling

Drag the app to the Trash. Its data lives entirely under
`~/Library/Application Support/ForexTradingSystem/` (config, SQLite
database, logs, safety state) -- delete that folder too if you want a
completely clean removal. The MT5 bridge EA files
(`MQL5/Experts/ForexBridgeEA.mq5`, `MQL5/Include/JsonBridge.mqh`) live
inside MT5's own data folder and are unaffected; remove them from MT5's
Navigator (right-click -> Delete) if you no longer want the EA.

## Restarting / crash recovery

On every start, the orchestrator re-reads account/position state from MT5
directly (`TradingOrchestrator._resync_open_positions`) rather than
trusting anything cached locally, and the kill switch / running state is
persisted to `safety_state.json` so a crash or Mac sleep/wake can never
silently re-enable trading (Requirement 22).
