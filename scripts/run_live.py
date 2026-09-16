#!/usr/bin/env python3
"""Launch the app with LIVE trading available.

This does NOT enable live trading by itself (Rule 10). It still requires:
  1. mode == "LIVE" in Settings
  2. live_trading_confirmed == true, set explicitly via the Settings tab

Both are enforced again inside the orchestrator immediately before any
order would be sent -- there is no code path that bypasses this.

    python3 scripts/run_live.py
"""
import sys
import webbrowser
from pathlib import Path
from threading import Timer

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main():
    from ui.server import main as run_server, state

    print("=" * 70)
    print(" LIVE TRADING MODE")
    print(" Orders placed from this session can use real money.")
    print(" Live trading will NOT start until you explicitly confirm it")
    print(" in the Settings tab (mode=LIVE, live_trading_confirmed=true).")
    print("=" * 70)

    Timer(1.5, lambda: webbrowser.open("http://127.0.0.1:8765")).start()
    run_server()


if __name__ == "__main__":
    main()
