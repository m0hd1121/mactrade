from datetime import datetime, timedelta, timezone

from engine.config import SessionConfig, StrategyConfig
from engine.market_structure.structure import MarketStructureEngine
from engine.strategy.liquidity_sweep import LiquiditySweepStrategy
from engine.types import Bar, Direction, SetupStatus


def test_full_pipeline_produces_ready_signal_with_valid_rr():
    cfg = StrategyConfig(swing_lookback=2, displacement_lookback=3, displacement_body_multiple=1.3, max_bars_since_sweep=6, sl_buffer_points=2)
    eng = MarketStructureEngine("EURUSD", point=0.0001, strategy_cfg=cfg, session_cfg=SessionConfig())
    strat = LiquiditySweepStrategy(eng, cfg, min_reward_risk=3.0)

    t0 = datetime(2024, 1, 1, 8, 0, tzinfo=timezone.utc)
    rows = [
        (1.1000, 1.1005, 1.0995, 1.1000),
        (1.1000, 1.1005, 1.0985, 1.0990),
        (1.0990, 1.0995, 1.0950, 1.0960),   # swing low candidate
        (1.0960, 1.0975, 1.0955, 1.0970),
        (1.0970, 1.0990, 1.0965, 1.0985),
        (1.0985, 1.1020, 1.0980, 1.1015),   # swing high candidate
        (1.1015, 1.1018, 1.0995, 1.1000),
        (1.1000, 1.1005, 1.0980, 1.0990),
        (1.0990, 1.0995, 1.0940, 1.0955),   # sweeps the swing low
        (1.0955, 1.1010, 1.0950, 1.1005),   # displacement bullish
        (1.1005, 1.1008, 1.0995, 1.1000),
        (1.1000, 1.1030, 1.0998, 1.1025),   # closes above prior swing high -> confirmation
    ]

    signals = []
    for i, (o, h, l, c) in enumerate(rows):
        eng.update(Bar(time=t0 + timedelta(minutes=5 * i), open=o, high=h, low=l, close=c))
        signals.append(strat.evaluate(i))

    ready = [s for s in signals if s.status == SetupStatus.READY]
    assert len(ready) == 1
    plan = ready[0].plan
    assert plan.direction == Direction.BUY
    assert plan.reward_risk_ratio >= 3.0 - 1e-9
    assert plan.stop_loss < plan.entry < plan.take_profit
    assert len(plan.reasoning) >= 2


def test_no_signal_without_any_sweep():
    cfg = StrategyConfig(swing_lookback=2)
    eng = MarketStructureEngine("EURUSD", point=0.0001, strategy_cfg=cfg, session_cfg=SessionConfig())
    strat = LiquiditySweepStrategy(eng, cfg, min_reward_risk=3.0)

    t0 = datetime(2024, 1, 1, 8, 0, tzinfo=timezone.utc)
    rows = [(1.1000 + i * 0.0001, 1.1002 + i * 0.0001, 1.0998 + i * 0.0001, 1.1001 + i * 0.0001) for i in range(20)]
    for i, (o, h, l, c) in enumerate(rows):
        eng.update(Bar(time=t0 + timedelta(minutes=5 * i), open=o, high=h, low=l, close=c))
        sig = strat.evaluate(i)
        assert sig.status in (SetupStatus.WAITING, SetupStatus.REJECTED)
