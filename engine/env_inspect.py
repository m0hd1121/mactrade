"""Local environment inspection (Phase 1 / Requirement 20).

Used by both `scripts/inspect_environment.py` (run once from a terminal) and
the first-run setup wizard in the UI. Everything here is read-only and safe
to run repeatedly.
"""
from __future__ import annotations

import platform
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from engine.bridge.file_bridge import default_mt5_files_dir
from engine.bridge.protocol import HEARTBEAT_FILE


@dataclass
class EnvironmentReport:
    os_name: str
    os_version: str
    architecture: str
    is_macos: bool
    macos_supported: bool
    python_version: str
    mt5_app_found: bool
    mt5_app_paths: list[str] = field(default_factory=list)
    bridge_dir: str = ""
    bridge_dir_exists: bool = False
    ea_heartbeat_detected: bool = False
    notes: list[str] = field(default_factory=list)


MIN_MACOS_MAJOR = 12  # Monterey+ -- matches native MT5-for-Mac's own minimum


def _find_mt5_app() -> list[str]:
    candidates = [
        Path("/Applications/MetaTrader 5.app"),
        Path.home() / "Applications" / "MetaTrader 5.app",
    ]
    found = [str(p) for p in candidates if p.exists()]
    if not found:
        try:
            result = subprocess.run(
                ["mdfind", "kMDItemCFBundleIdentifier == 'net.metaquotes.metatrader5'"],
                capture_output=True, text=True, timeout=5,
            )
            found = [line for line in result.stdout.splitlines() if line.strip()]
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass
    return found


def inspect_environment() -> EnvironmentReport:
    os_name = platform.system()
    is_macos = os_name == "Darwin"
    os_version = platform.mac_ver()[0] if is_macos else platform.release()
    arch = platform.machine()

    macos_supported = True
    notes: list[str] = []
    if is_macos and os_version:
        try:
            major = int(os_version.split(".")[0])
            macos_supported = major >= MIN_MACOS_MAJOR
            if not macos_supported:
                notes.append(f"macOS {os_version} detected; native MT5 requires macOS {MIN_MACOS_MAJOR}+ (Monterey or later)")
        except ValueError:
            pass
    elif not is_macos:
        notes.append(f"Running on {os_name}, not macOS -- MT5 auto-detection and the file bridge are macOS-specific")

    mt5_paths = _find_mt5_app() if is_macos else []

    bridge_dir = default_mt5_files_dir()
    heartbeat_found = (bridge_dir / "ForexTradingSystem" / HEARTBEAT_FILE).exists()

    if is_macos and not mt5_paths:
        notes.append("MetaTrader 5.app not found in /Applications -- install it from your broker or metatrader5.com before continuing")
    if mt5_paths and not heartbeat_found:
        notes.append("MT5 found, but the bridge EA heartbeat hasn't appeared yet -- attach ForexBridgeEA.mq5 to a chart and enable Algo Trading (see MT5_SETUP.md)")

    return EnvironmentReport(
        os_name=os_name, os_version=os_version, architecture=arch, is_macos=is_macos,
        macos_supported=macos_supported, python_version=platform.python_version(),
        mt5_app_found=bool(mt5_paths), mt5_app_paths=mt5_paths,
        bridge_dir=str(bridge_dir / "ForexTradingSystem"), bridge_dir_exists=bridge_dir.exists(),
        ea_heartbeat_detected=heartbeat_found, notes=notes,
    )
