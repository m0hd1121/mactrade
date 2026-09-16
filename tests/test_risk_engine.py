from datetime import datetime, timezone

from engine.config import RiskConfig
from engine.risk.position_sizer import calculate_position_size
from engine.risk.risk_engine import RiskEngine, RiskState
from engine.risk.symbol_spec import check_symbol_viability
from engine.types import AccountInfo, Direction, Quote, SymbolSpec, TradeMode, TradePlan


def xauusd_spec():
    return SymbolSpec(
        symbol="XAUUSD", digits=2, point=0.01, contract_size=100, tick_size=0.01, tick_value=1.0,
        volume_min=0.01, volume_max=100.0, volume_step=0.01, margin_initial_per_lot=100.0,
        trade_mode=TradeMode.FULL, stops_level_points=50, freeze_level_points=0,
        currency_base="XAU", currency_profit="USD", currency_margin="USD",
    )


def eurusd_spec():
    return SymbolSpec(
        symbol="EURUSD", digits=5, point=0.00001, contract_size=100_000, tick_size=0.00001, tick_value=1.0,
        volume_min=0.01, volume_max=100.0, volume_step=0.01, margin_initial_per_lot=1085.0,
        trade_mode=TradeMode.FULL, stops_level_points=50, freeze_level_points=0,
        currency_base="EUR", currency_profit="USD", currency_margin="EUR",
    )


def test_small_account_rejected_when_min_volume_exceeds_risk():
    """The mandatory Requirement 3 scenario: broker's minimum lot risk exceeds
    the configured maximum risk -> reject outright, never widen risk."""
    account = AccountInfo(login=1, broker="Test", account_currency="USD", balance=50.0, equity=50.0, margin=0.0, margin_free=50.0, leverage=500)
    spec = xauusd_spec()
    plan = TradePlan(symbol="XAUUSD", direction=Direction.BUY, entry=2000.0, stop_loss=1991.3, take_profit=2026.1, invalidation_price=1991.3)
    cfg = RiskConfig(risk_per_trade_pct=0.5)

    result = calculate_position_size(account, spec, plan, cfg)

    assert result.approved is False
    assert "Minimum broker volume would exceed maximum allowed account risk" in result.reason
    assert result.details["max_risk_amount"] == round(50.0 * 0.005, 2)
    assert result.details["required_minimum_risk"] > result.details["max_risk_amount"]


def test_larger_account_same_symbol_is_approved():
    account = AccountInfo(login=1, broker="Test", account_currency="USD", balance=5000.0, equity=5000.0, margin=0.0, margin_free=5000.0, leverage=500)
    spec = xauusd_spec()
    plan = TradePlan(symbol="XAUUSD", direction=Direction.BUY, entry=2000.0, stop_loss=1991.3, take_profit=2026.1, invalidation_price=1991.3)
    cfg = RiskConfig(risk_per_trade_pct=0.5)

    result = calculate_position_size(account, spec, plan, cfg)

    assert result.approved is True
    assert result.volume >= spec.volume_min
    assert result.actual_risk_amount <= account.equity * (cfg.risk_per_trade_pct / 100.0) * 1.02


def test_risk_never_widens_for_small_accounts():
    """Rule 5: risk_per_trade_pct must not silently change with balance."""
    account_small = AccountInfo(login=1, broker="Test", account_currency="USD", balance=25.0, equity=25.0, margin=0.0, margin_free=25.0, leverage=500)
    account_big = AccountInfo(login=1, broker="Test", account_currency="USD", balance=25000.0, equity=25000.0, margin=0.0, margin_free=25000.0, leverage=500)
    spec = eurusd_spec()
    plan = TradePlan(symbol="EURUSD", direction=Direction.BUY, entry=1.1000, stop_loss=1.0950, take_profit=1.1150, invalidation_price=1.0950)
    cfg = RiskConfig(risk_per_trade_pct=0.5)

    small_result = calculate_position_size(account_small, spec, plan, cfg)
    big_result = calculate_position_size(account_big, spec, plan, cfg)

    # whichever is approved, the CONFIGURED risk percentage used is identical
    assert cfg.risk_per_trade_pct == 0.5
    if small_result.approved:
        assert small_result.actual_risk_pct <= 0.5 * 1.05
    if big_result.approved:
        assert big_result.actual_risk_pct <= 0.5 * 1.05


def test_reward_risk_below_minimum_is_rejected_by_risk_engine():
    account = AccountInfo(login=1, broker="Test", account_currency="USD", balance=1000.0, equity=1000.0, margin=0.0, margin_free=1000.0, leverage=500)
    spec = eurusd_spec()
    quote = Quote(symbol="EURUSD", time=datetime.now(timezone.utc), bid=1.09995, ask=1.10005)
    plan = TradePlan(symbol="EURUSD", direction=Direction.BUY, entry=1.1000, stop_loss=1.0990, take_profit=1.1015, invalidation_price=1.0990)  # R:R = 1.5

    engine = RiskEngine(RiskConfig(risk_per_trade_pct=0.5, min_reward_risk=3.0))
    decision = engine.evaluate_trade(account, spec, quote, plan, RiskState())

    assert decision.approved is False
    assert "R:R" in decision.reason


def test_kill_switch_blocks_all_trades():
    account = AccountInfo(login=1, broker="Test", account_currency="USD", balance=1000.0, equity=1000.0, margin=0.0, margin_free=1000.0, leverage=500)
    spec = eurusd_spec()
    quote = Quote(symbol="EURUSD", time=datetime.now(timezone.utc), bid=1.09995, ask=1.10005)
    plan = TradePlan(symbol="EURUSD", direction=Direction.BUY, entry=1.1000, stop_loss=1.0950, take_profit=1.1150, invalidation_price=1.0950)

    engine = RiskEngine(RiskConfig(risk_per_trade_pct=0.5))
    decision = engine.evaluate_trade(account, spec, quote, plan, RiskState(kill_switch_active=True))

    assert decision.approved is False
    assert "Kill switch" in decision.reason


def test_daily_loss_limit_blocks_new_trades():
    account = AccountInfo(login=1, broker="Test", account_currency="USD", balance=1000.0, equity=1000.0, margin=0.0, margin_free=1000.0, leverage=500)
    spec = eurusd_spec()
    quote = Quote(symbol="EURUSD", time=datetime.now(timezone.utc), bid=1.09995, ask=1.10005)
    plan = TradePlan(symbol="EURUSD", direction=Direction.BUY, entry=1.1000, stop_loss=1.0950, take_profit=1.1150, invalidation_price=1.0950)

    cfg = RiskConfig(risk_per_trade_pct=0.5, max_daily_loss_pct=2.0)
    engine = RiskEngine(cfg)
    state = RiskState(daily_realized_pnl=-20.01)  # 2.001% of 1000 balance already lost today

    decision = engine.evaluate_trade(account, spec, quote, plan, state)
    assert decision.approved is False
    assert "Daily loss limit" in decision.reason


def test_account_viability_reports_symbol_not_tradable():
    account = AccountInfo(login=1, broker="Test", account_currency="USD", balance=50.0, equity=50.0, margin=0.0, margin_free=50.0, leverage=500)
    spec = xauusd_spec()
    cfg = RiskConfig(risk_per_trade_pct=0.5)

    viability = check_symbol_viability(account, spec, cfg, typical_stop_price=8.7)  # ~870 points on XAUUSD

    assert viability.tradable is False
    assert viability.minimum_practical_balance is not None
    assert viability.minimum_practical_balance > account.balance
