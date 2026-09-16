from engine.db.database import Database


def test_trade_lifecycle_and_pnl_queries(tmp_path):
    db = Database(tmp_path / "test.db")
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)

    trade_id = db.open_trade(
        mode="PAPER", symbol="EURUSD", direction="BUY", volume=0.01, entry_price=1.1000,
        stop_loss=1.0950, take_profit=1.1150, risk_amount=0.5, risk_pct=0.5, reward_risk_ratio=3.0,
        open_time=now - timedelta(hours=1),
    )
    db.close_trade(trade_id, close_price=1.1150, profit=1.5, status="CLOSED_TP", close_time=now)

    trades = db.get_trades(mode="PAPER")
    assert len(trades) == 1
    assert trades[0]["status"] == "CLOSED_TP"

    pnl = db.realized_pnl_since("PAPER", now - timedelta(days=1))
    assert pnl == 1.5
    assert db.consecutive_losses("PAPER") == 0
    db.close()


def test_consecutive_losses_counts_from_most_recent(tmp_path):
    db = Database(tmp_path / "test2.db")
    for profit in [1.0, -1.0, -1.0, -1.0]:
        tid = db.open_trade(mode="PAPER", symbol="EURUSD", direction="BUY", volume=0.01, entry_price=1.1,
                             stop_loss=1.09, take_profit=1.13, risk_amount=0.5, risk_pct=0.5, reward_risk_ratio=3.0)
        db.close_trade(tid, close_price=1.1, profit=profit, status="CLOSED_SL" if profit < 0 else "CLOSED_TP")
    assert db.consecutive_losses("PAPER") == 3
    db.close()


def test_kill_switch_and_error_logging(tmp_path):
    db = Database(tmp_path / "test3.db")
    db.log_kill_switch("ACTIVATED", "manual test")
    db.log_error("test", "something failed", {"detail": 1})
    errors = db.get_recent_errors()
    assert len(errors) == 1
    assert errors[0]["message"] == "something failed"
    db.close()
