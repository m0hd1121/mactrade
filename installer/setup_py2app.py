"""py2app build spec. Run ONLY on macOS via installer/build_app.sh.

    cd installer && python3 setup_py2app.py py2app

Produces installer/dist/Forex Trading System.app.
"""
from __future__ import annotations

import sys
from pathlib import Path

from setuptools import setup

ROOT = Path(__file__).resolve().parent.parent
ICON = Path(__file__).parent / "icon.icns"

# py2app's package scanner (modulegraph) resolves entries in OPTIONS["packages"]
# via normal Python import machinery against sys.path. This script runs with
# cwd=installer/ (see build_app.sh: `cd installer && python setup_py2app.py py2app`),
# and engine/ and ui/ live one directory up, so without this they're invisible
# to py2app and it fails with "ImportError: No module named 'engine'".
sys.path.insert(0, str(ROOT))

APP = [str(Path(__file__).parent / "app_main.py")]
DATA_FILES = [
    ("ui/static", [str(p) for p in (ROOT / "ui" / "static").glob("*")]),
    ("engine/db", [str(ROOT / "engine" / "db" / "schema.sql")]),
]

OPTIONS = {
    "argv_emulation": False,
    # "anyio" is listed here (not left to modulegraph's static scan) because it
    # picks its async backend with a runtime importlib.import_module() call
    # (anyio._backends._asyncio) that a static scanner can't see -- without
    # this, the packaged app 500s on its first request with
    # "ModuleNotFoundError: No module named 'anyio._backends'". "sniffio" is
    # anyio's own small dependency, included for the same reason.
    "packages": ["engine", "ui", "fastapi", "starlette", "uvicorn", "pydantic", "webview", "anyio", "sniffio"],
    "includes": ["sqlite3", "email.mime.multipart", "anyio._backends._asyncio"],
    "iconfile": str(ICON) if ICON.exists() else None,
    "plist": {
        "CFBundleName": "Forex Trading System",
        "CFBundleDisplayName": "Forex Trading System",
        "CFBundleIdentifier": "com.forextradingsystem.app",
        "CFBundleShortVersionString": "1.0.0",
        "CFBundleVersion": "1.0.0",
        "LSMinimumSystemVersion": "12.0",
        "NSHighResolutionCapable": True,
        "NSHumanReadableCopyright": "Personal-use trading tool. No warranty. See README.md.",
        # loopback-only HTTP to our own bundled server; no external network access needed
        "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
    },
}

if __name__ == "__main__":
    if sys.platform != "darwin":
        raise SystemExit("setup_py2app.py must be run on macOS (py2app is macOS-only). See INSTALLATION.md.")
    setup(
        app=APP,
        name="Forex Trading System",
        data_files=DATA_FILES,
        options={"py2app": OPTIONS},
        setup_requires=["py2app"],
    )
