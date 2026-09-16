"""Account viability analysis (Requirement 6): for each symbol, is the
current account actually able to trade it under the configured risk limits,
and what is the estimated minimum practical account size.

`typical_stop_price` is a plain statistic derived directly from recent OHLC
data (e.g. the median M5 high-low range over the last N bars) -- it is NOT a
smoothed technical indicator, just a raw price-geometry estimate used to give
the user a realistic number before any signal has actually formed.
"""
from __future__ import annotations

from engine.config import RiskConfig
from engine.risk.position_sizer import loss_per_lot
from engine.types import AccountInfo, SymbolSpec, SymbolViability


def minimum_practical_balance(spec: SymbolSpec, risk_cfg: RiskConfig, typical_stop_price: float) -> float | None:
    if typical_stop_price <= 0:
        return None
    per_lot_loss = loss_per_lot(spec, typical_stop_price)
    if per_lot_loss <= 0:
        return None
    required_risk = spec.volume_min * per_lot_loss
    return round(required_risk / (risk_cfg.risk_per_trade_pct / 100.0), 2)


def check_symbol_viability(
    account: AccountInfo, spec: SymbolSpec, risk_cfg: RiskConfig, typical_stop_price: float,
) -> SymbolViability:
    min_balance = minimum_practical_balance(spec, risk_cfg, typical_stop_price)
    if min_balance is None:
        return SymbolViability(symbol=spec.symbol, tradable=False, reason="Unable to derive symbol cost model", minimum_practical_balance=None)

    max_risk_amount = account.equity * (risk_cfg.risk_per_trade_pct / 100.0)
    per_lot_loss = loss_per_lot(spec, typical_stop_price)
    required_minimum_risk = spec.volume_min * per_lot_loss

    if required_minimum_risk > max_risk_amount:
        return SymbolViability(
            symbol=spec.symbol, tradable=False,
            reason="Minimum executable volume would violate configured risk parameters",
            minimum_practical_balance=min_balance,
        )

    required_margin = spec.volume_min * spec.margin_initial_per_lot
    if required_margin > account.margin_free:
        return SymbolViability(
            symbol=spec.symbol, tradable=False,
            reason="Insufficient free margin for the broker's minimum position size",
            minimum_practical_balance=min_balance,
        )

    return SymbolViability(symbol=spec.symbol, tradable=True, reason=None, minimum_practical_balance=min_balance)


def account_viability(
    account: AccountInfo,
    specs: dict[str, SymbolSpec],
    risk_cfg: RiskConfig,
    typical_stop_prices: dict[str, float],
) -> list[SymbolViability]:
    results = []
    for symbol, spec in specs.items():
        stop = typical_stop_prices.get(symbol)
        if not stop:
            results.append(SymbolViability(symbol=symbol, tradable=False, reason="No recent price data available", minimum_practical_balance=None))
            continue
        results.append(check_symbol_viability(account, spec, risk_cfg, stop))
    return results
