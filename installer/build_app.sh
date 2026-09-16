#!/usr/bin/env bash
# Build "Forex Trading System.app" from source. Run this ON YOUR MAC --
# it cannot be cross-compiled from Linux/Windows (py2app is macOS-only).
#
# Usage:  ./installer/build_app.sh
set -euo pipefail

if [[ "$(uname)" != "Darwin" ]]; then
  echo "This script must be run on macOS." >&2
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "==> Checking Python 3"
if ! command -v python3 >/dev/null; then
  echo "python3 not found. Install it from https://www.python.org/downloads/macos/ or 'brew install python' first." >&2
  exit 1
fi
PYVER="$(python3 -c 'import sys; print(sys.version_info[:2])')"
echo "    Found Python: $PYVER"

echo "==> Creating build virtual environment (.build-venv)"
python3 -m venv .build-venv
source .build-venv/bin/activate

echo "==> Installing dependencies"
pip install --upgrade pip >/dev/null
pip install -r requirements.txt
pip install py2app pywebview

echo "==> Running unit tests before packaging"
pip install pytest >/dev/null
python -m pytest tests -q

echo "==> Cleaning previous build"
rm -rf installer/build installer/dist

echo "==> Building app bundle with py2app"
(cd installer && python setup_py2app.py py2app)

APP_PATH="installer/dist/Forex Trading System.app"
if [[ -d "$APP_PATH" ]]; then
  echo ""
  echo "Build succeeded: $APP_PATH"
  echo "Next: ./installer/make_dmg.sh   (packages it into a .dmg installer)"
else
  echo "Build did not produce an .app bundle -- check the py2app output above." >&2
  exit 1
fi

deactivate
