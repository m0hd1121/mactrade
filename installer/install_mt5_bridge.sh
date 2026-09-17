#!/usr/bin/env bash
# Copies the bridge EA (mt5_bridge/) into your MT5 terminal's MQL5/Experts
# folder so MetaEditor can compile it. Run on macOS with MT5 already
# installed at least once (so its data folder exists).
#
# If this can't find your terminal automatically, open MT5 -> File -> Open
# Data Folder, then manually copy mt5_bridge/ForexBridgeEA.mq5 and
# mt5_bridge/Include/JsonBridge.mqh into MQL5/Experts and MQL5/Include
# respectively. See MT5_SETUP.md for the full walkthrough either way.
set -euo pipefail

if [[ "$(uname)" != "Darwin" ]]; then
  echo "This script is for macOS. On another platform, copy mt5_bridge/ into your MT5 data folder manually." >&2
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WINE_ROOT="$HOME/Library/Application Support/net.metaquotes.wine.metatrader5/drive_c"

# The subpath from WINE_ROOT to a given terminal's own MQL5/ folder varies by
# install -- a "portable" install keeps it at ".../Program Files/MetaTrader 5/
# MQL5", a standard install uses the classic per-terminal
# ".../users/*/AppData/Roaming/MetaQuotes/Terminal/<hash>/MQL5" layout. Search
# broadly instead of assuming either.
if [[ ! -d "$WINE_ROOT" ]]; then
  echo "Could not find a MetaTrader 5 data folder under:"
  echo "  $WINE_ROOT"
  echo ""
  echo "Open MetaTrader 5 at least once, then in the app: File -> Open Data Folder,"
  echo "and manually copy:"
  echo "  $ROOT_DIR/mt5_bridge/ForexBridgeEA.mq5   -> MQL5/Experts/"
  echo "  $ROOT_DIR/mt5_bridge/Include/JsonBridge.mqh -> MQL5/Include/"
  exit 1
fi

found=0
while IFS= read -r experts_dir; do
  found=1
  terminal_dir="$(dirname "$(dirname "$experts_dir")")"
  include_dir="$terminal_dir/MQL5/Include"
  mkdir -p "$include_dir"
  cp "$ROOT_DIR/mt5_bridge/ForexBridgeEA.mq5" "$experts_dir/"
  cp "$ROOT_DIR/mt5_bridge/Include/JsonBridge.mqh" "$include_dir/"
  echo "Installed bridge EA into: $experts_dir"
done < <(find "$WINE_ROOT" -maxdepth 8 -type d -path "*/MQL5/Experts")

if [[ "$found" -eq 0 ]]; then
  echo "No MQL5/Experts folder found under any terminal instance yet."
  echo "Launch MetaTrader 5 once (so it creates its data folder), then re-run this script."
  exit 1
fi

echo ""
echo "Next steps (in MT5):"
echo "  1. Open MetaEditor (F4), find ForexBridgeEA.mq5 under Experts, and click Compile."
echo "  2. Back in MT5, drag ForexBridgeEA onto any one chart."
echo "  3. Enable 'Allow Algo Trading' (toolbar toggle) and check the same box in the EA's Common tab."
echo "  4. Confirm it's running: the app's Settings -> Test Connection should report your account."
