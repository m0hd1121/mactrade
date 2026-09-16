"""Top-level trade risk gate.

Every trade -- backtest, paper, or live -- passes through
`RiskEngine.evaluate_trade` before an order is ever built. Any single failed
gate rejects the trade; nothing here ever loosens a limit to make a trade
fit (Rule 4, Rule 5, Rule 6, Rule 14).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from engine.config import RiskConfig
from engine.risk.position_sizer import calculate_position_size
from engine.types import AccountInfo, PositionSizeResult, Quote, SymbolSpec, TradePlan


@dataclass
class RiskState:
    """Mutable, per-session risk state. The orchestrator refreshes this from
    the database / broker before every evaluation -- it is never trusted as
    stale local state across a restart (Requirement 22)."""

    daily_realized_pnl: float = 0.0
    weekly_realized_pnl: float = 0.0
    trades_today: int = 0
    open_positions: int = 0
    consecutive_losses: int = 0
    kill_switch_active: bool = False


@dataclass
class RiskDecision:
    approved: bool
    reason: Optional[str] = None
    position_size: Optional[PositionSizeResult] = None
    details: dict = field(default_factory=dict)


class RiskEngine:
    def __init__(self, risk_cfg: RiskConfig):
        self.cfg = risk_cfg

    def check_transaction_cost(self, spec: SymbolSpec, quote: Quote, plan: TradePlan) -> tuple[bool, Optional[str]]:
        spread_points = quote.spread / spec.point if spec.point else 0.0
        if spread_points > self.cfg.max_spread_points:
            return False, f"Spread {spread_points:.1f} points exceeds configured limit {self.cfg.max_spread_points:.1f} points"

        # spread cost as a fraction of the planned risk distance -- large for tight
        # small-account stops, which is exactly when it matters most.
        if plan.risk_price > 0:
            spread_fraction = quote.spread / plan.risk_price
            if spread_fraction > self.cfg.max_spread_fraction_of_risk:
                return False, (
                    f"Spread cost ({spread_fraction * 100:.1f}% of planned risk) exceeds "
                    f"configured limit ({self.cfg.max_spread_fraction_of_risk * 100:.1f}%)"
                )
        return True, None

    def evaluate_trade(
        self, account: AccountInfo, spec: SymbolSpec, quote: Quote, plan: TradePlan, state: RiskState,
    ) -> RiskDecision:
        if state.kill_switch_active:
            return RiskDecision(approved=False, reason="Kill switch is active -- no new trades permitted")

        if plan.reward_risk_ratio < self.cfg.min_reward_risk - 1e-9:
            return RiskDecision(
                approved=False,
                reason=f"Planned R:R {plan.reward_risk_ratio:.2f} is below the minimum required {self.cfg.min_reward_risk:.2f}",
            )

        if state.open_positions >= self.cfg.max_concurrent_positions:
            return RiskDecision(approved=False, reason=f"Maximum concurrent positions ({self.cfg.max_concurrent_positions}) already open")

        if state.trades_today >= self.cfg.max_trades_per_day:
            return RiskDecision(approved=False, reason=f"Maximum trades per day ({self.cfg.max_trades_per_day}) already reached")

        if state.consecutive_losses >= self.cfg.max_consecutive_losses_pause:
            return RiskDecision(
                approved=False,
                reason=f"Paused after {state.consecutive_losses} consecutive losses (limit {self.cfg.max_consecutive_losses_pause})",
            )

        max_daily_loss_amount = account.balance * (self.cfg.max_daily_loss_pct / 100.0)
        if state.daily_realized_pnl <= -max_daily_loss_amount:
            return RiskDecision(approved=False, reason=f"Daily loss limit reached ({self.cfg.max_daily_loss_pct:.2f}% of balance)")

        max_weekly_loss_amount = account.balance * (self.cfg.max_weekly_loss_pct / 100.0)
        if state.weekly_realized_pnl <= -max_weekly_loss_amount:
            return RiskDecision(approved=False, reason=f"Weekly loss limit reached ({self.cfg.max_weekly_loss_pct:.2f}% of balance)")

        cost_ok, cost_reason = self.check_transaction_cost(spec, quote, plan)
        if not cost_ok:
            return RiskDecision(approved=False, reason=cost_reason)

        sizing = calculate_position_size(account, spec, plan, self.cfg)
        if not sizing.approved:
            return RiskDecision(approved=False, reason=sizing.reason, position_size=sizing, details=sizing.details)

        return RiskDecision(approved=True, position_size=sizing, details=sizing.details)
