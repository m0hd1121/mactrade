"""Locates the real on-disk MT5 terminal folder(s) on macOS.

MT5 for macOS runs inside a lightweight bundle MetaQuotes ships under
`net.metaquotes.wine.metatrader5`, but the exact subpath to a given
terminal's own `MQL5/` folder varies by install: a "portable" install keeps
it right next to the program files
(`.../drive_c/Program Files/MetaTrader 5/MQL5`), while a standard install
uses the classic Windows-style per-terminal
`AppData/Roaming/MetaQuotes/Terminal/<hash>/MQL5` layout. Rather than assume
either (an earlier version of this module did, and was wrong against a real
install), this searches for it directly.
"""
from __future__ import annotations

from pathlib import Path

WINE_CONTAINER_ROOT = Path.home() / "Library" / "Application Support" / "net.metaquotes.wine.metatrader5" / "drive_c"


def _bounded_walk(root: Path, max_depth: int):
    if not root.exists():
        return
    stack: list[tuple[Path, int]] = [(root, 0)]
    while stack:
        current, depth = stack.pop()
        try:
            entries = list(current.iterdir())
        except (PermissionError, OSError):
            continue
        for entry in entries:
            if entry.is_dir():
                yield entry
                if depth < max_depth:
                    stack.append((entry, depth + 1))


def find_mql5_dirs(max_depth: int = 8) -> list[Path]:
    """All 'MQL5' directories under the MT5 container, depth-bounded so this
    stays fast even in a large Wine-style prefix."""
    return [d for d in _bounded_walk(WINE_CONTAINER_ROOT, max_depth) if d.name == "MQL5"]


def find_mt5_files_dir() -> Path | None:
    """The bridge directory: <terminal>/MQL5/Files for the first MT5 terminal
    found. Deliberately the terminal-local Files/ folder, not the separate
    "Common" data folder -- see ARCHITECTURE.md. This only ever needs to work
    for the single terminal the user is actually trading through, and using
    the terminal-local folder sidesteps a second, less consistently-located
    path to search for."""
    dirs = find_mql5_dirs()
    if not dirs:
        return None
    return dirs[0] / "Files"


def find_mql5_experts_dirs() -> list[Path]:
    return [d / "Experts" for d in find_mql5_dirs() if (d / "Experts").exists()]
