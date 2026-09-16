"""SQLite persistence layer (Requirement 24).

A thin, typed wrapper -- no ORM, to keep the dependency list and memory
footprint small (Requirement 25). Every write here is also what the UI reads
directly, so the schema doubles as the API between the engine and the
dashboard.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

from engine.risk.risk_engine import RiskDecision
from engine.types import Signal, StructureEvent, SweepEvent, TradePlan

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def _iso(dt: Optional[datetime] = None) -> str:
    return (dt or datetime.now(timezone.utc)).isoformat()


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA_PATH.read_text())
        self._conn.commit()

    @contextmanager
    def cursor(self) -> Iterator[sqlite3.Cursor]:
        cur = self._conn.cursor()
        try:
            yield cur
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        finally:
            cur.close()

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------ signals
    def log_signal(self, signal: Signal) -> int:
        plan = signal.plan
        with self.cursor() as cur:
            cur.execute(
                """INSERT INTO signals (symbol, time, status, structure, entry, stop_loss, take_profit,
                   reward_risk_ratio, rejection_reason, details_json) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    signal.symbol, _iso(signal.time), signal.status.value, signal.structure.value,
                    plan.entry if plan else None, plan.stop_loss if plan else None, plan.take_profit if plan else None,
                    plan.reward_risk_ratio if plan else None, signal.rejection_reason, json.dumps(signal.details, default=str),
                ),
            )
            return cur.lastrowid

    def upsert_setup(self, signal: Signal, liquidity_description: str = "") -> None:
        plan = signal.plan
        with self.cursor() as cur:
            cur.execute(
                """INSERT INTO setups (symbol, time, status, structure, liquidity, entry, stop_loss, take_profit,
                   reward_risk_ratio, reasoning_json) VALUES (?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(symbol) DO UPDATE SET time=excluded.time, status=excluded.status,
                   structure=excluded.structure, liquidity=excluded.liquidity, entry=excluded.entry,
                   stop_loss=excluded.stop_loss, take_profit=excluded.take_profit,
                   reward_risk_ratio=excluded.reward_risk_ratio, reasoning_json=excluded.reasoning_json""",
                (
                    signal.symbol, _iso(signal.time), signal.status.value, signal.structure.value, liquidity_description,
                    plan.entry if plan else None, plan.stop_loss if plan else None, plan.take_profit if plan else None,
                    plan.reward_risk_ratio if plan else None,
                    json.dumps((plan.reasoning if plan else []) + ([signal.rejection_reason] if signal.rejection_reason else [])),
                ),
            )

    def get_setups(self) -> list[dict]:
        with self.cursor() as cur:
            cur.execute("SELECT * FROM setups ORDER BY symbol")
            return [dict(r) for r in cur.fetchall()]

    # ------------------------------------------------------------------ market events
    def log_market_event(self, symbol: str, time: datetime, event_type: str, level: Optional[float] = None, details: Optional[dict] = None) -> None:
        with self.cursor() as cur:
            cur.execute(
                "INSERT INTO market_events (symbol, time, event_type, level, details_json) VALUES (?,?,?,?,?)",
                (symbol, _iso(time), event_type, level, json.dumps(details or {}, default=str)),
            )

    # ------------------------------------------------------------------ risk events
    def log_risk_event(self, symbol: str, decision: RiskDecision) -> None:
        sizing = decision.position_size
        with self.cursor() as cur:
            cur.execute(
                """INSERT INTO risk_events (symbol, time, approved, reason, volume, actual_risk_amount,
                   actual_risk_pct, details_json) VALUES (?,?,?,?,?,?,?,?)""",
                (
                    symbol, _iso(), int(decision.approved), decision.reason,
                    sizing.volume if sizing else None, sizing.actual_risk_amount if sizing else None,
                    sizing.actual_risk_pct if sizing else None, json.dumps(decision.details, default=str),
                ),
            )

    # ------------------------------------------------------------------ errors
    def log_error(self, source: str, message: str, details: Optional[dict] = None) -> None:
        with self.cursor() as cur:
            cur.execute(
                "INSERT INTO errors (time, source, message, details_json) VALUES (?,?,?,?)",
                (_iso(), source, message, json.dumps(details or {}, default=str)),
            )

    def get_recent_errors(self, limit: int = 100) -> list[dict]:
        with self.cursor() as cur:
            cur.execute("SELECT * FROM errors ORDER BY id DESC LIMIT ?", (limit,))
            return [dict(r) for r in cur.fetchall()]

    # ------------------------------------------------------------------ kill switch
    def log_kill_switch(self, action: str, reason: str = "") -> None:
        with self.cursor() as cur:
            cur.execute("INSERT INTO kill_switch_events (time, action, reason) VALUES (?,?,?)", (_iso(), action, reason))

    # ------------------------------------------------------------------ trades
    def open_trade(
        self, mode: str, symbol: str, direction: str, volume: float, entry_price: float,
        stop_loss: float, take_profit: float, risk_amount: float, risk_pct: float,
        reward_risk_ratio: float, ticket: Optional[str] = None, backtest_id: Optional[int] = None,
        session: Optional[str] = None, news_window: Optional[str] = None, comment: str = "",
        open_time: Optional[datetime] = None,
    ) -> int:
        with self.cursor() as cur:
            cur.execute(
                """INSERT INTO trades (mode, backtest_id, ticket, symbol, direction, volume, entry_price,
                   stop_loss, take_profit, risk_amount, risk_pct, reward_risk_ratio, open_time, status,
                   session, news_window, comment)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?, 'OPEN', ?,?,?)""",
                (
                    mode, backtest_id, ticket, symbol, direction, volume, entry_price, stop_loss, take_profit,
                    risk_amount, risk_pct, reward_risk_ratio, _iso(open_time), session, news_window, comment,
                ),
            )
            return cur.lastrowid

    def close_trade(self, trade_id: int, close_price: float, profit: float, status: str, close_time: Optional[datetime] = None) -> None:
        with self.cursor() as cur:
            cur.execute(
                "UPDATE trades SET close_price=?, profit=?, status=?, close_time=? WHERE id=?",
                (close_price, profit, status, _iso(close_time), trade_id),
            )

    def get_open_trades(self, mode: Optional[str] = None) -> list[dict]:
        with self.cursor() as cur:
            if mode:
                cur.execute("SELECT * FROM trades WHERE status='OPEN' AND mode=?", (mode,))
            else:
                cur.execute("SELECT * FROM trades WHERE status='OPEN'")
            return [dict(r) for r in cur.fetchall()]

    def get_trades(self, mode: Optional[str] = None, symbol: Optional[str] = None, limit: int = 500) -> list[dict]:
        query = "SELECT * FROM trades WHERE 1=1"
        params: list[Any] = []
        if mode:
            query += " AND mode=?"
            params.append(mode)
        if symbol:
            query += " AND symbol=?"
            params.append(symbol)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self.cursor() as cur:
            cur.execute(query, params)
            return [dict(r) for r in cur.fetchall()]

    def trades_today_count(self, mode: str, since: datetime) -> int:
        with self.cursor() as cur:
            cur.execute("SELECT COUNT(*) c FROM trades WHERE mode=? AND open_time >= ?", (mode, _iso(since)))
            return cur.fetchone()["c"]

    def realized_pnl_since(self, mode: str, since: datetime) -> float:
        with self.cursor() as cur:
            cur.execute(
                "SELECT COALESCE(SUM(profit),0) p FROM trades WHERE mode=? AND status!='OPEN' AND close_time >= ?",
                (mode, _iso(since)),
            )
            return cur.fetchone()["p"]

    def consecutive_losses(self, mode: str) -> int:
        with self.cursor() as cur:
            cur.execute("SELECT profit FROM trades WHERE mode=? AND status!='OPEN' ORDER BY id DESC LIMIT 50", (mode,))
            rows = cur.fetchall()
        count = 0
        for r in rows:
            if r["profit"] is not None and r["profit"] < 0:
                count += 1
            else:
                break
        return count

    # ------------------------------------------------------------------ backtests
    def save_backtest(self, symbols: list[str], start_date: str, end_date: str, starting_balance: float, risk_pct: float, metrics: dict) -> int:
        with self.cursor() as cur:
            cur.execute(
                """INSERT INTO backtests (created_at, symbols, start_date, end_date, starting_balance, risk_pct,
                   total_trades, win_rate, profit_factor, expectancy, max_drawdown_pct, max_consecutive_losses,
                   total_return_pct, sharpe_ratio, recovery_factor, ending_balance, metrics_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    _iso(), ",".join(symbols), start_date, end_date, starting_balance, risk_pct,
                    metrics.get("total_trades"), metrics.get("win_rate"), metrics.get("profit_factor"),
                    metrics.get("expectancy"), metrics.get("max_drawdown_pct"), metrics.get("max_consecutive_losses"),
                    metrics.get("total_return_pct"), metrics.get("sharpe_ratio"), metrics.get("recovery_factor"),
                    metrics.get("ending_balance"), json.dumps(metrics, default=str),
                ),
            )
            return cur.lastrowid

    def get_backtests(self, limit: int = 50) -> list[dict]:
        with self.cursor() as cur:
            cur.execute("SELECT * FROM backtests ORDER BY id DESC LIMIT ?", (limit,))
            return [dict(r) for r in cur.fetchall()]

    # ------------------------------------------------------------------ performance snapshots
    def snapshot_performance(self, mode: str, balance: float, equity: float, daily_pnl: float, weekly_pnl: float, drawdown_pct: float) -> None:
        with self.cursor() as cur:
            cur.execute(
                "INSERT INTO performance_snapshots (time, mode, balance, equity, daily_pnl, weekly_pnl, drawdown_pct) VALUES (?,?,?,?,?,?,?)",
                (_iso(), mode, balance, equity, daily_pnl, weekly_pnl, drawdown_pct),
            )

    def get_performance_history(self, mode: str, limit: int = 1000) -> list[dict]:
        with self.cursor() as cur:
            cur.execute("SELECT * FROM performance_snapshots WHERE mode=? ORDER BY id DESC LIMIT ?", (mode, limit))
            return [dict(r) for r in cur.fetchall()][::-1]
