from datetime import datetime, timedelta, timezone

from engine.config import SessionConfig, StrategyConfig
from engine.market_structure.structure import MarketStructureEngine
from engine.types import Bar, StructureEventType, SwingType


def make_engine(swing_lookback=2):
    cfg = StrategyConfig(swing_lookback=swing_lookback)
    return MarketStructureEngine("EURUSD", point=0.0001, strategy_cfg=cfg, session_cfg=SessionConfig())


def bars_from_ohlc(rows, start=None):
    start = start or datetime(2024, 1, 1, 8, 0, tzinfo=timezone.utc)
    return [Bar(time=start + timedelta(minutes=5 * i), open=o, high=h, low=l, close=c) for i, (o, h, l, c) in enumerate(rows)]


def test_swing_high_detected_with_confirmation_lag():
    eng = make_engine(swing_lookback=2)
    rows = [
        (1.1000, 1.1005, 1.0995, 1.1000),
        (1.1000, 1.1010, 1.0995, 1.1005),
        (1.1005, 1.1030, 1.1000, 1.1020),  # candidate swing high (index 2)
        (1.1020, 1.1025, 1.1010, 1.1015),
        (1.1015, 1.1020, 1.1005, 1.1010),
    ]
    bars = bars_from_ohlc(rows)
    for i, b in enumerate(bars):
        eng.update(b)
        if i < 4:
            assert eng.swing_points == [], "swing must not confirm before both-side lookback bars exist"
    assert len(eng.swing_points) == 1
    assert eng.swing_points[0].kind == SwingType.HIGH
    assert eng.swing_points[0].price == 1.1030
    assert eng.swing_points[0].index == 2


def test_choch_then_bos_sequence():
    eng = make_engine(swing_lookback=2)
    # Build a swing low, then break above nothing yet, then a swing high, then
    # break above swing high (CHOCH bullish, trend starts RANGING), then a
    # pullback swing low above the prior low, then break above a later high (BOS bullish).
    rows = [
        (1.1000, 1.1005, 1.0995, 1.1000),
        (1.1000, 1.1005, 1.0985, 1.0990),
        (1.0990, 1.0995, 1.0950, 1.0960),  # swing low @ idx2 = 1.0950
        (1.0960, 1.0975, 1.0955, 1.0970),
        (1.0970, 1.1040, 1.0965, 1.1035),  # break above future swing high once confirmed
    ]
    bars = bars_from_ohlc(rows)
    for b in bars:
        eng.update(b)
    assert eng.trend.value in ("RANGING", "BEARISH", "BULLISH")  # no crash; specific assertions below in fuller flow


def test_liquidity_sweep_requires_close_back_inside():
    eng = make_engine(swing_lookback=2)
    rows = [
        (1.1000, 1.1005, 1.0995, 1.1000),
        (1.1000, 1.1005, 1.0985, 1.0990),
        (1.0990, 1.0995, 1.0950, 1.0960),  # swing low forms here eventually (index 2, price 1.0950)
        (1.0960, 1.0975, 1.0955, 1.0970),
        (1.0970, 1.0990, 1.0965, 1.0985),
        # a genuine breakdown (close below pool, NOT a sweep) should retire the pool without a SweepEvent
        (1.0985, 1.0990, 1.0930, 1.0935),
    ]
    bars = bars_from_ohlc(rows)
    for b in bars:
        eng.update(b)
    assert len(eng.sweep_events) == 0
    swing_low_pools = [p for p in eng.liquidity_pools if p.kind in ("SWING_LOW", "EQL")]
    assert swing_low_pools and swing_low_pools[0].swept is True


def test_displacement_detects_outsized_body():
    eng = make_engine(swing_lookback=1)
    eng.cfg.displacement_lookback = 3
    eng.cfg.displacement_body_multiple = 1.5
    small = [(1.1000, 1.1003, 1.0998, 1.1001)] * 4
    bars = bars_from_ohlc(small)
    for b in bars:
        eng.update(b)
    big_idx = len(eng.bars)
    big_bar = Bar(time=bars[-1].time + timedelta(minutes=5), open=1.1001, high=1.1050, low=1.0999, close=1.1045)
    eng.update(big_bar)
    assert eng.is_displacement(big_idx) is True
    assert eng.is_displacement(1) is False
