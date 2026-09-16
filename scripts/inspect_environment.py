#!/usr/bin/env python3
"""Phase 1 environment inspection -- run this first on your Mac.

    python3 scripts/inspect_environment.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.env_inspect import inspect_environment  # noqa: E402


def main():
    report = inspect_environment()
    print("=" * 60)
    print("ENVIRONMENT REPORT")
    print("=" * 60)
    print(f"OS:               {report.os_name} {report.os_version} ({report.architecture})")
    print(f"macOS supported:  {'YES' if report.macos_supported else 'NO'}")
    print(f"Python:           {report.python_version}")
    print(f"MT5 app found:    {'YES' if report.mt5_app_found else 'NO'}")
    for p in report.mt5_app_paths:
        print(f"                  - {p}")
    print(f"Bridge directory: {report.bridge_dir}")
    print(f"EA heartbeat:     {'DETECTED' if report.ea_heartbeat_detected else 'not detected yet'}")
    if report.notes:
        print("\nNotes:")
        for n in report.notes:
            print(f"  - {n}")
    print("=" * 60)


if __name__ == "__main__":
    main()
