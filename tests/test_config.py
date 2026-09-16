import pytest
from pydantic import ValidationError

from engine.config import AppConfig, RiskConfig


def test_min_reward_risk_cannot_be_configured_below_3():
    with pytest.raises(ValidationError):
        RiskConfig(min_reward_risk=2.5)


def test_risk_per_trade_pct_has_a_sane_ceiling():
    with pytest.raises(ValidationError):
        RiskConfig(risk_per_trade_pct=5.0)  # Rule 5: never silently allow "just risk more"


def test_default_mode_is_paper_not_live():
    cfg = AppConfig()
    assert cfg.mode == "PAPER"
    assert cfg.is_live() is False


def test_live_requires_explicit_confirmation():
    cfg = AppConfig(mode="LIVE", live_trading_confirmed=False)
    assert cfg.is_live() is False
    cfg2 = AppConfig(mode="LIVE", live_trading_confirmed=True)
    assert cfg2.is_live() is True
