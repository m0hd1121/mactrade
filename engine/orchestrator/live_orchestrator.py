"""Ties bridge + market structure + strategy + risk engine + database
together for PAPER and LIVE trading (BACKTEST uses engine/backtest instead).

State-sync rule (Requirement 22): every tick rebuilds RiskState from the
database and the bridge's OWN reported positions -- nothing about
today's trade count, today's P/L, or open positions is ever assumed to
carry over correctly from memory. A restart, crash, MT5 reconnect, or Mac
sleep/wake all land in exactly the same safe path: re-read reality, then
proceed.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from engine.bridge.base import BridgeConnectionError, BrokerBridge
from engine.config import AppConfig
from engine.db.database import Database
from engine.logging_config import get_logger
from engine.market_structure.sessions import classify_session
from engine.market_structure.structure import MarketStructureEngine
from engine.orchestrator.paper_execution import PaperExecutionEngine
from engine.orchestrator.safety import SafetyController
from engine.risk.risk_engine import RiskEngine, RiskState
from engine.strategy.liquidity_sweep import LiquiditySweepStrategy
from engine.types import (
    Bar, Direction, OrderRequest, OrderResult, OrderResultStatus, SetupStatus, SymbolSpec,
)

logger = get_logger("orchestrator")

WARMUP_BARS = 500


class TradingOrchestrator:
    def __init__(self, config: AppConfig, bridge: BrokerBridge, db: Database, safety: SafetyController):
        self.config = config
        self.bridge = bridge
        self.db = db
        self.safety = safety
        self.risk_engine = RiskEngine(config.risk)

        self.structures: dict[str, MarketStructureEngine] = {}
        self.strategies: dict[str, LiquiditySweepStrategy] = {}
        self.specs: dict[str, SymbolSpec] = {}
        self.last_bar_time: dict[str, datetime] = {}
        self.paper = PaperExecutionEngine()
        self.initialized = False

    # ------------------------------------------------------------------
    def initialize(self) -> None:
        if not self.bridge.connect():
            raise BridgeConnectionError("Could not connect to broker bridge -- verify MT5 is running and the EA is attached")

        self._resync_open_positions()

        for symbol in self.config.symbols:
            try:
                spec = self.bridge.get_symbol_spec(symbol)
            except BridgeConnectionError as e:
                logger.warning("Skipping %s: %s", symbol, e)
                self.db.log_error("orchestrator", f"Could not load symbol spec for {symbol}: {e}")
                continue
            self.specs[symbol] = spec

            structure = MarketStructureEngine(symbol, spec.point, self.config.strategy, self.config.sessions)
            try:
                warmup = self.bridge.get_bars(symbol, self.config.timeframe, WARMUP_BARS)
            except BridgeConnectionError:
                warmup = []
            for bar in warmup:
                structure.update(bar)
            self.structures[symbol] = structure
            self.strategies[symbol] = LiquiditySweepStrategy(structure, self.config.strategy, self.config.risk.min_reward_risk)
            self.last_bar_time[symbol] = warmup[-1].time if warmup else None

        self.initialized = True
        logger.info("Orchestrator initialized in %s mode for symbols: %s", self.config.mode, ", ".join(self.specs))

    def _resync_open_positions(self) -> None:
        """Reconcile DB 'OPEN' trades against what the broker actually reports.
        A trade marked OPEN in the DB that the broker no longer shows (closed
        manually, by SL/TP, or during downtime) is corrected here rather than
        trusted (Requirement 22)."""
        if self.config.mode != "LIVE":
            return  # PAPER positions are entirely local/simulated; nothing to reconcile against a broker
        live_tickets = {p.ticket for p in self.bridge.get_open_positions()}
        for trade in self.db.get_open_trades(mode="LIVE"):
            if trade["ticket"] not in live_tickets:
                logger.warning("Trade %s (ticket %s) no longer open at broker; reconciling as closed (unknown exit)", trade["id"], trade["ticket"])
                self.db.close_trade(trade["id"], close_price=trade["entry_price"], profit=0.0, status="CLOSED_MANUAL")

    # ------------------------------------------------------------------
    def tick(self) -> None:
        if not self.initialized:
            self.initialize()

        for symbol in list(self.specs):
            try:
                self._process_symbol(symbol)
            except BridgeConnectionError as e:
                logger.error("Bridge error processing %s: %s", symbol, e)
                self.db.log_error("bridge", str(e), {"symbol": symbol})

    def _process_symbol(self, symbol: str) -> None:
        structure = self.structures[symbol]
        strategy = self.strategies[symbol]

        for bar in self._fetch_new_bars(symbol):
            structure.update(bar)
            idx = len(structure.bars) - 1

            if structure.sweep_events and structure.sweep_events[-1].index == idx:
                self.db.log_market_event(symbol, bar.time, "SWEEP", structure.sweep_events[-1].sweep_price)
            for ev in structure.structure_events:
                if ev.index == idx:
                    self.db.log_market_event(symbol, bar.time, ev.event_type.value, ev.level)

            signal = strategy.evaluate(idx)
            self.db.log_signal(signal)
            self.db.upsert_setup(signal, liquidity_description=f"{len(structure.unswept_pools())} unswept pools")

            if signal.status == SetupStatus.READY and self.safety.state.running and not self.safety.state.kill_switch_active:
                self._attempt_trade(symbol, signal)

        self._manage_paper_positions(symbol)

    def _fetch_new_bars(self, symbol: str) -> list[Bar]:
        bars = self.bridge.get_bars(symbol, self.config.timeframe, 5)
        last = self.last_bar_time.get(symbol)
        new_bars = [b for b in bars if last is None or b.time > last]
        if new_bars:
            self.last_bar_time[symbol] = new_bars[-1].time
        return new_bars

    # ------------------------------------------------------------------
    def _build_risk_state(self, symbol: str) -> RiskState:
        now = datetime.now(timezone.utc)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = day_start - timedelta(days=day_start.weekday())

        if self.config.mode == "LIVE":
            open_positions = len(self.bridge.get_open_positions())
        else:
            open_positions = len(self.paper.positions)

        return RiskState(
            daily_realized_pnl=self.db.realized_pnl_since(self.config.mode, day_start),
            weekly_realized_pnl=self.db.realized_pnl_since(self.config.mode, week_start),
            trades_today=self.db.trades_today_count(self.config.mode, day_start),
            open_positions=open_positions,
            consecutive_losses=self.db.consecutive_losses(self.config.mode),
            kill_switch_active=self.safety.state.kill_switch_active,
        )

    def _attempt_trade(self, symbol: str, signal) -> None:
        spec = self.specs[symbol]
        account = self.bridge.get_account_info()
        quote = self.bridge.get_quote(symbol)
        state = self._build_risk_state(symbol)

        decision = self.risk_engine.evaluate_trade(account, spec, quote, signal.plan, state)
        self.db.log_risk_event(symbol, decision)

        if not decision.approved:
            logger.info("Trade rejected for %s: %s", symbol, decision.reason)
            return

        sizing = decision.position_size
        plan = signal.plan
        order = OrderRequest(
            symbol=symbol, direction=plan.direction, volume=sizing.volume, entry=plan.entry,
            stop_loss=plan.stop_loss, take_profit=plan.take_profit, comment="ForexTradingSystem auto",
        )

        session = classify_session(quote.time, self.config.sessions).value
        trade_id = self.db.open_trade(
            mode=self.config.mode, symbol=symbol, direction=order.direction.value, volume=sizing.volume,
            entry_price=plan.entry, stop_loss=plan.stop_loss, take_profit=plan.take_profit,
            risk_amount=sizing.actual_risk_amount, risk_pct=sizing.actual_risk_pct,
            reward_risk_ratio=plan.reward_risk_ratio, session=session, comment=order.comment,
        )

        if self.config.mode == "LIVE":
            if not self.config.is_live():
                logger.error("Refusing LIVE order: live_trading_confirmed is not set (Rule 10)")
                self.db.close_trade(trade_id, close_price=plan.entry, profit=0.0, status="CLOSED_MANUAL")
                return
            result = self.bridge.send_order(order)
            if result.status != OrderResultStatus.FILLED:
                self.db.log_error("orchestrator", f"Live order rejected for {symbol}: {result.message}")
                self.db.close_trade(trade_id, close_price=plan.entry, profit=0.0, status="CLOSED_MANUAL")
                return
            self._attach_ticket(trade_id, result.order_id)
        else:
            result, pos = self.paper.fill(order, quote, trade_id)
            self._attach_ticket(trade_id, result.order_id)

        logger.info("Opened %s %s %.2f lots @ %.5f (trade #%s)", symbol, order.direction.value, sizing.volume, plan.entry, trade_id)

    def _attach_ticket(self, trade_id: int, ticket: str) -> None:
        with self.db.cursor() as cur:
            cur.execute("UPDATE trades SET ticket=? WHERE id=?", (ticket, trade_id))

    # ------------------------------------------------------------------
    def _manage_paper_positions(self, symbol: str) -> None:
        if self.config.mode != "PAPER":
            return
        spec = self.specs.get(symbol)
        if spec is None:
            return
        quote = self.bridge.get_quote(symbol)
        for pos in list(self.paper.positions_for(symbol)):
            exit_info = self.paper.check_exit(pos, quote)
            if exit_info is None:
                continue
            status, close_price = exit_info
            profit = self.paper.profit(pos, spec, close_price)
            self.db.close_trade(pos.trade_db_id, close_price=close_price, profit=profit, status=status)
            self.paper.close(pos.ticket)
            logger.info("Closed paper position %s %s: %s @ %.5f, P/L %.2f", symbol, pos.ticket, status, close_price, profit)

    # ------------------------------------------------------------------
    def close_all(self, reason: str = "manual") -> list[OrderResult]:
        results: list[OrderResult] = []
        if self.config.mode == "LIVE":
            results = self.bridge.close_all_positions()
            for r in results:
                if r.status == OrderResultStatus.FILLED:
                    self._close_db_trade_by_ticket(r.order_id, r.filled_price, "CLOSED_KILL_SWITCH" if "kill" in reason.lower() else "CLOSED_MANUAL")
        else:
            for symbol in list(self.specs):
                quote = self.bridge.get_quote(symbol)
                spec = self.specs[symbol]
                for pos in list(self.paper.positions_for(symbol)):
                    price = quote.bid if pos.direction == Direction.BUY else quote.ask
                    profit = self.paper.profit(pos, spec, price)
                    self.db.close_trade(pos.trade_db_id, close_price=price, profit=profit,
                                         status="CLOSED_KILL_SWITCH" if "kill" in reason.lower() else "CLOSED_MANUAL")
                    self.paper.close(pos.ticket)
                    results.append(OrderResult(status=OrderResultStatus.FILLED, order_id=pos.ticket, filled_price=price, message=reason))
        self.db.log_kill_switch("CLOSE_ALL", reason)
        return results

    def _close_db_trade_by_ticket(self, ticket: str, price: float, status: str) -> None:
        with self.db.cursor() as cur:
            cur.execute("SELECT id, entry_price, symbol, direction, volume FROM trades WHERE ticket=? AND status='OPEN'", (ticket,))
            row = cur.fetchone()
        if row is None:
            return
        spec = self.specs.get(row["symbol"])
        if spec is None or price is None:
            profit = 0.0
        else:
            direction = row["direction"]
            ticks = (price - row["entry_price"]) / spec.tick_size if direction == "BUY" else (row["entry_price"] - price) / spec.tick_size
            profit = ticks * spec.tick_value * row["volume"]
        self.db.close_trade(row["id"], close_price=price or row["entry_price"], profit=profit, status=status)

    def kill_switch(self, reason: str) -> None:
        logger.critical("KILL SWITCH ACTIVATED: %s", reason)
        self.safety.activate_kill_switch(reason)
        self.close_all(reason=f"kill switch: {reason}")
