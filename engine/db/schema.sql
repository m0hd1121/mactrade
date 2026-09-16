-- SQLite schema (Requirement 24). One local file, no server, low overhead.
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS trades (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    mode            TEXT NOT NULL,              -- BACKTEST | PAPER | LIVE
    backtest_id     INTEGER,                    -- NULL unless mode = BACKTEST
    ticket          TEXT,
    symbol          TEXT NOT NULL,
    direction       TEXT NOT NULL,
    volume          REAL NOT NULL,
    entry_price     REAL NOT NULL,
    stop_loss       REAL NOT NULL,
    take_profit     REAL NOT NULL,
    risk_amount     REAL NOT NULL,
    risk_pct        REAL NOT NULL,
    reward_risk_ratio REAL NOT NULL,
    open_time       TEXT NOT NULL,
    close_time      TEXT,
    close_price     REAL,
    profit          REAL,
    status          TEXT NOT NULL DEFAULT 'OPEN', -- OPEN | CLOSED_TP | CLOSED_SL | CLOSED_MANUAL | CLOSED_KILL_SWITCH
    session         TEXT,
    news_window     TEXT,
    comment         TEXT,
    FOREIGN KEY (backtest_id) REFERENCES backtests(id)
);
CREATE INDEX IF NOT EXISTS idx_trades_symbol_time ON trades(symbol, open_time);
CREATE INDEX IF NOT EXISTS idx_trades_mode ON trades(mode);

CREATE TABLE IF NOT EXISTS signals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol          TEXT NOT NULL,
    time            TEXT NOT NULL,
    status          TEXT NOT NULL,              -- READY | WAITING | REJECTED | INVALIDATED
    structure       TEXT,
    entry           REAL,
    stop_loss       REAL,
    take_profit     REAL,
    reward_risk_ratio REAL,
    rejection_reason TEXT,
    details_json    TEXT
);
CREATE INDEX IF NOT EXISTS idx_signals_symbol_time ON signals(symbol, time);

CREATE TABLE IF NOT EXISTS setups (
    symbol          TEXT PRIMARY KEY,           -- latest setup snapshot per symbol (Market Monitor)
    time            TEXT NOT NULL,
    status          TEXT NOT NULL,
    structure       TEXT,
    liquidity       TEXT,
    entry           REAL,
    stop_loss       REAL,
    take_profit     REAL,
    reward_risk_ratio REAL,
    reasoning_json  TEXT
);

CREATE TABLE IF NOT EXISTS market_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol          TEXT NOT NULL,
    time            TEXT NOT NULL,
    event_type      TEXT NOT NULL,              -- SWEEP | BOS_BULLISH | BOS_BEARISH | CHOCH_BULLISH | CHOCH_BEARISH | SESSION_CHANGE
    level           REAL,
    details_json    TEXT
);
CREATE INDEX IF NOT EXISTS idx_market_events_symbol_time ON market_events(symbol, time);

CREATE TABLE IF NOT EXISTS risk_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol          TEXT NOT NULL,
    time            TEXT NOT NULL,
    approved        INTEGER NOT NULL,
    reason          TEXT,
    volume          REAL,
    actual_risk_amount REAL,
    actual_risk_pct REAL,
    details_json    TEXT
);
CREATE INDEX IF NOT EXISTS idx_risk_events_symbol_time ON risk_events(symbol, time);

CREATE TABLE IF NOT EXISTS errors (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    time            TEXT NOT NULL,
    source          TEXT NOT NULL,              -- bridge | strategy | risk | orchestrator | ui
    message         TEXT NOT NULL,
    details_json    TEXT
);

CREATE TABLE IF NOT EXISTS kill_switch_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    time            TEXT NOT NULL,
    action          TEXT NOT NULL,              -- ACTIVATED | DEACTIVATED | CLOSE_ALL
    reason          TEXT
);

CREATE TABLE IF NOT EXISTS backtests (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      TEXT NOT NULL,
    symbols         TEXT NOT NULL,
    start_date      TEXT NOT NULL,
    end_date        TEXT NOT NULL,
    starting_balance REAL NOT NULL,
    risk_pct        REAL NOT NULL,
    total_trades    INTEGER,
    win_rate        REAL,
    profit_factor   REAL,
    expectancy      REAL,
    max_drawdown_pct REAL,
    max_consecutive_losses INTEGER,
    total_return_pct REAL,
    sharpe_ratio    REAL,
    recovery_factor REAL,
    ending_balance  REAL,
    metrics_json    TEXT
);

CREATE TABLE IF NOT EXISTS performance_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    time            TEXT NOT NULL,
    mode            TEXT NOT NULL,
    balance         REAL NOT NULL,
    equity          REAL NOT NULL,
    daily_pnl       REAL,
    weekly_pnl      REAL,
    drawdown_pct    REAL
);
CREATE INDEX IF NOT EXISTS idx_perf_time ON performance_snapshots(time);
