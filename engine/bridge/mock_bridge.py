"""In-memory simulated broker.

Used for (a) local development/testing without MT5 installed -- exactly the
situation in this build environment -- and (b) a "no broker connected yet"
fallback so the UI has something to show during first-run setup before MT5
is detected. It is never used for BACKTEST (that uses real historical data
via engine/backtest/data_loader.py) and must never be selectable for LIVE
mode.
"""
from __future__ import annotations

import random
import uuid
from datetime import datetime, timedelta, timezone

from engine.bridge.base import BrokerBridge
from engine.bridge.specs_defaults import default_price, default_spread_points, default_symbol_spec
from engine.types import (
    AccountInfo, Bar, Direction, OrderRequest, OrderResult, OrderResultStatus,
    Position, Quote, SymbolSpec,
)


class MockBridge(BrokerBridge):
    def __init__(self, starting_balance: float = 500.0, seed: int = 7):
        self._rng = random.Random(seed)
        self._connected = False
        self._balance = starting_balance
        self._prices: dict[str, float] = {}
        self._positions: dict[str, Position] = {}
        self._next_ticket = 1000

    # ------------------------------------------------------------------
    def connect(self) -> bool:
        self._connected = True
        return True

    def is_connected(self) -> bool:
        return self._connected

    def broker_name(self) -> str:
        return "Mock Paper Broker (no MT5 connected)"

    # ------------------------------------------------------------------
    def _price(self, symbol: str) -> float:
        if symbol not in self._prices:
            self._prices[symbol] = default_price(symbol)
        spec = default_symbol_spec(symbol)
        drift = self._rng.uniform(-3, 3) * spec.point
        self._prices[symbol] = max(spec.point, self._prices[symbol] + drift)
        return self._prices[symbol]

    def get_account_info(self) -> AccountInfo:
        equity = self._balance + sum(p.profit for p in self._positions.values())
        return AccountInfo(
            login=0, broker=self.broker_name(), account_currency="USD",
            balance=self._balance, equity=equity, margin=0.0, margin_free=equity,
            leverage=500,
        )

    def get_symbol_spec(self, symbol: str) -> SymbolSpec:
        return default_symbol_spec(symbol)

    def get_quote(self, symbol: str) -> Quote:
        spec = default_symbol_spec(symbol)
        mid = self._price(symbol)
        half_spread = default_spread_points(symbol) * spec.point / 2.0
        return Quote(symbol=symbol, time=datetime.now(timezone.utc), bid=mid - half_spread, ask=mid + half_spread)

    def get_bars(self, symbol: str, timeframe: str, count: int) -> list[Bar]:
        spec = default_symbol_spec(symbol)
        now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        price = default_price(symbol)
        bars: list[Bar] = []
        for i in range(count):
            o = price
            drift = self._rng.uniform(-8, 8) * spec.point
            c = max(spec.point, o + drift)
            h = max(o, c) + abs(self._rng.uniform(0, 4)) * spec.point
            l = min(o, c) - abs(self._rng.uniform(0, 4)) * spec.point
            t = now - timedelta(minutes=5 * (count - i))
            bars.append(Bar(time=t, open=o, high=h, low=l, close=c))
            price = c
        self._prices[symbol] = price
        return bars

    def get_open_positions(self) -> list[Position]:
        for pos in self._positions.values():
            quote = self.get_quote(pos.symbol)
            spec = default_symbol_spec(pos.symbol)
            px = quote.bid if pos.direction == Direction.BUY else quote.ask
            ticks = (px - pos.entry_price) / spec.tick_size if pos.direction == Direction.BUY else (pos.entry_price - px) / spec.tick_size
            pos.profit = ticks * spec.tick_value * pos.volume
        return list(self._positions.values())

    def send_order(self, order: OrderRequest) -> OrderResult:
        quote = self.get_quote(order.symbol)
        fill_price = quote.ask if order.direction == Direction.BUY else quote.bid
        ticket = str(self._next_ticket)
        self._next_ticket += 1
        self._positions[ticket] = Position(
            ticket=ticket, symbol=order.symbol, direction=order.direction, volume=order.volume,
            entry_price=fill_price, stop_loss=order.stop_loss, take_profit=order.take_profit,
            open_time=datetime.now(timezone.utc),
        )
        return OrderResult(status=OrderResultStatus.FILLED, order_id=ticket, filled_price=fill_price, message="Paper fill (mock bridge)")

    def close_position(self, ticket: str) -> OrderResult:
        pos = self._positions.pop(ticket, None)
        if pos is None:
            return OrderResult(status=OrderResultStatus.ERROR, message=f"No open paper position with ticket {ticket}")
        quote = self.get_quote(pos.symbol)
        spec = default_symbol_spec(pos.symbol)
        px = quote.bid if pos.direction == Direction.BUY else quote.ask
        ticks = (px - pos.entry_price) / spec.tick_size if pos.direction == Direction.BUY else (pos.entry_price - px) / spec.tick_size
        profit = ticks * spec.tick_value * pos.volume
        self._balance += profit
        return OrderResult(status=OrderResultStatus.FILLED, order_id=ticket, filled_price=px, message=f"Closed, P/L {profit:.2f}")
