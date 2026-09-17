#!/usr/bin/env python3
"""Launch the app in PAPER mode (the default -- Requirement 19).

    python3 scripts/run_paper.py

Opens the dashboard at http://127.0.0.1:8765. Trading only starts once you
press Start in the UI (or POST /api/safety/start); nothing trades
automatically at launch.
"""
import os
import sys
import webbrowser
from pathlib import Path
from threading import Timer

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main():
    from ui.server import main as run_server, state

    if state.config.mode != "PAPER":
        state.config.mode = "PAPER"
        state.save_config()

    host = os.environ.get("FTS_HOST", "127.0.0.1")
    port = os.environ.get("FTS_PORT", "8765")
    local_host = "127.0.0.1" if host in ("0.0.0.0", "127.0.0.1") else host
    Timer(1.5, lambda: webbrowser.open(f"http://{local_host}:{port}")).start()
    run_server()


if __name__ == "__main__":
    main()
