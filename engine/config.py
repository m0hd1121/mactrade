"""Application configuration.

Loaded from ~/Library/Application Support/ForexTradingSystem/config.json on
macOS (or ./config/config.json when that directory isn't available, e.g. in
this dev/CI environment). Credentials are never stored here -- see keychain.py.
"""
from __future__ import annotations

import json
import os
import platform
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

DEFAULT_SYMBOLS = [
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCHF", "USDCAD", "NZDUSD",
]


def app_data_dir() -> Path:
    """macOS Application Support dir when present, else a local ./var dir.

    Checking for the real macOS path first (rather than branching on
    platform.system()) means the same code works unmodified in this Linux
    dev/test environment and on the user's actual Mac.
    """
    mac_support = Path.home() / "Library" / "Application Support" / "ForexTradingSystem"
    if platform.system() == "Darwin" or mac_support.parent.exists():
        return mac_support
    return Path(os.environ.get("FTS_DATA_DIR", Path.cwd() / "var"))


class RiskConfig(BaseModel):
    risk_per_trade_pct: float = 0.5          # % of equity risked per trade; conservative default
    max_daily_loss_pct: float = 2.0
    max_weekly_loss_pct: float = 5.0
    max_trades_per_day: int = 5
    max_concurrent_positions: int = 2
    max_consecutive_losses_pause: int = 3     # pause new entries after N losses in a row
    max_spread_points: float = 30.0           # reject setup if current spread exceeds this
    max_spread_fraction_of_risk: float = 0.15  # spread cost must be <= this fraction of planned risk
    min_reward_risk: float = 3.0              # Rule 3: hard floor, never configurable below this

    @field_validator("risk_per_trade_pct")
    @classmethod
    def _sane_risk(cls, v: float) -> float:
        if not (0 < v <= 2.0):
            raise ValueError("risk_per_trade_pct must be in (0, 2.0] -- this system will not raise risk automatically")
        return v

    @field_validator("min_reward_risk")
    @classmethod
    def _min_rr_floor(cls, v: float) -> float:
        if v < 3.0:
            raise ValueError("min_reward_risk may not be configured below 3.0 (Rule 3)")
        return v


class SessionConfig(BaseModel):
    trade_asian: bool = False
    trade_london: bool = True
    trade_new_york: bool = True
    # UTC hour boundaries; broker/DST-adjusted at runtime if needed
    asian_start_utc: int = 23
    asian_end_utc: int = 7
    london_start_utc: int = 7
    london_end_utc: int = 16
    new_york_start_utc: int = 12
    new_york_end_utc: int = 21


class NewsConfig(BaseModel):
    enabled: bool = False
    calendar_file: Optional[str] = None   # path to a local high-impact-event CSV; no live fetches
    pre_news_minutes: int = 15
    post_news_minutes: int = 30
    block_new_entries_during_news: bool = True


class StrategyConfig(BaseModel):
    swing_lookback: int = 3                # bars each side to confirm a swing point
    equal_level_tolerance_points: float = 3.0
    displacement_min_atr_multiple: float = 0.0  # unused: no indicators; kept 0, see displacement_body_multiple
    displacement_body_multiple: float = 1.5     # displacement candle body must exceed N x avg body of lookback
    displacement_lookback: int = 20
    session_liquidity_lookback_sessions: int = 3
    max_bars_since_sweep: int = 12          # confirmation must occur within N bars of the sweep
    sl_buffer_points: float = 5.0           # stop placed this many points beyond the sweep extreme
    target_search_pools: int = 10           # how many unswept opposite-side pools to scan for a TP target


class BridgeConfig(BaseModel):
    kind: str = "mock"                     # "mock" | "mt5_file"
    files_dir: Optional[str] = None        # MT5 Common/Files directory for file bridge
    poll_interval_seconds: float = 1.0
    command_timeout_seconds: float = 10.0


class AppConfig(BaseModel):
    mode: str = "PAPER"                    # BACKTEST | PAPER | LIVE -- Rule 10: never auto-LIVE
    symbols: List[str] = Field(default_factory=lambda: list(DEFAULT_SYMBOLS))
    timeframe: str = "M5"
    risk: RiskConfig = Field(default_factory=RiskConfig)
    sessions: SessionConfig = Field(default_factory=SessionConfig)
    news: NewsConfig = Field(default_factory=NewsConfig)
    strategy: StrategyConfig = Field(default_factory=StrategyConfig)
    bridge: BridgeConfig = Field(default_factory=BridgeConfig)
    live_trading_confirmed: bool = False   # must be explicitly set True through the UI confirmation flow

    @field_validator("mode")
    @classmethod
    def _valid_mode(cls, v: str) -> str:
        if v not in ("BACKTEST", "PAPER", "LIVE"):
            raise ValueError("mode must be BACKTEST, PAPER or LIVE")
        return v

    def is_live(self) -> bool:
        return self.mode == "LIVE" and self.live_trading_confirmed

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "AppConfig":
        path = path or (app_data_dir() / "config.json")
        if not path.exists():
            cfg = cls()
            cfg.save(path)
            return cfg
        data = json.loads(path.read_text())
        return cls.model_validate(data)

    def save(self, path: Optional[Path] = None) -> Path:
        path = path or (app_data_dir() / "config.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.model_dump_json(indent=2))
        return path
