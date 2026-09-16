"""Dynamic, broker-spec-aware position sizing.

This module implements Requirement 3/14: the smallest executable position
size is computed from the broker's ACTUAL symbol specification, and if even
the broker's minimum volume would push realized risk above the configured
limit, the trade is rejected outright. Risk is never widened to fit the
broker's minimum lot -- capital preservation over trade frequency (Rule 4,
Rule 5, Rule 6).
"""
from __future__ import annotations

from engine.config import RiskConfig
from engine.types import AccountInfo, PositionSizeResult, SymbolSpec, TradeMode, TradePlan


def _direction_allowed(spec: SymbolSpec, direction: str) -> bool:
    if spec.trade_mode == TradeMode.DISABLED:
        return False
    if spec.trade_mode == TradeMode.CLOSEONLY:
        return False
    if spec.trade_mode == TradeMode.LONGONLY and direction == "SELL":
        return False
    if spec.trade_mode == TradeMode.SHORTONLY and direction == "BUY":
        return False
    return True


def loss_per_lot(spec: SymbolSpec, risk_price_distance: float) -> float:
    """Account-currency loss for a 1.0-lot position moving `risk_price_distance`."""
    if spec.tick_size <= 0:
        return 0.0
    ticks = risk_price_distance / spec.tick_size
    return ticks * spec.tick_value


def calculate_position_size(
    account: AccountInfo, spec: SymbolSpec, plan: TradePlan, risk_cfg: RiskConfig,
) -> PositionSizeResult:
    if not _direction_allowed(spec, plan.direction.value):
        return PositionSizeResult(approved=False, reason=f"{spec.symbol} trading is restricted ({spec.trade_mode.value}) for {plan.direction.value}")

    max_risk_amount = round(account.equity * (risk_cfg.risk_per_trade_pct / 100.0), 2)
    risk_price = plan.risk_price

    if risk_price <= 0:
        return PositionSizeResult(approved=False, reason="Invalid stop-loss distance (zero or negative risk)")

    min_stop_distance = spec.stops_level_points * spec.point
    if min_stop_distance > 0 and risk_price < min_stop_distance:
        return PositionSizeResult(
            approved=False,
            reason=(
                f"Stop-loss distance ({risk_price:.{spec.digits}f}) is narrower than the broker's "
                f"minimum stop level ({min_stop_distance:.{spec.digits}f})"
            ),
        )

    per_lot_loss = loss_per_lot(spec, risk_price)
    if per_lot_loss <= 0:
        return PositionSizeResult(approved=False, reason="Could not compute a valid tick value for this symbol")

    required_minimum_risk = round(spec.volume_min * per_lot_loss, 2)
    details = {
        "account_balance": account.balance,
        "account_equity": account.equity,
        "max_risk_amount": max_risk_amount,
        "required_minimum_risk": required_minimum_risk,
        "broker_min_volume": spec.volume_min,
        "broker_volume_step": spec.volume_step,
        "risk_price_distance": risk_price,
        "loss_per_lot": per_lot_loss,
    }

    if required_minimum_risk > max_risk_amount:
        return PositionSizeResult(
            approved=False,
            reason="Minimum broker volume would exceed maximum allowed account risk.",
            actual_risk_amount=required_minimum_risk,
            actual_risk_pct=(required_minimum_risk / account.equity * 100.0) if account.equity else 0.0,
            details=details,
        )

    ideal_volume = max_risk_amount / per_lot_loss
    volume = spec.normalize_volume(ideal_volume)
    if volume < spec.volume_min:
        volume = spec.volume_min  # floor-to-step underflow guard; already risk-checked above

    actual_risk_amount = round(volume * per_lot_loss, 2)
    actual_risk_pct = (actual_risk_amount / account.equity * 100.0) if account.equity else 0.0
    details["volume"] = volume
    details["actual_risk_amount"] = actual_risk_amount
    details["actual_risk_pct"] = actual_risk_pct

    required_margin = volume * spec.margin_initial_per_lot
    details["required_margin"] = required_margin
    if required_margin > account.margin_free:
        return PositionSizeResult(
            approved=False,
            reason=(
                f"Insufficient free margin: position requires ~{required_margin:.2f} "
                f"{account.account_currency}, only {account.margin_free:.2f} available"
            ),
            volume=volume, actual_risk_amount=actual_risk_amount, actual_risk_pct=actual_risk_pct, details=details,
        )

    if actual_risk_amount > max_risk_amount * 1.02:  # small tolerance for step rounding
        return PositionSizeResult(
            approved=False,
            reason="Rounded position size would exceed configured maximum risk",
            volume=volume, actual_risk_amount=actual_risk_amount, actual_risk_pct=actual_risk_pct, details=details,
        )

    return PositionSizeResult(
        approved=True, volume=volume, actual_risk_amount=actual_risk_amount,
        actual_risk_pct=actual_risk_pct, details=details,
    )
