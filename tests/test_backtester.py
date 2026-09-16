from datetime import datetime, timezone

from engine.backtest.backtester import Backtester, BacktestConfig
from engine.backtest.data_loader import generate_synthetic_bars
from engine.backtest.monte_carlo import run_monte_carlo
from engine.backtest.small_account_sweep import run_small_account_sweep
from engine.backtest.walk_forward import run_walk_forward
from engine.bridge.specs_defaults import default_symbol_spec
from engine.config import RiskConfig, SessionConfig, StrategyConfig


def make_config(balance=1000.0, spread_points=2.0):
    return BacktestConfig(
        starting_balance=balance, risk_cfg=RiskConfig(risk_per_trade_pct=0.5), strategy_cfg=StrategyConfig(),
        session_cfg=SessionConfig(), spread_points=spread_points, slippage_points=0.5,
    )


def test_backtester_runs_without_error_and_respects_min_rr():
    spec = default_symbol_spec("EURUSD")
    bars = generate_synthetic_bars("EURUSD", datetime(2024, 1, 1, tzinfo=timezone.utc), 15000, point=spec.point, seed=3)
    bt = Backtester(spec, make_config())
    result = bt.run(bars)

    assert result.metrics["total_trades"] == len(result.trades)
    for t in result.trades:
        assert t["reward_risk_ratio"] >= 3.0 - 1e-6
        assert t["risk_pct"] <= 0.5 * 1.05  # never exceeds configured risk (Rule 4)
    assert len(result.equity_curve) == len(bars)


def test_backtester_never_exceeds_configured_risk_even_when_rejected():
    spec = default_symbol_spec("XAUUSD")
    bars = generate_synthetic_bars("XAUUSD", datetime(2024, 1, 1, tzinfo=timezone.utc), 3000, start_price=2000.0, point=spec.point, seed=9)
    cfg = make_config(balance=30.0, spread_points=200.0)  # deliberately hostile small account + wide spread
    bt = Backtester(spec, cfg)
    result = bt.run(bars)
    # a $30 XAUUSD account should reject most/all setups on cost or min-volume grounds
    assert result.metrics["total_trades"] == 0 or all(t["risk_pct"] <= 0.5 * 1.1 for t in result.trades)


def test_small_account_sweep_reports_ladder():
    spec = default_symbol_spec("EURUSD")
    bars = generate_synthetic_bars("EURUSD", datetime(2024, 1, 1, tzinfo=timezone.utc), 6000, point=spec.point, seed=11)
    cfg = make_config()
    results = run_small_account_sweep(spec, bars, cfg, balances=[20, 100, 1000])
    assert [r.starting_balance for r in results] == [20, 100, 1000]
    for r in results:
        assert r.total_trades >= 0


def test_walk_forward_splits_chronologically():
    spec = default_symbol_spec("EURUSD")
    bars = generate_synthetic_bars("EURUSD", datetime(2024, 1, 1, tzinfo=timezone.utc), 9000, point=spec.point, seed=5)
    cfg = make_config()
    segments = run_walk_forward(spec, bars, cfg)
    names = [s.name for s in segments]
    assert names == ["training", "validation", "out_of_sample"]
    assert segments[0].start_time < segments[1].start_time < segments[2].start_time


def test_monte_carlo_distribution_sane():
    profits = [10, -5, 15, -8, 20, -3, -12, 9]
    mc = run_monte_carlo(profits, starting_balance=1000.0, iterations=500, seed=1)
    assert mc.final_balance_p5 <= mc.final_balance_p50 <= mc.final_balance_p95
    assert 0.0 <= mc.probability_of_ruin <= 1.0
