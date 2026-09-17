"""The file-based bridge protocol shared with mt5_bridge/ForexBridgeEA.mq5.

WHY A FILE BRIDGE (see ARCHITECTURE.md / MT5_SETUP.md for the full writeup):
MetaTrader 5's official Python integration (the `MetaTrader5` pip package) is
a thin wrapper around a Windows DLL exported by the Windows MT5 terminal --
it does not exist for the native macOS MT5 build. MQL5 running inside native
macOS MT5 also cannot import arbitrary Windows DLLs (no wsock32.dll), so a
raw TCP/socket EA -- the usual Windows bridge trick -- is not reliably
available either. What MQL5 CAN always do, on every MT5 build, is read and
write plain files inside its own sandboxed `MQL5/Files/` directory. This
project therefore uses that folder as a simple, dependency-free, polling
message bus between the EA (inside MT5) and this Python engine (outside
MT5). No Wine, no VPS, no Windows, no DLLs.

(MQL5 also supports a separate, cross-terminal-shared "Common/Files"
folder via the FILE_COMMON flag -- an earlier version of this bridge used
that instead. It was dropped: this only ever needs to work for the one
terminal the user is actually trading through, and MT5's exact on-disk path
to the Common folder varies by install in a way its own terminal-local
MQL5/Files/ folder does not, so the terminal-local folder is both simpler
and more reliably locatable -- see engine/mt5_paths.py.)

Layout, all inside <MT5 terminal's data folder>/MQL5/Files/ForexTradingSystem/:

    heartbeat.json        EA writes {"time": <epoch seconds>} every timer tick
    account.json           EA writes AccountInfo fields every timer tick
    symbols/<SYMBOL>.json  EA writes SymbolSpec + latest Quote every timer tick,
                            for every symbol the Python config lists
    bars/<SYMBOL>_M5.csv   EA exports the last N closed M5 bars, appended as
                            new bars close (time,open,high,low,close,volume)
    positions.json         EA writes the current open-position list every tick
    commands/<id>.json     Python writes a command file to request an action
    responses/<id>.json    EA writes the matching result; Python polls for it
                            and deletes both files once consumed

Command types (Python -> EA):
    {"type": "ORDER", "id": ..., "symbol", "direction", "volume", "sl", "tp", "comment"}
    {"type": "CLOSE", "id": ..., "ticket"}
    {"type": "CLOSE_ALL", "id": ...}

Response shape (EA -> Python):
    {"id": ..., "status": "FILLED"|"REJECTED"|"ERROR", "ticket", "filled_price", "message"}

The EA is the single source of truth for account/position state; Python
never assumes state survives a restart (Requirement 22) -- every read hits
the files fresh.
"""
from __future__ import annotations

BRIDGE_DIRNAME = "ForexTradingSystem"
HEARTBEAT_FILE = "heartbeat.json"
ACCOUNT_FILE = "account.json"
POSITIONS_FILE = "positions.json"
SYMBOLS_SUBDIR = "symbols"
BARS_SUBDIR = "bars"
COMMANDS_SUBDIR = "commands"
RESPONSES_SUBDIR = "responses"

HEARTBEAT_STALE_SECONDS = 15.0
