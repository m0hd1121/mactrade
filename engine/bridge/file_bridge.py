"""Real MT5 connection via the file-based bridge protocol (protocol.py).

Talks to mt5_bridge/ForexBridgeEA.mq5 running inside the user's already-
installed, native macOS MetaTrader 5 terminal. No credentials ever pass
through this file or these files on disk: the EA is already logged in
because the user opened their MT5 terminal and logged in normally, exactly
as they always do -- this bridge only reads account/market state the EA
already has and asks it to place orders the same way a human clicking
"New Order" would.
"""
from __future__ import annotations

import csv
import io
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from engine.bridge.base import BridgeConnectionError, BrokerBridge
from engine.bridge.protocol import (
    ACCOUNT_FILE, BARS_SUBDIR, COMMANDS_SUBDIR, HEARTBEAT_FILE, HEARTBEAT_STALE_SECONDS,
    POSITIONS_FILE, RESPONSES_SUBDIR, SYMBOLS_SUBDIR,
)
from engine.logging_config import get_logger
from engine.types import (
    AccountInfo, Bar, Direction, OrderRequest, OrderResult, OrderResultStatus,
    Position, Quote, SymbolSpec, TradeMode,
)

logger = get_logger("bridge.file")


def default_mt5_common_files_dir() -> Path:
    """Best-effort default location of MT5's shared Common\\Files folder on macOS.

    Native MT5 for Mac stores its data under
    ~/Library/Application Support/net.metaquotes.wine.metatrader5/drive_c/...
    (it ships its own lightweight Wine-like runtime bundle solely to host the
    Windows-format terminal, distinct from a user-installed Wine/CrossOver
    setup). The exact broker-specific terminal ID varies, so
    InstalledMT5Detector (see scripts/inspect_environment.py) scans for it;
    this function only returns the conventional root to scan under.
    """
    return Path.home() / "Library" / "Application Support" / "net.metaquotes.wine.metatrader5" / \
        "drive_c" / "users" / "user" / "AppData" / "Roaming" / "MetaQuotes" / "Terminal" / "Common" / "Files"


class FileBridge(BrokerBridge):
    def __init__(self, files_dir: Path, poll_interval: float = 1.0, command_timeout: float = 10.0):
        self.root = Path(files_dir)
        self.poll_interval = poll_interval
        self.command_timeout = command_timeout
        self._broker_name = "MT5 (file bridge)"

    # ------------------------------------------------------------------
    def connect(self) -> bool:
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / COMMANDS_SUBDIR).mkdir(exist_ok=True)
        (self.root / RESPONSES_SUBDIR).mkdir(exist_ok=True)
        if not self.is_connected():
            logger.warning("MT5 bridge directory exists but no fresh heartbeat from the EA yet: %s", self.root)
            return False
        account = self.get_account_info()
        self._broker_name = account.broker
        logger.info("Connected to MT5 via file bridge: broker=%s login=%s", account.broker, account.login)
        return True

    def is_connected(self) -> bool:
        hb_path = self.root / HEARTBEAT_FILE
        if not hb_path.exists():
            return False
        try:
            data = json.loads(hb_path.read_text())
            age = time.time() - float(data["time"])
            return age <= HEARTBEAT_STALE_SECONDS
        except (json.JSONDecodeError, KeyError, OSError, ValueError):
            return False

    def broker_name(self) -> str:
        return self._broker_name

    # ------------------------------------------------------------------
    def _read_json(self, path: Path) -> dict:
        if not path.exists():
            raise BridgeConnectionError(f"Expected bridge file missing: {path} -- is the EA attached and running?")
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError as e:
            raise BridgeConnectionError(f"Bridge file {path} was unreadable/corrupt: {e}")

    def get_account_info(self) -> AccountInfo:
        data = self._read_json(self.root / ACCOUNT_FILE)
        return AccountInfo(
            login=int(data["login"]), broker=data["broker"], account_currency=data["currency"],
            balance=float(data["balance"]), equity=float(data["equity"]), margin=float(data["margin"]),
            margin_free=float(data["margin_free"]), leverage=float(data["leverage"]),
            server_time=datetime.fromtimestamp(float(data.get("server_time", time.time())), tz=timezone.utc),
        )

    def get_symbol_spec(self, symbol: str) -> SymbolSpec:
        data = self._read_json(self.root / SYMBOLS_SUBDIR / f"{symbol}.json")
        return SymbolSpec(
            symbol=symbol, digits=int(data["digits"]), point=float(data["point"]),
            contract_size=float(data["contract_size"]), tick_size=float(data["tick_size"]),
            tick_value=float(data["tick_value"]), volume_min=float(data["volume_min"]),
            volume_max=float(data["volume_max"]), volume_step=float(data["volume_step"]),
            margin_initial_per_lot=float(data["margin_initial_per_lot"]),
            trade_mode=TradeMode(data.get("trade_mode", "FULL")),
            stops_level_points=float(data.get("stops_level_points", 0)),
            freeze_level_points=float(data.get("freeze_level_points", 0)),
            currency_base=data.get("currency_base", symbol[:3]),
            currency_profit=data.get("currency_profit", symbol[3:6] if len(symbol) >= 6 else "USD"),
            currency_margin=data.get("currency_margin", symbol[:3]),
            swap_long=float(data.get("swap_long", 0.0)), swap_short=float(data.get("swap_short", 0.0)),
        )

    def get_quote(self, symbol: str) -> Quote:
        data = self._read_json(self.root / SYMBOLS_SUBDIR / f"{symbol}.json")
        return Quote(symbol=symbol, time=datetime.fromtimestamp(float(data["quote_time"]), tz=timezone.utc),
                     bid=float(data["bid"]), ask=float(data["ask"]))

    def get_bars(self, symbol: str, timeframe: str, count: int) -> list[Bar]:
        path = self.root / BARS_SUBDIR / f"{symbol}_{timeframe}.csv"
        if not path.exists():
            raise BridgeConnectionError(f"No exported bar history for {symbol} {timeframe} yet: {path}")
        rows = list(csv.reader(io.StringIO(path.read_text())))
        bars = []
        for row in rows[-count:]:
            if len(row) < 5:
                continue
            t = datetime.fromtimestamp(float(row[0]), tz=timezone.utc)
            bars.append(Bar(time=t, open=float(row[1]), high=float(row[2]), low=float(row[3]), close=float(row[4]),
                             volume=float(row[5]) if len(row) > 5 else 0.0))
        return bars

    def get_open_positions(self) -> list[Position]:
        path = self.root / POSITIONS_FILE
        if not path.exists():
            return []
        data = self._read_json(path)
        out = []
        for item in data.get("positions", []):
            out.append(Position(
                ticket=str(item["ticket"]), symbol=item["symbol"], direction=Direction(item["direction"]),
                volume=float(item["volume"]), entry_price=float(item["entry_price"]),
                stop_loss=float(item["stop_loss"]), take_profit=float(item["take_profit"]),
                open_time=datetime.fromtimestamp(float(item["open_time"]), tz=timezone.utc),
                profit=float(item.get("profit", 0.0)),
            ))
        return out

    # ------------------------------------------------------------------
    def _send_command(self, payload: dict) -> dict:
        cmd_id = str(uuid.uuid4())
        payload = {"id": cmd_id, **payload}
        cmd_path = self.root / COMMANDS_SUBDIR / f"{cmd_id}.json"
        resp_path = self.root / RESPONSES_SUBDIR / f"{cmd_id}.json"
        cmd_path.write_text(json.dumps(payload))

        deadline = time.time() + self.command_timeout
        while time.time() < deadline:
            if resp_path.exists():
                try:
                    result = json.loads(resp_path.read_text())
                except json.JSONDecodeError:
                    time.sleep(self.poll_interval)
                    continue
                resp_path.unlink(missing_ok=True)
                cmd_path.unlink(missing_ok=True)
                return result
            time.sleep(self.poll_interval)

        cmd_path.unlink(missing_ok=True)
        raise BridgeConnectionError(f"MT5 EA did not respond to command {payload.get('type')} within {self.command_timeout}s")

    def send_order(self, order: OrderRequest) -> OrderResult:
        try:
            result = self._send_command({
                "type": "ORDER", "symbol": order.symbol, "direction": order.direction.value,
                "volume": order.volume, "sl": order.stop_loss, "tp": order.take_profit,
                "comment": order.comment, "client_id": order.client_id,
            })
        except BridgeConnectionError as e:
            return OrderResult(status=OrderResultStatus.ERROR, message=str(e))
        return OrderResult(
            status=OrderResultStatus(result.get("status", "ERROR")),
            order_id=str(result["ticket"]) if result.get("ticket") else None,
            filled_price=float(result["filled_price"]) if result.get("filled_price") else None,
            message=result.get("message", ""),
        )

    def close_position(self, ticket: str) -> OrderResult:
        try:
            result = self._send_command({"type": "CLOSE", "ticket": ticket})
        except BridgeConnectionError as e:
            return OrderResult(status=OrderResultStatus.ERROR, message=str(e))
        return OrderResult(
            status=OrderResultStatus(result.get("status", "ERROR")),
            order_id=str(result.get("ticket")) if result.get("ticket") else ticket,
            filled_price=float(result["filled_price"]) if result.get("filled_price") else None,
            message=result.get("message", ""),
        )

    def close_all_positions(self) -> list[OrderResult]:
        try:
            result = self._send_command({"type": "CLOSE_ALL"})
        except BridgeConnectionError as e:
            return [OrderResult(status=OrderResultStatus.ERROR, message=str(e))]
        results = []
        for item in result.get("results", []):
            results.append(OrderResult(
                status=OrderResultStatus(item.get("status", "ERROR")), order_id=str(item.get("ticket") or ""),
                filled_price=float(item["filled_price"]) if item.get("filled_price") else None,
                message=item.get("message", ""),
            ))
        return results
