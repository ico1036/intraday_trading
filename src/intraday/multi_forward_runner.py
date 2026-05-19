"""
포트폴리오 Forward Test 러너

Binance kline 스트림(WS) + REST warmup 기반으로 포트폴리오 전략을 paper-trade.
실행 메타·리밸런싱 이벤트·가중치·NAV를 영구 로그로 남깁니다.
"""

import asyncio
import csv
import json
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional, Union

import pandas as pd

from .candle_builder import Candle, CandleType
from .klines_client import (
    BinanceKlineStreamClient,
    BinanceKlinesClient,
    Kline,
    kline_to_candle,
    seconds_to_binance_interval,
)
from .strategies.multi.momentum import PortfolioMomentum
from .strategies.multi.pair import PairTradingStrategy
from .backtest.multi_runner import PortfolioPosition
from .strategy import MarketState, Order, OrderType, PortfolioOrder, Side


class SymbolState:
    """Per-symbol state driven by closed klines."""

    MAX_PRICE_HISTORY = 10_000

    def __init__(self, symbol: str):
        self.symbol = symbol
        self.last_price: float = 0.0
        self.candle_count = 0
        self._price_history: deque = deque(maxlen=self.MAX_PRICE_HISTORY)
        self._price_timestamps: deque = deque(maxlen=self.MAX_PRICE_HISTORY)
        self.last_candle: Optional[Candle] = None

    def on_kline_close(self, candle: Candle) -> Candle:
        self.last_price = candle.close
        self.candle_count += 1
        self.last_candle = candle
        self._price_history.append(candle.close)
        self._price_timestamps.append(candle.timestamp)
        return candle

    def get_price_history(self) -> pd.Series:
        if not self._price_history:
            return pd.Series(dtype=float)
        return pd.Series(list(self._price_history), index=list(self._price_timestamps))


class PortfolioForwardRunner:
    def __init__(
        self,
        strategy: Union[PortfolioMomentum, PairTradingStrategy],
        symbols: list[str],
        candle_type: CandleType = CandleType.TIME,
        candle_size: float = 300.0,
        initial_capital: float = 10_000.0,
        position_size_pct: float = 0.3,
        fee_rate: float = 0.002,
        rebalance_minutes: int = 60,
        status_print_interval: float = 60.0,
        run_id: Optional[str] = None,
        close_on_stop: bool = False,
        auto_save_interval_seconds: Optional[float] = None,
        auto_save_output_dir: Optional[str | Path] = None,
        warmup_bars: int = 0,
    ):
        self.strategy = strategy
        self.symbols = [s.upper() for s in symbols]
        self.candle_type = candle_type
        self.candle_size = candle_size
        self.initial_capital = initial_capital
        self.position_size_pct = position_size_pct
        self.fee_rate = fee_rate
        self.rebalance_minutes = rebalance_minutes
        self.status_print_interval = max(1.0, float(status_print_interval))
        self.run_id = run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        self.close_on_stop = close_on_stop
        self.auto_save_interval_seconds = auto_save_interval_seconds
        self.auto_save_output_dir = (
            Path(auto_save_output_dir) if auto_save_output_dir is not None else None
        )

        self.warmup_bars = max(0, int(warmup_bars))
        if candle_type != CandleType.TIME:
            raise ValueError("kline forward runner only supports CandleType.TIME")
        # Validate up front so wrong candle_size fails fast at construction.
        self._kline_interval = seconds_to_binance_interval(candle_size)

        self.symbol_states: dict[str, SymbolState] = {
            symbol: SymbolState(symbol) for symbol in self.symbols
        }

        self.position = PortfolioPosition()
        self.capital = initial_capital
        self.trade_log: list[dict[str, Any]] = []

        # 운영용 로그 버퍼
        self.rebalance_events: list[dict[str, Any]] = []  # 모델 타겟 + 주문 시그널
        self.execution_events: list[dict[str, Any]] = []  # 실제 체결(모의)
        self.weight_events: list[dict[str, Any]] = []  # 일간 비중 스냅샷
        self.nav_events: list[dict[str, Any]] = []  # NAV 시계열

        self._running = False
        self._clients: dict[str, BinanceKlineStreamClient] = {}
        self._last_rebalance_time: Optional[datetime] = None
        # Populated by ``load_existing_state`` so ``run()`` can pick up
        # the rebalance clock where the prior session left off instead of
        # restarting the interval from now. Without this, --resume kept
        # equity continuous but stalled trading for one full
        # rebalance_minutes window.
        self._resumed_last_rebalance_time: Optional[datetime] = None
        self._start_time: Optional[datetime] = None
        self._auto_save_last_at: Optional[datetime] = None
        self._rebalance_seq = 0
        self._last_daily_weight_date: Optional[str] = None
        # When True, on_kline_close updates SymbolState + advances strategy
        # state via a dry-run generate_order call, but skips order execution
        # — used during REST warmup to seed `_current_date`/`_qv_today`
        # without forging trades at past timestamps.
        self._warming_up = False

    # ----- resume mode -----
    def load_existing_state(self, output_dir: str | Path) -> None:
        """Prepend prior persisted state from ``output_dir/<run_id>/*.parquet``.

        Used when restarting on top of an existing forward dir so the chart
        keeps continuity (no gap between prior run and the new run).
        Falls back silently when the files are missing or empty.
        """
        run_dir = Path(output_dir) / self.run_id
        if not run_dir.is_dir():
            return

        def _load_rows(name: str) -> list[dict[str, Any]]:
            path = run_dir / name
            if not path.exists():
                return []
            try:
                df = pd.read_parquet(path)
            except Exception as exc:  # noqa: BLE001
                print(f"[Resume] failed to read {name}: {exc}")
                return []
            return df.to_dict("records")

        prior_nav = _load_rows("portfolio_nav.parquet") or _load_rows("equity_curve.parquet")
        prior_trades = _load_rows("trades.parquet")
        prior_weights = _load_rows("weights.parquet")
        prior_events = _load_rows("events.parquet")

        self.nav_events = prior_nav + self.nav_events
        self.trade_log = prior_trades + self.trade_log
        self.weight_events = prior_weights + self.weight_events
        # events.parquet stores rebalance + execution mixed; keep them all in
        # rebalance_events for simplicity (save_report writes the union).
        self.rebalance_events = prior_events + self.rebalance_events

        # Restore capital from the last prior NAV entry so subsequent
        # `_record_nav` calls don't reset the equity curve back to
        # `initial_capital` and create a visible jump in the chart.
        if prior_nav:
            last = prior_nav[-1]
            equity = last.get("equity")
            capital = last.get("capital")
            if isinstance(capital, (int, float)) and capital > 0:
                self.capital = float(capital)
            elif isinstance(equity, (int, float)) and equity > 0:
                self.capital = float(equity)

        # Restore the rebalance clock so the should_rebalance() interval
        # doesn't reset to "wait one full window from now" on resume.
        # Picking from weight events is robust: a weight event is written
        # at every successful rebalance.
        latest_rebal: Optional[datetime] = None
        for r in prior_weights:
            ts = r.get("timestamp")
            if ts is None:
                continue
            try:
                dt = ts if isinstance(ts, datetime) else pd.to_datetime(ts).to_pydatetime()
            except Exception:
                continue
            if latest_rebal is None or dt > latest_rebal:
                latest_rebal = dt
        self._resumed_last_rebalance_time = latest_rebal

        print(
            f"[Resume] loaded prior state from {run_dir}: "
            f"nav={len(prior_nav)} trades={len(prior_trades)} "
            f"weights={len(prior_weights)} events={len(prior_events)} "
            f"→ capital=${self.capital:,.2f} "
            f"last_rebalance={latest_rebal}"
        )

    # ----- data ingestion / scheduling -----
    def on_kline_close(self, symbol: str, kline: Kline) -> None:
        """WS callback: a closed kline arrived for ``symbol``."""
        symbol = symbol.upper()
        if symbol not in self.symbol_states:
            return
        candle = kline_to_candle(symbol, kline, self.candle_size)
        self.symbol_states[symbol].on_kline_close(candle)
        if self._warming_up:
            self._advance_strategy_state(symbol, candle, candle.timestamp)
        else:
            self._on_candle_complete(symbol, candle, candle.timestamp)

    def _advance_strategy_state(self, symbol: str, candle: Candle, timestamp: datetime) -> None:
        """During warmup, run the strategy on each candle but discard orders.

        The strategy still updates its internal qv/day accumulators, so by
        the time live klines arrive, ``_current_date`` and ``_qv_today``
        are primed and the first live close fires a real basket.
        """
        panel = self._build_panel()
        if panel is None:
            return
        state = MarketState(
            timestamp=timestamp,
            mid_price=candle.close,
            imbalance=candle.volume_imbalance,
            spread=0.0,
            spread_bps=0.0,
            best_bid=candle.close,
            best_ask=candle.close,
            best_bid_qty=candle.buy_volume,
            best_ask_qty=candle.sell_volume,
            position_side=None,
            position_qty=0.0,
            open=candle.open,
            high=candle.high,
            low=candle.low,
            close=candle.close,
            volume=candle.volume,
            vwap=candle.vwap,
            symbol=symbol,
            panel=panel,
            positions={},
        )
        try:
            self.strategy.generate_order(state)
        except Exception as exc:  # noqa: BLE001
            print(f"[Warmup] strategy.generate_order failed for {symbol}: {exc}")

    def _on_candle_complete(self, symbol: str, candle: Candle, timestamp: datetime) -> None:
        if self.should_rebalance(timestamp):
            self._execute_rebalance(symbol, candle, timestamp)

    def should_rebalance(self, now: datetime) -> bool:
        if self._last_rebalance_time is None:
            return False
        return (now - self._last_rebalance_time).total_seconds() / 60 >= self.rebalance_minutes

    # ----- rebalance / order execution -----
    def _execute_rebalance(self, symbol: str, candle: Candle, timestamp: datetime) -> None:
        prices = self.get_current_prices()
        if len(prices) < len(self.symbols):
            return

        self._last_rebalance_time = timestamp

        rebalance_id = f"{self.run_id}_{self._rebalance_seq:05d}"
        self._rebalance_seq += 1

        if isinstance(self.strategy, PortfolioMomentum):
            self._rebalance_momentum(prices, timestamp)
            return
        if isinstance(self.strategy, PairTradingStrategy):
            self._rebalance_pair(prices, timestamp)
            return

        self._rebalance_portfolio(symbol, candle, timestamp, rebalance_id)

    def _rebalance_momentum(self, prices: dict[str, float], timestamp: datetime) -> None:
        if not self._has_warmed_momentum_state(timestamp):
            return

        price_data = {
            sym: self.symbol_states[sym].get_price_history()
            for sym in self.symbols
            if not self.symbol_states[sym].get_price_history().empty
        }
        if len(price_data) < len(self.symbols):
            return

        rankings = self.strategy.calculate_rankings(price_data)
        signals = self.strategy.generate_signals(rankings, self.position.to_dict())

        for sym, signal in signals.items():
            p = prices.get(sym)
            if p:
                self._execute_signal(sym, signal, p, timestamp)

    def _has_warmed_momentum_state(self, timestamp: datetime) -> bool:
        """모멘텀 전략을 안전하게 시작하기 위한 최소 히스토리 체크."""
        lookback = getattr(self.strategy, "lookback_minutes", 0)
        min_lookback_seconds = max(60, int(lookback) * 60)

        for sym in self.symbols:
            state = self.symbol_states[sym]
            prices = state.get_price_history()
            if len(prices) < 2:
                return False

            # 캔들 생성 자체가 최소 1개는 되어야 함(초기 미완성 상태 방지)
            if state.candle_count < 1:
                return False

            # lookback 기간보다 오래된 히스토리가 쌓여야 함
            first_ts = prices.index[0]
            if timestamp - first_ts < timedelta(seconds=min_lookback_seconds):
                return False

        return True
    def _rebalance_pair(self, prices: dict[str, float], timestamp: datetime) -> None:
        coin_a = self.strategy.coin_a
        coin_b = self.strategy.coin_b

        history_a = self.symbol_states[coin_a].get_price_history()
        history_b = self.symbol_states[coin_b].get_price_history()
        if history_a.empty or history_b.empty:
            return

        zscore = self.strategy.calculate_spread_zscore(history_a, history_b)
        if zscore.empty or pd.isna(zscore.iloc[-1]):
            return

        signal = self.strategy.generate_signal(zscore.iloc[-1], None if not (self.position.has_position(coin_a) and self.position.has_position(coin_b)) else ("LONG_SPREAD" if self.position.get_side(coin_a) == "LONG" else "SHORT_SPREAD"))

        if signal == "LONG_SPREAD":
            self._execute_signal(coin_a, "LONG", prices[coin_a], timestamp)
            self._execute_signal(coin_b, "SHORT", prices[coin_b], timestamp)
        elif signal == "SHORT_SPREAD":
            self._execute_signal(coin_a, "SHORT", prices[coin_a], timestamp)
            self._execute_signal(coin_b, "LONG", prices[coin_b], timestamp)
        elif signal == "EXIT":
            if self.position.has_position(coin_a):
                self._execute_signal(coin_a, "CLOSE", prices[coin_a], timestamp)
            if self.position.has_position(coin_b):
                self._execute_signal(coin_b, "CLOSE", prices[coin_b], timestamp)

    def _rebalance_portfolio(
        self,
        trigger_symbol: str,
        candle: Candle,
        timestamp: datetime,
        rebalance_id: str,
    ) -> None:
        panel = self._build_panel()
        if panel is None:
            return

        current_prices = self.get_current_prices()
        positions = self._build_positions_dict()
        side_str = self.position.get_side(trigger_symbol)

        state = MarketState(
            timestamp=timestamp,
            mid_price=candle.close,
            imbalance=candle.volume_imbalance,
            spread=0.0,
            spread_bps=0.0,
            best_bid=candle.close,
            best_ask=candle.close,
            best_bid_qty=candle.buy_volume,
            best_ask_qty=candle.sell_volume,
            position_side=(Side.BUY if side_str == "LONG" else Side.SELL if side_str == "SHORT" else None),
            position_qty=float(positions.get(trigger_symbol, {}).get("qty", 0.0)) if side_str else 0.0,
            open=candle.open,
            high=candle.high,
            low=candle.low,
            close=candle.close,
            volume=candle.volume,
            vwap=candle.vwap,
            symbol=trigger_symbol,
            panel=panel,
            positions=positions,
        )

        result = self.strategy.generate_order(state)
        if result is None:
            return

        if isinstance(result, PortfolioOrder):
            if not self._validate_weight_sum(result):
                return

            for sym, order in result.items():
                if order is None:
                    continue
                price = current_prices.get(sym, 0.0)
                if price <= 0:
                    continue

                current_qty = self._get_position_qty(sym)
                target_weight = order.weight
                target_qty = 0.0
                target_notional = None
                try:
                    target_qty = self._resolve_qty(sym, order, price)
                    target_notional = target_qty * price
                except ValueError:
                    pass

                self.rebalance_events.append({
                    "run_id": self.run_id,
                    "rebalance_id": rebalance_id,
                    "timestamp": timestamp,
                    "event_type": "model_target",
                    "symbol": sym,
                    "target_side": order.side.value,
                    "target_weight": target_weight,
                    "target_qty": target_qty,
                    "target_notional": target_notional,
                    "position_qty_before": current_qty,
                })
                self.weight_events.append({
                    "timestamp": timestamp,
                    "alpha_id": self.strategy.__class__.__name__,
                    "symbol": sym,
                    "target_weight": (
                        (
                            (float(target_notional) * (1.0 if order.side == Side.BUY else -1.0)) / self.capital
                            if target_notional is not None and self.capital
                            else 0.0
                        ) if target_weight is None
                        else float(target_weight) * (1.0 if order.side == Side.BUY else -1.0)
                    ),
                    "target_notional": (
                        None if target_notional is None
                        else float(target_notional) * (1.0 if order.side == Side.BUY else -1.0)
                    ),
                    "target_qty": (
                        float(target_qty) * (1.0 if order.side == Side.BUY else -1.0)
                    ),
                    "price": price,
                    "bar_type": self.candle_type.value,
                    "bar_size": float(self.candle_size),
                    "metadata": json.dumps(
                        {
                            "run_id": self.run_id,
                            "rebalance_id": rebalance_id,
                            "source": "portfolio_order",
                            "order_side": order.side.value,
                            "order_type": order.order_type.value,
                        },
                        ensure_ascii=False,
                        default=str,
                    ),
                })

                self._execute_portfolio_order(sym, order, price, timestamp)

                # position_qty_after for 추적
                self.rebalance_events.append({
                    "run_id": self.run_id,
                    "rebalance_id": rebalance_id,
                    "timestamp": timestamp,
                    "event_type": "execution",
                    "symbol": sym,
                    "position_qty_after": self._get_position_qty(sym),
                })

        elif isinstance(result, Order):
            sym = trigger_symbol
            price = current_prices.get(sym, 0.0)
            if price <= 0:
                return
            self._execute_portfolio_order(sym, result, price, timestamp)

    def _validate_weight_sum(self, result: PortfolioOrder) -> bool:
        weighted = [o.weight for o in result.active_orders.values() if o is not None and o.weight is not None]
        if not weighted:
            return True
        total = sum(weighted)
        if total <= 0 or total > 1.0 + 1e-12:
            return False
        return all(0 < w <= 1.0 for w in weighted)

    def _build_panel(self) -> Optional[dict[str, dict[str, Any]]]:
        panel: dict[str, dict[str, Any]] = {}
        for sym, st in self.symbol_states.items():
            if st.last_candle is None:
                continue
            c = st.last_candle
            panel[sym] = {
                "timestamp": c.timestamp,
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "volume": c.volume,
                "quote_volume": c.quote_volume,
                "vwap": c.vwap,
                "volume_imbalance": c.volume_imbalance,
                "trade_count": c.trade_count,
                "buy_volume": c.buy_volume,
                "sell_volume": c.sell_volume,
            }
        return panel or None

    def _build_positions_dict(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for sym in self.symbols:
            if self.position.has_position(sym):
                side = self.position.get_side(sym)
                entry = self.position.get_entry_price(sym) or 0.0
                out[sym] = {
                    "side": side,
                    "qty": self._get_position_qty(sym),
                    "entry_price": entry,
                }
        return out

    def _get_position_qty(self, symbol: str) -> float:
        qty = 0.0
        for p in self.position._positions.values():  # type: ignore[attr-defined]
            if p.symbol == symbol:
                qty = p.quantity
                break
        return qty

    def _resolve_qty(self, symbol: str, order: Order, price: float) -> float:
        if order.quantity > 0:
            return order.quantity
        if order.weight is not None:
            if not (0 < order.weight <= 1.0):
                raise ValueError(f"Invalid order weight for {symbol}: {order.weight}")
            position_value = self.capital * self.position_size_pct * order.weight
            return position_value / price if price > 0 else 0.0
        return 0.0

    def _record_exec(self, event: dict[str, Any]) -> None:
        self.execution_events.append(event)

    def _execute_portfolio_order(self, symbol: str, order: Order, price: float, timestamp: datetime) -> None:
        try:
            quantity = self._resolve_qty(symbol, order, price)
        except ValueError as exc:
            print(f"[PortfolioForward] {exc}")
            return

        before_qty = self._get_position_qty(symbol)

        def _append(action: str, pnl: float = 0.0, fee: float = 0.0) -> None:
            self.trade_log.append({
                "timestamp": timestamp,
                "symbol": symbol,
                "action": action,
                "price": price,
                "quantity": quantity,
                "pnl": pnl,
                "fee": fee,
            })
            self._record_exec({
                "run_id": self.run_id,
                "timestamp": timestamp,
                "event_type": "trade",
                "symbol": symbol,
                "order_side": order.side.value,
                "action": action,
                "price": price,
                "qty": quantity,
                "pnl": pnl,
                "fee": fee,
                "qty_before": before_qty,
                "qty_after": self._get_position_qty(symbol),
            })

        if order.side == Side.BUY:
            current_side = self.position.get_side(symbol)
            if current_side == "SHORT":
                pnl = self.position.close(symbol, price, timestamp)
                fee = abs(pnl) * self.fee_rate
                self.capital += pnl - fee
                _append("CLOSE_SHORT", pnl, fee)

            if quantity > 0 and not self.position.has_position(symbol):
                fee = quantity * price * self.fee_rate
                self.position.open(symbol, "LONG", price, quantity, timestamp)
                self._record_exec({
                    "run_id": self.run_id,
                    "timestamp": timestamp,
                    "event_type": "trade",
                    "symbol": symbol,
                    "order_side": order.side.value,
                    "action": "OPEN_LONG",
                    "price": price,
                    "qty": quantity,
                    "pnl": 0.0,
                    "fee": fee,
                    "qty_before": before_qty,
                    "qty_after": self._get_position_qty(symbol),
                })
                self.trade_log.append({
                    "timestamp": timestamp,
                    "symbol": symbol,
                    "action": "OPEN_LONG",
                    "price": price,
                    "quantity": quantity,
                    "fee": fee,
                })
                print(f"[PortfolioForward] OPEN_LONG {symbol} @ ${price:,.2f} qty={quantity:.4f}")

            elif quantity <= 0 and current_side == "LONG":
                pnl = self.position.close(symbol, price, timestamp)
                fee = abs(pnl) * self.fee_rate
                self.capital += pnl - fee
                _append("CLOSE", pnl, fee)

        elif order.side == Side.SELL:
            current_side = self.position.get_side(symbol)
            if current_side == "LONG":
                pnl = self.position.close(symbol, price, timestamp)
                fee = abs(pnl) * self.fee_rate
                self.capital += pnl - fee
                _append("CLOSE_LONG", pnl, fee)

            if quantity > 0 and not self.position.has_position(symbol):
                fee = quantity * price * self.fee_rate
                self.capital -= fee
                self.position.open(symbol, "SHORT", price, quantity, timestamp)
                self._record_exec({
                    "run_id": self.run_id,
                    "timestamp": timestamp,
                    "event_type": "trade",
                    "symbol": symbol,
                    "order_side": order.side.value,
                    "action": "OPEN_SHORT",
                    "price": price,
                    "qty": quantity,
                    "pnl": 0.0,
                    "fee": fee,
                    "qty_before": before_qty,
                    "qty_after": self._get_position_qty(symbol),
                })
                self.trade_log.append({
                    "timestamp": timestamp,
                    "symbol": symbol,
                    "action": "OPEN_SHORT",
                    "price": price,
                    "quantity": quantity,
                    "fee": fee,
                })
                print(f"[PortfolioForward] OPEN_SHORT {symbol} @ ${price:,.2f} qty={quantity:.4f}")

            elif quantity <= 0 and current_side == "SHORT":
                pnl = self.position.close(symbol, price, timestamp)
                fee = abs(pnl) * self.fee_rate
                self.capital += pnl - fee
                _append("CLOSE", pnl, fee)

    def _open_signal(self, symbol: str, side: str, price: float, quantity: float, position_value: float, timestamp: datetime) -> None:
        fee = position_value * self.fee_rate
        self.capital -= fee
        self.position.open(symbol, side, price, quantity, timestamp)
        self.trade_log.append({
            "timestamp": timestamp,
            "symbol": symbol,
            "action": f"OPEN_{side}",
            "price": price,
            "quantity": quantity,
            "fee": fee,
        })
        self._record_exec({
            "run_id": self.run_id,
            "timestamp": timestamp,
            "event_type": "trade",
            "symbol": symbol,
            "order_side": side,
            "action": f"OPEN_{side}",
            "price": price,
            "qty": quantity,
            "pnl": 0.0,
            "fee": fee,
            "qty_before": self._get_position_qty(symbol),
            "qty_after": self._get_position_qty(symbol),
        })
        print(f"[PortfolioForward] {side} {symbol} @ ${price:,.2f} qty={quantity:.4f}")

    def _execute_signal(self, symbol: str, signal: str, price: float, timestamp: datetime) -> None:
        position_value = self.capital * self.position_size_pct / len(self.symbols)
        quantity = position_value / price

        if signal in ("LONG", "SHORT"):
            if self.position.has_position(symbol):
                pnl = self.position.close(symbol, price, timestamp)
                fee = position_value * self.fee_rate
                self.capital += pnl - fee
                self._log_signal_trade(symbol, timestamp, price, "CLOSE", quantity, pnl, fee)

            self._open_signal(symbol, signal, price, quantity, position_value, timestamp)

        elif signal == "CLOSE_AND_LONG":
            if self.position.has_position(symbol):
                pnl = self.position.close(symbol, price, timestamp)
                fee = position_value * self.fee_rate
                self.capital += pnl - fee
                self._log_signal_trade(symbol, timestamp, price, "CLOSE", quantity, pnl, fee)
            self._open_signal(symbol, "LONG", price, quantity, position_value, timestamp)

        elif signal == "CLOSE_AND_SHORT":
            if self.position.has_position(symbol):
                pnl = self.position.close(symbol, price, timestamp)
                fee = position_value * self.fee_rate
                self.capital += pnl - fee
                self._log_signal_trade(symbol, timestamp, price, "CLOSE", quantity, pnl, fee)
            self._open_signal(symbol, "SHORT", price, quantity, position_value, timestamp)

        elif signal == "CLOSE":
            if self.position.has_position(symbol):
                pnl = self.position.close(symbol, price, timestamp)
                fee = position_value * self.fee_rate
                self.capital += pnl - fee
                self._log_signal_trade(symbol, timestamp, price, "CLOSE", quantity, pnl, fee)

    def _log_signal_trade(
        self,
        symbol: str,
        timestamp: datetime,
        price: float,
        action: str,
        quantity: float,
        pnl: float,
        fee: float,
    ) -> None:
        self.trade_log.append({
            "timestamp": timestamp,
            "symbol": symbol,
            "action": action,
            "price": price,
            "quantity": quantity,
            "pnl": pnl,
            "fee": fee,
        })
        self._record_exec({
            "run_id": self.run_id,
            "timestamp": timestamp,
            "event_type": "trade",
            "symbol": symbol,
            "order_side": "CLOSE",
            "action": action,
            "price": price,
            "qty": quantity,
            "pnl": pnl,
            "fee": fee,
            "qty_before": self._get_position_qty(symbol),
            "qty_after": self._get_position_qty(symbol),
        })

    def close_all_positions(self, timestamp: Optional[datetime] = None) -> None:
        if not self.position.get_all_positions():
            return

        ts = timestamp or datetime.now()
        prices = self.get_current_prices()

        for info in list(self.position.get_all_positions()):
            if info.symbol not in prices:
                continue
            price = prices[info.symbol]
            if info.side == "LONG":
                self._execute_portfolio_order(
                    info.symbol,
                    Order(side=Side.BUY, quantity=0.0, order_type=OrderType.MARKET),
                    price,
                    ts,
                )
            else:
                self._execute_portfolio_order(
                    info.symbol,
                    Order(side=Side.SELL, quantity=0.0, order_type=OrderType.MARKET),
                    price,
                    ts,
                )

    # ----- state + metrics -----
    def _trade_stats(self) -> dict[str, Any]:
        # A "closed" trade is one with a realised PnL. Plain ``"pnl" in t``
        # matches OPEN legs too (their dict carries pnl=None/NaN), which
        # would inflate total_trades 2x and crush win_rate by the same
        # factor. Filter on actual numeric PnL.
        closed = [t for t in self.trade_log if pd.notna(t.get("pnl"))]
        wins = sum(1 for t in closed if t.get("pnl", 0) > 0)
        losses = sum(1 for t in closed if t.get("pnl", 0) < 0)
        gross_profit = sum(t.get("pnl", 0) for t in closed if t.get("pnl", 0) > 0)
        gross_loss = abs(sum(t.get("pnl", 0) for t in closed if t.get("pnl", 0) < 0))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf") if gross_profit > 0 else 0.0
        return {
            "total_trades": len(closed),
            "wins": wins,
            "losses": losses,
            "win_rate": (wins / len(closed) * 100) if closed else 0.0,
            "profit_factor": profit_factor,
            "gross_profit": gross_profit,
            "gross_loss": gross_loss,
        }

    def get_current_prices(self) -> dict[str, float]:
        return {
            sym: st.last_price
            for sym, st in self.symbol_states.items()
            if st.last_price > 0
        }

    def _record_nav(self, timestamp: datetime) -> None:
        status = self.get_status()
        self.nav_events.append({
            "run_id": self.run_id,
            "timestamp": timestamp,
            "capital": status["capital"],
            "unrealized": status["unrealized_pnl"],
            "equity": status["equity"],
            "positions": status["positions"],
            "active_symbols": len(status["positions"]),
            "trades": status["trades_with_pnl"],
            "runtime_sec": status["runtime_sec"],
        })

    def _record_daily_weight(self, timestamp: datetime) -> None:
        date_key = timestamp.strftime("%Y-%m-%d")
        if self._last_daily_weight_date == date_key:
            return

        prices = self.get_current_prices()
        entries = []
        total_notional = 0.0
        for sym in self.symbols:
            if sym not in prices:
                continue
            qty = self._get_position_qty(sym)
            gross_notional = abs(qty * prices[sym])
            if gross_notional == 0:
                continue
            total_notional += gross_notional
            side = self.position.get_side(sym)
            signed_qty = qty if side == "LONG" else -qty
            entries.append((sym, signed_qty, gross_notional, prices[sym]))

        if not entries:
            self._last_daily_weight_date = date_key
            return

        for sym, signed_qty, gross_notional, price in entries:
            signed_notional = signed_qty * price
            self.weight_events.append({
                "timestamp": timestamp,
                "alpha_id": self.strategy.__class__.__name__,
                "symbol": sym,
                "target_weight": signed_notional / total_notional if total_notional else 0.0,
                "target_notional": signed_notional,
                "target_qty": signed_qty,
                "price": price,
                "bar_type": self.candle_type.value,
                "bar_size": float(self.candle_size),
                "metadata": json.dumps(
                    {"run_id": self.run_id, "source": "position_snapshot", "date": date_key},
                    ensure_ascii=False,
                    default=str,
                ),
            })

        self._last_daily_weight_date = date_key

    def get_status(self) -> dict[str, Any]:
        positions = self.position.to_dict()
        prices = self.get_current_prices()
        unrealized = self.position.get_unrealized_pnl(prices)
        stats = self._trade_stats()

        runtime_sec = (datetime.now() - self._start_time).total_seconds() if self._start_time else 0.0
        return {
            "timestamp": datetime.now().isoformat(),
            "capital": self.capital,
            "unrealized_pnl": unrealized,
            "equity": self.capital + unrealized,
            "positions": positions,
            "symbols": {
                sym: {
                    "price": st.last_price,
                    "candles": st.candle_count,
                }
                for sym, st in self.symbol_states.items()
            },
            "trades": len(self.trade_log),
            "trades_with_pnl": stats["total_trades"],
            "run_id": self.run_id,
            "last_rebalance_time": self._last_rebalance_time.isoformat() if self._last_rebalance_time else None,
            "runtime_sec": runtime_sec,
        }

    # ----- lifecycle -----
    async def run(self, duration_seconds: Optional[float] = None) -> None:
        self._running = True
        self._start_time = datetime.now()
        self._auto_save_last_at = self._start_time
        # Initialise the rebalance clock:
        #   - resume → pick up where the prior session left off (so the
        #     next candle close that's >= rebalance_minutes past it
        #     triggers a rebalance immediately).
        #   - fresh start → set the clock back by one full window so the
        #     first candle close after start triggers a rebalance, instead
        #     of waiting a full rebalance_minutes from wallclock start.
        if self._resumed_last_rebalance_time is not None:
            self._last_rebalance_time = self._resumed_last_rebalance_time
        else:
            self._last_rebalance_time = self._start_time - timedelta(
                minutes=self.rebalance_minutes
            )
        self._record_nav(self._start_time)

        print("=" * 60)
        print("🚀 Portfolio Forward Test")
        print("=" * 60)
        print(f"Run ID:     {self.run_id}")
        print(f"Strategy:   {self.strategy.__class__.__name__}")
        print(f"Symbols:    {self.symbols}")
        print(f"Candle:     {self.candle_type.value} / {self.candle_size}")
        print(f"Capital:    ${self.initial_capital:,.2f}")
        print(f"Fee Rate:   {self.fee_rate * 100:.2f}%")
        print(f"Rebalance:  {self.rebalance_minutes} min")
        print(f"Duration:   {duration_seconds}s" if duration_seconds is not None else "∞ (Ctrl+C)")
        print("=" * 60)

        client_tasks: list[asyncio.Task] = []
        # REST warmup: prepend the last ``warmup_bars`` closed klines so the
        # strategy state is non-empty before the live stream starts.
        if self.warmup_bars > 0:
            await self._kline_warmup(self.warmup_bars)
        stream = BinanceKlineStreamClient(
            symbols=self.symbols,
            interval=self._kline_interval,
        )
        self._clients["__kline_stream__"] = stream
        client_tasks.append(asyncio.create_task(stream.connect(on_kline_close=self.on_kline_close)))

        status_task = asyncio.create_task(self._status_printer())
        timer_task = (
            asyncio.create_task(self._stop_after(duration_seconds))
            if duration_seconds is not None
            else None
        )
        autosave_task = asyncio.create_task(self._auto_save_loop()) if self.auto_save_interval_seconds else None

        try:
            if timer_task:
                await timer_task
                await self.stop()
            else:
                await asyncio.gather(status_task, *client_tasks, return_exceptions=True)
                return

            status_task.cancel()
            for t in client_tasks:
                t.cancel()
            if autosave_task:
                autosave_task.cancel()
            await asyncio.gather(*[status_task, *client_tasks], return_exceptions=True)
            if autosave_task:
                await asyncio.gather(autosave_task, return_exceptions=True)

        except asyncio.CancelledError:
            await self.stop()
            status_task.cancel()
            for t in client_tasks:
                t.cancel()
            if autosave_task:
                autosave_task.cancel()
            await asyncio.gather(*[status_task, *client_tasks], return_exceptions=True)
            if autosave_task:
                await asyncio.gather(autosave_task, return_exceptions=True)
        finally:
            if self.close_on_stop:
                self.close_all_positions()
            self._record_nav(datetime.now())
            self._record_daily_weight(datetime.now())
            print(f"\n[PortfolioForward] Test ended.")
            print(f"[PortfolioForward] Capital: ${self.capital:,.2f}")
            print(f"[PortfolioForward] Trades: {len(self.trade_log)}")

    async def _status_printer(self) -> None:
        while self._running:
            await asyncio.sleep(self.status_print_interval)
            if not self._running:
                break
            status = self.get_status()
            equity = status["equity"]
            ret = (equity - self.initial_capital) / self.initial_capital * 100
            pos_str = ", ".join(f"{s}={p}" for s, p in status["positions"].items()) if status["positions"] else "None"
            print(f"[PortfolioForward] Equity=${equity:,.2f} ({ret:+.2f}%) | Positions: {pos_str}")

            self._record_nav(datetime.now())

    async def _kline_warmup(self, bars: int) -> None:
        """Fetch ``bars`` recent closed klines per symbol via REST and feed
        them through :meth:`on_kline_close` to seed strategy state."""
        self._warming_up = True
        client = BinanceKlinesClient()
        interval = self._kline_interval
        print(f"[Warmup] REST fetching {bars} {interval} bars for {len(self.symbols)} symbols...")
        # Bound concurrency so we don't hammer Binance.
        sem = asyncio.Semaphore(20)

        async def fetch(symbol: str) -> tuple[str, list[Kline]]:
            async with sem:
                try:
                    klines = await client.fetch_klines(symbol, interval, limit=bars + 1)
                    return symbol, klines
                except Exception as exc:  # noqa: BLE001
                    print(f"[Warmup] {symbol}: {exc}")
                    return symbol, []

        results = await asyncio.gather(*(fetch(s) for s in self.symbols))

        # Replay closed klines in chronological order to mirror the live
        # stream's ordering semantics.
        per_ts: dict[datetime, list[tuple[str, Kline]]] = {}
        for symbol, klines in results:
            # Last kline is the still-open current bar — drop it.
            for k in klines[:-1]:
                per_ts.setdefault(k.timestamp, []).append((symbol, k))

        for ts in sorted(per_ts.keys()):
            for symbol, kline in per_ts[ts]:
                self.on_kline_close(symbol, kline)

        total = sum(len(v) for v in per_ts.values())
        print(f"[Warmup] replayed {total} closed klines across {len(per_ts)} timestamps.")
        self._warming_up = False

    async def _auto_save_loop(self) -> None:
        while self._running:
            await asyncio.sleep(self.auto_save_interval_seconds)
            if not self._running:
                break
            self._auto_save_last_at = datetime.now()
            self._record_nav(self._auto_save_last_at)
            self._record_daily_weight(self._auto_save_last_at)
            if self.auto_save_output_dir is not None:
                try:
                    self.save_report(self.auto_save_output_dir)
                except Exception as exc:  # don't kill the loop on transient I/O errors
                    print(f"[PortfolioForward][Heartbeat] save_report failed: {exc}")
            print(f"[PortfolioForward][Heartbeat] run={self.run_id} len(logs)={len(self.nav_events)}")

    async def _stop_after(self, seconds: float) -> None:
        await asyncio.sleep(seconds)

    async def stop(self) -> None:
        self._running = False
        for client in self._clients.values():
            await client.stop()

    # ----- persistence -----
    def _to_parquet_safe(self, rows: list[dict[str, Any]], path: Path) -> None:
        # parquet가 dict/list 컬럼을 못 쓰는 경우가 있어 문자열로 정규화
        if not rows:
            schemas = {
                "weights.parquet": [
                    "timestamp",
                    "alpha_id",
                    "symbol",
                    "target_weight",
                    "target_notional",
                    "target_qty",
                    "price",
                    "bar_type",
                    "bar_size",
                    "metadata",
                ],
                "events.parquet": [
                    "run_id",
                    "rebalance_id",
                    "timestamp",
                    "event_type",
                    "symbol",
                    "target_side",
                    "target_weight",
                    "target_qty",
                    "target_notional",
                    "position_qty_before",
                    "position_qty_after",
                ],
                "trades.parquet": [
                    "timestamp",
                    "symbol",
                    "action",
                    "price",
                    "quantity",
                    "pnl",
                    "fee",
                ],
                "equity_curve.parquet": [
                    "run_id",
                    "timestamp",
                    "capital",
                    "unrealized",
                    "equity",
                    "positions",
                    "active_symbols",
                    "trades",
                    "runtime_sec",
                ],
                "portfolio_nav.parquet": [
                    "run_id",
                    "timestamp",
                    "capital",
                    "unrealized",
                    "equity",
                    "positions",
                    "active_symbols",
                    "trades",
                    "runtime_sec",
                ],
            }
            pd.DataFrame(columns=schemas.get(path.name, [])).to_parquet(path, index=False)
            return

        normalized: list[dict[str, Any]] = []
        for row in rows:
            normalized_row: dict[str, Any] = {}
            for k, v in row.items():
                if isinstance(v, (dict, list, tuple)):
                    normalized_row[k] = json.dumps(v, ensure_ascii=False, default=str)
                elif isinstance(v, datetime):
                    normalized_row[k] = pd.Timestamp(v)
                else:
                    normalized_row[k] = v
            normalized.append(normalized_row)

        df = pd.DataFrame(normalized)
        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"])

        df.to_parquet(path, index=False)

    def export_state(self) -> dict[str, Any]:
        status = self.get_status()
        stats = self._trade_stats()

        return {
            "run_id": self.run_id,
            "strategy": self.strategy.__class__.__name__,
            "symbols": self.symbols,
            "start_time": self._start_time.isoformat() if self._start_time else None,
            "last_rebalance_time": self._last_rebalance_time.isoformat() if self._last_rebalance_time else None,
            "status": status,
            "metrics": {
                "total_return_pct": ((status["equity"] - self.initial_capital) / self.initial_capital * 100) if self.initial_capital else 0.0,
                "trades_with_pnl": stats["total_trades"],
                "wins": stats["wins"],
                "losses": stats["losses"],
                "win_rate": stats["win_rate"],
                "profit_factor": stats["profit_factor"],
                "gross_profit": stats["gross_profit"],
                "gross_loss": stats["gross_loss"],
            },
        }

    def save_report(self, output_dir: str | Path) -> dict[str, Path]:
        out_root = Path(output_dir)
        run_dir = out_root / self.run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        state_payload = self.export_state()
        generated_at = datetime.now()
        state_payload["generated_at"] = generated_at.isoformat()

        state_json = run_dir / "summary.json"
        manifest_json = run_dir / "manifest.json"
        metrics_json = run_dir / "metrics.json"
        summary_csv = run_dir / "summary.csv"
        events_parquet = run_dir / "events.parquet"
        trades_parquet = run_dir / "trades.parquet"
        weights_parquet = run_dir / "weights.parquet"
        equity_curve_parquet = run_dir / "equity_curve.parquet"
        nav_parquet = run_dir / "portfolio_nav.parquet"

        events_rows = self.rebalance_events + self.execution_events
        metrics = state_payload["metrics"]
        flat_metrics = {
            "profit_factor": metrics["profit_factor"],
            "total_return": metrics["total_return_pct"] / 100,
            "total_return_pct": metrics["total_return_pct"],
            "max_drawdown": None,
            "max_drawdown_pct": None,
            "total_trades": metrics["trades_with_pnl"],
            "win_rate": metrics["win_rate"] / 100,
            "win_rate_pct": metrics["win_rate"],
            "sharpe": None,
            "sharpe_ratio": None,
        }

        # summary.json
        state_json.write_text(json.dumps(state_payload, ensure_ascii=False, default=str, indent=2), encoding="utf-8")
        metrics_json.write_text(
            json.dumps(flat_metrics, ensure_ascii=False, default=str, indent=2),
            encoding="utf-8",
        )
        manifest_json.write_text(
            json.dumps(
                {
                    "artifact_version": 1,
                    "run_type": "forward",
                    "run_id": self.run_id,
                    "strategy_name": self.strategy.__class__.__name__,
                    "symbols": self.symbols,
                    "started_at": self._start_time.isoformat() if self._start_time else None,
                    "ended_at": generated_at.isoformat(),
                    "files": {
                        "summary": "summary.json",
                        "metrics": "metrics.json",
                        "summary_csv": "summary.csv",
                        "equity_curve": "equity_curve.parquet",
                        "portfolio_nav": "portfolio_nav.parquet",
                        "trades": "trades.parquet",
                        "weights": "weights.parquet",
                        "events": "events.parquet",
                    },
                },
                ensure_ascii=False,
                default=str,
                indent=2,
            ),
            encoding="utf-8",
        )

        # summary.csv (human)
        summary_csv.write_text(
            "run_id,strategy,total_return_pct,trades_with_pnl,wins,losses,win_rate,profit_factor,equity,capital,unrealized,generated_at\n"
            f"{self.run_id},{self.strategy.__class__.__name__},{state_payload['metrics']['total_return_pct']:.6f},"
            f"{state_payload['metrics']['trades_with_pnl']},{state_payload['metrics']['wins']},{state_payload['metrics']['losses']},"
            f"{state_payload['metrics']['win_rate']:.4f},{state_payload['metrics']['profit_factor']},"
            f"{self.get_status()['equity']},{self.capital},{self.get_status()['unrealized_pnl']},{state_payload['generated_at']}\n",
            encoding="utf-8",
        )

        self._to_parquet_safe(events_rows, events_parquet)
        self._to_parquet_safe(self.trade_log, trades_parquet)
        self._to_parquet_safe(self.weight_events, weights_parquet)
        self._to_parquet_safe(self.nav_events, equity_curve_parquet)
        self._to_parquet_safe(self.nav_events, nav_parquet)

        return {
            "state": state_json,
            "summary": state_json,
            "manifest": manifest_json,
            "metrics": metrics_json,
            "events": events_parquet,
            "trades": trades_parquet,
            "weights": weights_parquet,
            "equity_curve": equity_curve_parquet,
            "portfolio": nav_parquet,
            "summary_csv": summary_csv,
        }
