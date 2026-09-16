"""Reasonable default broker symbol specifications.

These are ONLY used by the mock bridge (for local paper-trading demos before
MT5 is connected) and as a starting point for the account-viability display
in the setup wizard before real specs have been fetched. The moment a real
MT5 connection is available, `FileBridge.get_symbol_spec()` returns the
broker's ACTUAL numbers and those are what risk decisions are based on --
Requirement 3 is explicit that defaults must never be assumed for real
trading decisions.
"""
from __future__ import annotations

from engine.types import SymbolSpec, TradeMode

# (starting price, digits, point, contract_size, tick_size, tick_value_usd, volume_min, volume_step, margin_per_lot_usd)
_DEFAULTS = {
    "EURUSD": (1.0850, 5, 0.00001, 100_000, 0.00001, 1.0, 0.01, 0.01, 1085.0),
    "GBPUSD": (1.2650, 5, 0.00001, 100_000, 0.00001, 1.0, 0.01, 0.01, 1265.0),
    "USDJPY": (149.50, 3, 0.001, 100_000, 0.001, 0.67, 0.01, 0.01, 995.0),
    "AUDUSD": (0.6550, 5, 0.00001, 100_000, 0.00001, 1.0, 0.01, 0.01, 655.0),
    "USDCHF": (0.8850, 5, 0.00001, 100_000, 0.00001, 1.13, 0.01, 0.01, 885.0),
    "USDCAD": (1.3550, 5, 0.00001, 100_000, 0.00001, 0.74, 0.01, 0.01, 1355.0),
    "NZDUSD": (0.6050, 5, 0.00001, 100_000, 0.00001, 1.0, 0.01, 0.01, 605.0),
    "XAUUSD": (2020.00, 2, 0.01, 100, 0.01, 1.0, 0.01, 0.01, 2020.0),
}

_SPREAD_POINTS = {
    "EURUSD": 8, "GBPUSD": 12, "USDJPY": 10, "AUDUSD": 12,
    "USDCHF": 15, "USDCAD": 15, "NZDUSD": 18, "XAUUSD": 250,
}


def default_price(symbol: str) -> float:
    return _DEFAULTS[symbol][0]


def default_spread_points(symbol: str) -> float:
    return _SPREAD_POINTS.get(symbol, 15)


def default_symbol_spec(symbol: str) -> SymbolSpec:
    if symbol not in _DEFAULTS:
        raise KeyError(f"No default spec placeholder for {symbol}; connect MT5 or add one for testing")
    price, digits, point, contract_size, tick_size, tick_value, vol_min, vol_step, margin = _DEFAULTS[symbol]
    return SymbolSpec(
        symbol=symbol, digits=digits, point=point, contract_size=contract_size,
        tick_size=tick_size, tick_value=tick_value, volume_min=vol_min, volume_max=100.0,
        volume_step=vol_step, margin_initial_per_lot=margin, trade_mode=TradeMode.FULL,
        stops_level_points=50 if "JPY" not in symbol and symbol != "XAUUSD" else 30,
        freeze_level_points=0, currency_base=symbol[:3], currency_profit=symbol[3:6] if len(symbol) >= 6 else "USD",
        currency_margin=symbol[:3],
    )
