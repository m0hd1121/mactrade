"""Local management UI backend.

A local-only FastAPI server (bound to 127.0.0.1, no external exposure) that
serves the dashboard and drives the trading orchestrator in the background.
Run directly with `python -m ui.server` or via scripts/run_paper.py /
run_live.py; the packaged macOS app launches this same module inside a
pywebview window (see installer/).
"""
from __future__ import annotations

import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from engine.backtest.backtester import Backtester, BacktestConfig
from engine.backtest.data_loader import generate_synthetic_bars, load_csv_bars
from engine.backtest.monte_carlo import run_monte_carlo
from engine.backtest.small_account_sweep import DEFAULT_BALANCE_LADDER, run_small_account_sweep
from engine.backtest.walk_forward import run_walk_forward
from engine.bridge.base import BridgeConnectionError
from engine.bridge.file_bridge import FileBridge, default_mt5_files_dir
from engine.bridge.mock_bridge import MockBridge
from engine.config import AppConfig, app_data_dir
from engine.db.database import Database
from engine.env_inspect import inspect_environment
from engine.logging_config import configure_logging, get_logger
from engine.market_structure.sessions import classify_session
from engine.orchestrator.live_orchestrator import TradingOrchestrator
from engine.orchestrator.safety import SafetyController
from engine.risk.symbol_spec import account_viability

logger = get_logger("ui")


class AppState:
    def __init__(self):
        self.data_dir = app_data_dir()
        configure_logging(self.data_dir / "logs")
        self.config_path = self.data_dir / "config.json"
        self.config = AppConfig.load(self.config_path)
        self.db = Database(self.data_dir / "trading.db")
        self.safety = SafetyController(self.data_dir / "safety_state.json")
        self.bridge = self._build_bridge()
        self.orchestrator = TradingOrchestrator(self.config, self.bridge, self.db, self.safety)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def _build_bridge(self):
        if self.config.bridge.kind == "mt5_file":
            files_dir = Path(self.config.bridge.files_dir) if self.config.bridge.files_dir else (default_mt5_files_dir() / "ForexTradingSystem")
            return FileBridge(files_dir, poll_interval=self.config.bridge.poll_interval_seconds, command_timeout=self.config.bridge.command_timeout_seconds)
        return MockBridge(starting_balance=500.0)

    def rebuild_bridge_and_orchestrator(self):
        self.bridge = self._build_bridge()
        self.orchestrator = TradingOrchestrator(self.config, self.bridge, self.db, self.safety)

    def start_background_loop(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()

        def loop():
            try:
                self.orchestrator.initialize()
            except Exception as e:
                logger.error("Orchestrator init failed: %s", e)
                self.db.log_error("orchestrator", f"Initialization failed: {e}")
            while not self._stop.is_set():
                if self.config.mode in ("PAPER", "LIVE"):
                    try:
                        self.orchestrator.tick()
                    except Exception as e:
                        logger.exception("Tick failed")
                        self.db.log_error("orchestrator", f"Tick failed: {e}")
                self._stop.wait(5.0)

        self._thread = threading.Thread(target=loop, daemon=True)
        self._thread.start()

    def save_config(self):
        self.config.save(self.config_path)


state = AppState()
app = FastAPI(title="Forex Trading System")


@app.on_event("startup")
def _startup():
    state.start_background_loop()


# ---------------------------------------------------------------------- status / dashboard
@app.get("/api/status")
def api_status():
    connected = False
    broker = None
    try:
        connected = state.bridge.is_connected()
        broker = state.bridge.broker_name()
    except Exception:
        pass
    return {
        "mode": state.config.mode,
        "running": state.safety.state.running,
        "kill_switch_active": state.safety.state.kill_switch_active,
        "kill_switch_reason": state.safety.state.kill_switch_reason,
        "bridge_connected": connected,
        "broker": broker,
        "bridge_kind": state.config.bridge.kind,
    }


@app.get("/api/dashboard")
def api_dashboard():
    try:
        account = state.bridge.get_account_info()
    except Exception as e:
        raise HTTPException(503, f"Could not read account info: {e}")

    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = day_start - timedelta(days=day_start.weekday())
    daily_pnl = state.db.realized_pnl_since(state.config.mode, day_start)
    weekly_pnl = state.db.realized_pnl_since(state.config.mode, week_start)
    open_trades = state.db.get_open_trades(mode=state.config.mode)
    floating = sum(t.get("profit") or 0 for t in open_trades)

    state.db.snapshot_performance(state.config.mode, account.balance, account.equity, daily_pnl, weekly_pnl, 0.0)

    return {
        "mode": state.config.mode,
        "broker": account.broker, "account_currency": account.account_currency,
        "balance": account.balance, "equity": account.equity,
        "floating_pl": floating, "daily_pl": daily_pnl, "weekly_pl": weekly_pnl,
        "risk_per_trade_pct": state.config.risk.risk_per_trade_pct,
        "open_positions": open_trades,
        "running": state.safety.state.running, "kill_switch_active": state.safety.state.kill_switch_active,
    }


@app.get("/api/market-monitor")
def api_market_monitor():
    rows = []
    for symbol in state.config.symbols:
        try:
            quote = state.bridge.get_quote(symbol)
            spec = state.bridge.get_symbol_spec(symbol)
            spread_points = round(quote.spread / spec.point, 1) if spec.point else None
        except Exception:
            quote = None
            spread_points = None
        structure = state.orchestrator.structures.get(symbol)
        setup = next((s for s in state.db.get_setups() if s["symbol"] == symbol), None)
        rows.append({
            "symbol": symbol,
            "price": quote.mid if quote else None,
            "spread_points": spread_points,
            "structure": structure.trend.value if structure else None,
            "unswept_liquidity_pools": len(structure.unswept_pools()) if structure else None,
            "setup_status": setup["status"] if setup else "WAITING",
            "entry": setup.get("entry") if setup else None,
            "stop_loss": setup.get("stop_loss") if setup else None,
            "take_profit": setup.get("take_profit") if setup else None,
            "reward_risk_ratio": setup.get("reward_risk_ratio") if setup else None,
        })
    return rows


@app.get("/api/setups")
def api_setups():
    return state.db.get_setups()


@app.get("/api/risk")
def api_risk():
    try:
        account = state.bridge.get_account_info()
    except Exception as e:
        raise HTTPException(503, str(e))
    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = day_start - timedelta(days=day_start.weekday())
    return {
        "balance": account.balance, "equity": account.equity,
        "risk_per_trade_pct": state.config.risk.risk_per_trade_pct,
        "max_daily_loss_pct": state.config.risk.max_daily_loss_pct,
        "max_weekly_loss_pct": state.config.risk.max_weekly_loss_pct,
        "daily_pnl": state.db.realized_pnl_since(state.config.mode, day_start),
        "weekly_pnl": state.db.realized_pnl_since(state.config.mode, week_start),
        "trades_today": state.db.trades_today_count(state.config.mode, day_start),
        "max_trades_per_day": state.config.risk.max_trades_per_day,
        "open_exposure_positions": len(state.db.get_open_trades(mode=state.config.mode)),
        "max_concurrent_positions": state.config.risk.max_concurrent_positions,
        "consecutive_losses": state.db.consecutive_losses(state.config.mode),
        "max_consecutive_losses_pause": state.config.risk.max_consecutive_losses_pause,
    }


@app.get("/api/account-viability")
def api_account_viability():
    try:
        account = state.bridge.get_account_info()
    except Exception as e:
        raise HTTPException(503, str(e))
    specs = {}
    typical_stops = {}
    for symbol in state.config.symbols:
        try:
            specs[symbol] = state.bridge.get_symbol_spec(symbol)
            bars = state.bridge.get_bars(symbol, state.config.timeframe, 50)
            ranges = sorted(b.high - b.low for b in bars) if bars else []
            typical_stops[symbol] = ranges[len(ranges) // 2] * 3 if ranges else 0.0  # 3x median bar range as a stop-distance estimate
        except Exception:
            continue
    results = account_viability(account, specs, state.config.risk, typical_stops)
    return [
        {"symbol": r.symbol, "tradable": r.tradable, "reason": r.reason, "minimum_practical_balance": r.minimum_practical_balance}
        for r in results
    ]


@app.get("/api/trades")
def api_trades(mode: Optional[str] = None, symbol: Optional[str] = None, limit: int = 200):
    return state.db.get_trades(mode=mode, symbol=symbol, limit=limit)


@app.get("/api/errors")
def api_errors(limit: int = 100):
    return state.db.get_recent_errors(limit)


@app.get("/api/performance-history")
def api_performance_history(mode: Optional[str] = None, limit: int = 1000):
    return state.db.get_performance_history(mode or state.config.mode, limit)


# ---------------------------------------------------------------------- safety controls
@app.post("/api/safety/start")
def api_safety_start():
    try:
        state.safety.start()
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "state": state.safety.state}


@app.post("/api/safety/pause")
def api_safety_pause():
    state.safety.pause()
    return {"ok": True, "state": state.safety.state}


class KillSwitchRequest(BaseModel):
    reason: str = "Manual kill switch"


@app.post("/api/safety/kill")
def api_safety_kill(req: KillSwitchRequest):
    state.orchestrator.kill_switch(req.reason)
    return {"ok": True, "state": state.safety.state}


@app.post("/api/safety/deactivate-kill-switch")
def api_safety_deactivate_kill():
    state.safety.deactivate_kill_switch()
    return {"ok": True, "state": state.safety.state}


@app.post("/api/safety/close-all")
def api_safety_close_all():
    results = state.orchestrator.close_all(reason="manual close-all")
    return {"ok": True, "results": [r.__dict__ for r in results]}


# ---------------------------------------------------------------------- settings
@app.get("/api/settings")
def api_get_settings():
    return state.config.model_dump()


@app.post("/api/settings")
def api_post_settings(payload: dict):
    try:
        new_config = AppConfig.model_validate({**state.config.model_dump(), **payload})
    except Exception as e:
        raise HTTPException(400, f"Invalid configuration: {e}")
    if new_config.mode == "LIVE" and not new_config.live_trading_confirmed:
        raise HTTPException(400, "Switching to LIVE requires live_trading_confirmed=true (explicit confirmation, Rule 10)")
    state.config = new_config
    state.save_config()
    state.rebuild_bridge_and_orchestrator()
    return state.config.model_dump()


# ---------------------------------------------------------------------- environment / setup wizard
@app.get("/api/environment")
def api_environment():
    report = inspect_environment()
    return report.__dict__


@app.post("/api/test-connection")
def api_test_connection():
    ok = state.bridge.connect()
    if not ok:
        return {"connected": False, "message": "No fresh heartbeat from the MT5 bridge EA yet"}
    try:
        account = state.bridge.get_account_info()
    except Exception as e:
        return {"connected": False, "message": str(e)}
    return {"connected": True, "broker": account.broker, "login": account.login, "currency": account.account_currency, "balance": account.balance}


# ---------------------------------------------------------------------- backtesting
class BacktestRequest(BaseModel):
    symbol: str
    starting_balance: float = 1000.0
    risk_pct: Optional[float] = None
    bar_count: int = 20000
    csv_path: Optional[str] = None
    spread_points: Optional[float] = None
    run_small_account_sweep: bool = False
    run_walk_forward: bool = False
    run_monte_carlo: bool = False


@app.post("/api/backtest")
def api_run_backtest(req: BacktestRequest):
    try:
        spec = state.bridge.get_symbol_spec(req.symbol)
    except Exception:
        from engine.bridge.specs_defaults import default_symbol_spec
        spec = default_symbol_spec(req.symbol)

    if req.csv_path:
        bars = load_csv_bars(Path(req.csv_path))
        data_source = f"csv:{req.csv_path}"
    else:
        bars = generate_synthetic_bars(req.symbol, datetime(2023, 1, 1, tzinfo=timezone.utc), req.bar_count, seed=hash(req.symbol) % 10_000)
        data_source = "SYNTHETIC DEMO DATA (not real market history -- see BACKTESTING.md)"

    risk_cfg = state.config.risk.model_copy(update={"risk_per_trade_pct": req.risk_pct} if req.risk_pct else {})
    cfg = BacktestConfig(
        starting_balance=req.starting_balance, risk_cfg=risk_cfg, strategy_cfg=state.config.strategy,
        session_cfg=state.config.sessions, spread_points=req.spread_points or 10.0,
    )
    bt = Backtester(spec, cfg)
    result = bt.run(bars)

    backtest_id = state.db.save_backtest(
        symbols=[req.symbol], start_date=bars[0].time.isoformat() if bars else "", end_date=bars[-1].time.isoformat() if bars else "",
        starting_balance=req.starting_balance, risk_pct=risk_cfg.risk_per_trade_pct, metrics=result.metrics,
    )

    response = {
        "backtest_id": backtest_id, "data_source": data_source, "metrics": result.metrics,
        "trades": result.trades[-500:], "rejected_sample": result.rejected[:50],
        "equity_curve": [[t.isoformat(), v] for t, v in result.equity_curve[::max(1, len(result.equity_curve) // 1000)]],
    }

    if req.run_small_account_sweep:
        sweep = run_small_account_sweep(spec, bars, cfg)
        response["small_account_sweep"] = [s.__dict__ for s in sweep]

    if req.run_walk_forward:
        wf = run_walk_forward(spec, bars, cfg)
        response["walk_forward"] = [w.__dict__ for w in wf]

    if req.run_monte_carlo:
        profits = [t["profit"] for t in result.trades if t.get("profit") is not None]
        mc = run_monte_carlo(profits, req.starting_balance)
        response["monte_carlo"] = mc.__dict__

    return response


@app.get("/api/backtests")
def api_backtests(limit: int = 50):
    return state.db.get_backtests(limit)


# ---------------------------------------------------------------------- static frontend
STATIC_DIR = Path(__file__).parent / "static"


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def main():
    import uvicorn
    # Defaults to localhost-only -- this dashboard has no login of its own
    # (Start/Pause/Kill Switch/Close All/Settings, including switching to
    # LIVE mode, are all reachable to anyone who can reach the bound
    # address). Override deliberately, e.g. to your Mac's Tailscale IP for
    # private remote/mobile access without exposing it to the public
    # internet or your whole LAN -- see INSTALLATION.md "Remote access".
    host = os.environ.get("FTS_HOST", "127.0.0.1")
    port = int(os.environ.get("FTS_PORT", "8765"))
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
