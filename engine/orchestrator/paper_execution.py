"""PAPER-mode execution simulator.

PAPER mode connects to the REAL MT5 bridge for real account state, real
symbol specs and real live quotes -- the only thing it does NOT do is send
`ORDER`/`CLOSE` commands to the actual MT5 terminal. Fills and P/L are
simulated against the real quotes it just read, and every paper trade is
recorded in the same `trades` table as a LIVE trade would be (mode='PAPER'),
so backtests, paper runs and live runs are directly comparable in the UI.

This is the default mode (Rule 10 / Requirement 19) and is the only mode a
brand-new install can run without the explicit LIVE confirmation flow.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from engine.types import Direction, OrderRequest, OrderResult, OrderResultStatus, Quote, SymbolSpec

_ticket_counter = itertools.count(500000)


@dataclass
class PaperPosition:
    ticket: str
    symbol: str
    direction: Direction
    volume: float
    entry_price: float
    stop_loss: float
    take_profit: float
    open_time: datetime
    trade_db_id: int


class PaperExecutionEngine:
    def __init__(self):
        self.positions: dict[str, PaperPosition] = {}

    def fill(self, order: OrderRequest, quote: Quote, trade_db_id: int) -> tuple[OrderResult, PaperPosition]:
        fill_price = quote.ask if order.direction == Direction.BUY else quote.bid
        ticket = str(next(_ticket_counter))
        pos = PaperPosition(
            ticket=ticket, symbol=order.symbol, direction=order.direction, volume=order.volume,
            entry_price=fill_price, stop_loss=order.stop_loss, take_profit=order.take_profit,
            open_time=datetime.now(timezone.utc), trade_db_id=trade_db_id,
        )
        self.positions[ticket] = pos
        result = OrderResult(status=OrderResultStatus.FILLED, order_id=ticket, filled_price=fill_price, message="Paper fill")
        return result, pos

    def check_exit(self, pos: PaperPosition, quote: Quote) -> Optional[tuple[str, float]]:
        """Returns (status, close_price) if the position's SL or TP has been
        touched by the current bid/ask, else None. Uses the side of the quote
        a real stop order would actually execute against."""
        if pos.direction == Direction.BUY:
            if quote.bid <= pos.stop_loss:
                return "CLOSED_SL", pos.stop_loss
            if quote.bid >= pos.take_profit:
                return "CLOSED_TP", pos.take_profit
        else:
            if quote.ask >= pos.stop_loss:
                return "CLOSED_SL", pos.stop_loss
            if quote.ask <= pos.take_profit:
                return "CLOSED_TP", pos.take_profit
        return None

    def profit(self, pos: PaperPosition, spec: SymbolSpec, close_price: float) -> float:
        ticks = (
            (close_price - pos.entry_price) / spec.tick_size if pos.direction == Direction.BUY
            else (pos.entry_price - close_price) / spec.tick_size
        )
        return ticks * spec.tick_value * pos.volume

    def floating_profit(self, pos: PaperPosition, spec: SymbolSpec, quote: Quote) -> float:
        px = quote.bid if pos.direction == Direction.BUY else quote.ask
        return self.profit(pos, spec, px)

    def close(self, ticket: str) -> None:
        self.positions.pop(ticket, None)

    def positions_for(self, symbol: str) -> list[PaperPosition]:
        return [p for p in self.positions.values() if p.symbol == symbol]
