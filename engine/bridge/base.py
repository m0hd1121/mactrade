"""Broker bridge interface.

Every execution surface (mock/paper simulation, the real MT5 file bridge, a
future alternative) implements this same contract, so the strategy, risk and
orchestration layers never know or care which one is underneath. See
ARCHITECTURE.md for why a file-based bridge is used for MT5 on native macOS
instead of a direct Python<->MT5 API call.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from engine.types import AccountInfo, Bar, OrderRequest, OrderResult, Position, Quote, SymbolSpec


class BridgeConnectionError(RuntimeError):
    pass


class BrokerBridge(ABC):
    @abstractmethod
    def connect(self) -> bool:
        ...

    @abstractmethod
    def is_connected(self) -> bool:
        ...

    @abstractmethod
    def broker_name(self) -> str:
        ...

    @abstractmethod
    def get_account_info(self) -> AccountInfo:
        ...

    @abstractmethod
    def get_symbol_spec(self, symbol: str) -> SymbolSpec:
        ...

    @abstractmethod
    def get_quote(self, symbol: str) -> Quote:
        ...

    @abstractmethod
    def get_bars(self, symbol: str, timeframe: str, count: int) -> list[Bar]:
        ...

    @abstractmethod
    def get_open_positions(self) -> list[Position]:
        ...

    @abstractmethod
    def send_order(self, order: OrderRequest) -> OrderResult:
        ...

    @abstractmethod
    def close_position(self, ticket: str) -> OrderResult:
        ...

    def close_all_positions(self) -> list[OrderResult]:
        return [self.close_position(p.ticket) for p in self.get_open_positions()]
