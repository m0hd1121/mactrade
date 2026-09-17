"""Packaged macOS app entry point.

Runs the local FastAPI backend (ui/server.py) in a background thread and
opens it in a native window via pywebview -- this is what py2app wraps into
"Forex Trading System.app". Running the CLI equivalent directly
(`python -m ui.server` + a normal browser tab) works identically for
development; this file exists only to give the packaged app its own window
instead of depending on the system browser.
"""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

# When frozen by py2app, engine/ and ui/ are bundled as a zipped or plain
# source tree next to this file; make sure it's importable either way.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Defaults to localhost-only -- see the same note in ui/server.py::main().
# Override FTS_HOST (e.g. to "0.0.0.0" for LAN/Tailscale reachability) by
# launching this binary from Terminal with the env var set; double-clicking
# the .app from Finder always uses the default. See INSTALLATION.md
# "Remote access".
HOST = os.environ.get("FTS_HOST", "127.0.0.1")
PORT = int(os.environ.get("FTS_PORT", "8765"))
# The embedded window always talks to itself over loopback, which still
# works even when HOST is a wildcard/external bind address -- "0.0.0.0"
# itself isn't a connectable address, and a specific interface IP is only
# reachable from other machines, not guaranteed the same way locally.
_LOCAL_HOST = "127.0.0.1" if HOST in ("0.0.0.0", "127.0.0.1") else HOST


def _run_server():
    import uvicorn
    from ui.server import app
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


def main():
    server_thread = threading.Thread(target=_run_server, daemon=True)
    server_thread.start()

    # Give uvicorn a moment to bind before pointing a window at it.
    time.sleep(1.5)

    try:
        import webview
    except ImportError:
        print(f"pywebview not installed; open http://{_LOCAL_HOST}:{PORT} in your browser instead.")
        while True:
            time.sleep(3600)

    webview.create_window("Forex Trading System", f"http://{_LOCAL_HOST}:{PORT}", width=1280, height=860, min_size=(1000, 700))
    webview.start()


if __name__ == "__main__":
    main()
