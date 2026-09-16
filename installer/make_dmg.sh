#!/usr/bin/env bash
# Package the built .app into ForexTradingSystem.dmg. Run AFTER build_app.sh,
# ON macOS (uses hdiutil, which is macOS-only).
set -euo pipefail

if [[ "$(uname)" != "Darwin" ]]; then
  echo "This script must be run on macOS." >&2
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

APP_PATH="installer/dist/Forex Trading System.app"
if [[ ! -d "$APP_PATH" ]]; then
  echo "Build the app first: ./installer/build_app.sh" >&2
  exit 1
fi

STAGE_DIR="$(mktemp -d)"
cp -R "$APP_PATH" "$STAGE_DIR/"
ln -s /Applications "$STAGE_DIR/Applications"

DMG_PATH="installer/dist/ForexTradingSystem.dmg"
rm -f "$DMG_PATH"

echo "==> Creating $DMG_PATH"
hdiutil create -volname "Forex Trading System" -srcfolder "$STAGE_DIR" -ov -format UDZO "$DMG_PATH"

rm -rf "$STAGE_DIR"

echo ""
echo "Done: $DMG_PATH"
echo "Optional: codesign + notarize before distributing outside this Mac (see INSTALLATION.md)."
echo "For local personal use, ad-hoc signing is enough:"
echo "  codesign --force --deep --sign - \"$APP_PATH\""
