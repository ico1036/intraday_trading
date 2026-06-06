"""
포트폴리오 Tick 기반 백테스트 러너 (Phase 2)

여러 심볼의 틱 스트림을 시간순으로 병합하고,
심볼별 독립 캔들 빌드 + 패널 데이터 전략 전달.

heapq.merge로 O(N log K) 병합 (K = 심볼 수).

사용 예시:
    loaders = {
        "BTCUSDT": TickDataLoader(Path("./data/BTCUSDT")),
        "ETHUSDT": TickDataLoader(Path("./data/ETHUSDT")),
    }
    strategy = CrossCoinMomentumStrategy(symbols=["BTCUSDT", "ETHUSDT"])

    runner = PortfolioTickBacktestRunner(
        strategy=strategy,
        data_loaders=loaders,
        bar_type=CandleType.TIME,
        bar_size=60,
    )
    result = runner.run()
"""

import heapq
import inspect
import json
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Iterator
import logging
import time
from pathlib import Path

import numpy as np
import pandas as pd
from ..backtest.metrics import sharpe_daily_annualized

from ..candle_builder import CandleBuilder, CandleType, Candle
from ..client import AggTrade
from ..data.loader import TickDataLoader
from ..paper_trader import PaperTrader
from ..strategy import Strategy, MarketState, Order, Side, OrderType, PortfolioOrder


@dataclass
class SymbolTradeLog:
    """심볼별 거래 로그 항목"""
    timestamp: datetime
    symbol: str
    action: str  # OPEN_LONG, OPEN_SHORT, CLOSE
    price: float
    quantity: float
    fee: float
    pnl: float = 0.0


@dataclass
class PortfolioTickResult:
    """
    포트폴리오 틱 백테스트 결과

    Portfolio tick runner result with portfolio-level metrics and per-symbol
    execution logs.
    """
    initial_capital: float
    final_capital: float
    total_return: float  # 비율 (0.05 = 5%)
    sharpe_ratio: float
    max_drawdown: float  # 비율 (0.10 = 10%)
    total_trades: int
    winning_trades: int
    losing_trades: int
    equity_curve: pd.Series
    trade_log: list[dict]
    tick_counts: dict[str, int] = field(default_factory=dict)
    bar_counts: dict[str, int] = field(default_factory=dict)

    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return self.winning_trades / self.total_trades

    @property
    def profit_factor(self) -> float:
        gross_profit = sum(t["pnl"] for t in self.trade_log if t.get("pnl", 0) > 0)
        gross_loss = abs(sum(t["pnl"] for t in self.trade_log if t.get("pnl", 0) < 0))
        if gross_loss == 0:
            return float("inf") if gross_profit > 0 else 0.0
        return gross_profit / gross_loss

    def get_symbol_breakdown(self) -> dict[str, dict]:
        """심볼별 성과 분석"""
        breakdown: dict[str, dict] = {}
        for trade in self.trade_log:
            symbol = trade.get("symbol")
            if symbol is None:
                continue
            if symbol not in breakdown:
                breakdown[symbol] = {
                    "total_pnl": 0.0,
                    "trades": 0,
                    "wins": 0,
                    "losses": 0,
                }
            pnl = trade.get("pnl", 0)
            if pnl != 0:
                breakdown[symbol]["total_pnl"] += pnl
                breakdown[symbol]["trades"] += 1
                if pnl > 0:
                    breakdown[symbol]["wins"] += 1
                elif pnl < 0:
                    breakdown[symbol]["losses"] += 1
        return breakdown

    def summary(self) -> str:
        return f"""
=== Portfolio Tick Backtest Result ===
Initial Capital: ${self.initial_capital:,.2f}
Final Capital:   ${self.final_capital:,.2f}
Total Return:    {self.total_return * 100:.2f}%
Sharpe Ratio:    {self.sharpe_ratio:.2f}
Max Drawdown:    {self.max_drawdown * 100:.2f}%
Total Trades:    {self.total_trades}
Win Rate:        {self.win_rate * 100:.1f}%
Profit Factor:   {self.profit_factor:.2f}
"""


# ─── 포트폴리오 포지션 관리 ───────────────────────

@dataclass
class _PositionInfo:
    symbol: str
    side: str  # "LONG" or "SHORT"
    entry_price: float
    quantity: float
    entry_time: datetime
    liquidation_price: float | None = None
    margin: float = 0.0


class _MultiPosition:
    """심볼별 독립 포지션 관리"""

    def __init__(self):
        self._positions: dict[str, _PositionInfo] = {}

    def open(
        self,
        symbol: str,
        side: str,
        price: float,
        quantity: float,
        ts: datetime,
        liquidation_price: float | None = None,
        margin: float = 0.0,
    ):
        self._positions[symbol] = _PositionInfo(
            symbol,
            side,
            price,
            quantity,
            ts,
            liquidation_price=liquidation_price,
            margin=margin,
        )

    def close(self, symbol: str, price: float, ts: datetime) -> float:
        if symbol not in self._positions:
            return 0.0
        pos = self._positions.pop(symbol)
        if pos.side == "LONG":
            return (price - pos.entry_price) * pos.quantity
        return (pos.entry_price - price) * pos.quantity

    def partial_close(self, symbol: str, price: float, qty: float, ts: datetime) -> float:
        """Close ``qty`` units of an existing position, realizing PnL on
        that portion. Remaining qty keeps original entry_price. If the
        requested qty meets or exceeds current qty, the position is fully
        closed and removed."""
        pos = self._positions.get(symbol)
        if pos is None or qty <= 0:
            return 0.0
        close_qty = min(qty, pos.quantity)
        if pos.side == "LONG":
            pnl = (price - pos.entry_price) * close_qty
        else:
            pnl = (pos.entry_price - price) * close_qty
        remaining = pos.quantity - close_qty
        if remaining <= 0:
            self._positions.pop(symbol)
        else:
            pos.quantity = remaining
        return pnl

    def add(self, symbol: str, price: float, qty: float, ts: datetime) -> None:
        """Increase an existing position by ``qty`` units, updating the
        entry_price to a quantity-weighted average."""
        pos = self._positions.get(symbol)
        if pos is None or qty <= 0:
            return
        new_qty = pos.quantity + qty
        pos.entry_price = (pos.entry_price * pos.quantity + price * qty) / new_qty
        pos.quantity = new_qty

    def has(self, symbol: str) -> bool:
        return symbol in self._positions

    def get_side(self, symbol: str) -> Optional[str]:
        pos = self._positions.get(symbol)
        return pos.side if pos else None

    def get_qty(self, symbol: str) -> float:
        pos = self._positions.get(symbol)
        return pos.quantity if pos else 0.0

    def get_entry_price(self, symbol: str) -> float:
        pos = self._positions.get(symbol)
        return pos.entry_price if pos else 0.0

    def get(self, symbol: str) -> _PositionInfo | None:
        return self._positions.get(symbol)

    def to_dict(self) -> dict:
        """패널용 positions dict"""
        return {
            sym: {
                "side": pos.side,
                "qty": pos.quantity,
                "entry_price": pos.entry_price,
            }
            for sym, pos in self._positions.items()
        }

    def unrealized_pnl(self, prices: dict[str, float]) -> float:
        total = 0.0
        for sym, pos in self._positions.items():
            if sym in prices:
                if pos.side == "LONG":
                    total += (prices[sym] - pos.entry_price) * pos.quantity
                else:
                    total += (pos.entry_price - prices[sym]) * pos.quantity
        return total

    @property
    def all_symbols(self) -> list[str]:
        return list(self._positions.keys())


# ─── 메인 러너 ───────────────────────────

class PortfolioTickBacktestRunner:
    """
    포트폴리오 Tick 기반 백테스트 러너

    여러 심볼의 AggTrade 스트림을 heapq.merge로 병합,
    심볼별 CandleBuilder로 독립 캔들 생성,
    캔들 완성 시 패널 데이터를 전략에 전달.
    """

    def __init__(
        self,
        strategy,
        data_loaders: dict[str, "TickDataLoader"],
        bar_type: CandleType = CandleType.VOLUME,
        bar_size: float = 1.0,
        initial_capital: float = 10000.0,
        position_size_pct: float = 0.1,
        fee_rate: float | None = None,
        maker_fee_rate: float = 0.0017,
        taker_fee_rate: float = 0.0020,
        leverage: int = 1,
        fixed_aum_sizing: bool = False,
        max_portfolio_weight: float = 1.0,
    ):
        self.strategy = strategy
        self.data_loaders = data_loaders
        self.bar_type = bar_type
        self.bar_size = bar_size
        self.initial_capital = initial_capital
        self.position_size_pct = position_size_pct
        self.leverage = leverage
        self.max_portfolio_weight = float(max_portfolio_weight)
        # When True, position notional is computed off ``initial_capital``
        # rather than ``self._capital``. For a long/short strategy this
        # decouples per-leg size from the running PnL — drawdowns don't
        # shrink subsequent legs and recoveries don't pump them, which is
        # the standard convention for evaluating a market-neutral signal.
        self.fixed_aum_sizing = bool(fixed_aum_sizing)

        if fee_rate is not None:
            self.maker_fee_rate = fee_rate
            self.taker_fee_rate = fee_rate
        else:
            self.maker_fee_rate = maker_fee_rate
            self.taker_fee_rate = taker_fee_rate

        # 심볼 목록 (정렬 for determinism)
        self._symbols = sorted(data_loaders.keys())

        # 심볼별 CandleBuilder
        self._candle_builders: dict[str, CandleBuilder] = {
            sym: CandleBuilder(bar_type, bar_size) for sym in self._symbols
        }

        # 심볼별 최신 캔들 (패널 구성용)
        self._latest_candles: dict[str, Candle] = {}

        # 심볼별 최신 가격
        self._latest_prices: dict[str, float] = {}

        # 포지션 관리
        self._position = _MultiPosition()

        # 자본
        self._capital = initial_capital

        # 거래 로그
        self._trade_log: list[dict] = []
        self._weight_events: list[dict] = []
        self._event_log: list[dict] = []
        self._pending_orders: dict[str, tuple[Order, datetime]] = {}
        self._last_result: PortfolioTickResult | None = None

        # 에쿼티 커브
        self._equity_points: list[float] = []
        self._equity_timestamps: list[pd.Timestamp] = []

        # 통계
        self._tick_counts: dict[str, int] = {sym: 0 for sym in self._symbols}
        self._bar_counts: dict[str, int] = {sym: 0 for sym in self._symbols}
        self._total_ticks_target: int | None = None
        self._wall_start_ts: float = 0.0

        self._logger = logging.getLogger(__name__)

        # 시간
        self._start_time: Optional[datetime] = None
        self._end_time: Optional[datetime] = None

    @property
    def symbols(self) -> list[str]:
        return self._symbols

    @property
    def bar_counts(self) -> dict[str, int]:
        return self._bar_counts.copy()

    @property
    def tick_counts(self) -> dict[str, int]:
        return self._tick_counts.copy()

    def _alpha_id(self) -> str:
        return str(getattr(self.strategy, "alpha_id", self.strategy.__class__.__name__))

    def _merge_ticks(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> Iterator[tuple[str, AggTrade]]:
        """
        모든 심볼의 틱을 시간순으로 병합.

        heapq.merge 사용: O(N log K) (K = 심볼 수).
        Returns (symbol, AggTrade) tuples.
        """

        def _tagged_iter(symbol: str):
            """(timestamp, counter, symbol, trade) 형태로 래핑 (heapq 정렬 키)"""
            loader = self.data_loaders[symbol]
            for i, trade in enumerate(loader.iter_trades(start_time, end_time)):
                yield (trade.timestamp, i, symbol, trade)

        merged = heapq.merge(
            *[_tagged_iter(sym) for sym in self._symbols],
        )

        for _ts, _i, symbol, trade in merged:
            yield (symbol, trade)

    def _merge_bars(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> Iterator[tuple[str, Candle]]:
        """Merge symbol bar streams by timestamp."""

        def _tagged_iter(symbol: str):
            loader = self.data_loaders[symbol]
            for i, candle in enumerate(loader.iter_bars(start_time, end_time)):
                yield (candle.timestamp, i, symbol, candle)

        merged = heapq.merge(*[_tagged_iter(sym) for sym in self._symbols])
        for _ts, _i, symbol, candle in merged:
            yield (symbol, candle)

    def _uses_bar_loaders(self) -> bool:
        return all(callable(getattr(loader, "iter_bars", None)) for loader in self.data_loaders.values())

    def _estimate_loader_rows(
        self,
        loader: object,
        start_time: Optional[datetime],
        end_time: Optional[datetime],
    ) -> int:
        """호환성 있는 행 수 추정(테스트용 로더 대응)."""
        estimator = getattr(loader, "estimate_total_rows", None)
        if callable(estimator):
            try:
                return int(estimator(start_time, end_time))
            except TypeError:
                # 일부 구현은 인자 없이 동작할 수도 있어 fallback 시도
                return int(estimator())
            except Exception:
                return 0

        iter_trades = getattr(loader, "iter_trades", None)
        if callable(iter_trades):
            try:
                return sum(1 for _ in iter_trades(start_time, end_time))
            except TypeError:
                return sum(1 for _ in iter_trades())
            except Exception:
                return 0

        trades = getattr(loader, "_trades", None)
        if trades is not None and hasattr(trades, "__len__"):
            try:
                return len(trades)
            except Exception:
                return 0

        trades = getattr(loader, "trades", None)
        if trades is not None and hasattr(trades, "__len__"):
            try:
                return len(trades)
            except Exception:
                return 0

        return 0

    def _build_panel(self) -> dict:
        """현재 최신 캔들로 패널 데이터 구성"""
        panel = {}
        for sym, candle in self._latest_candles.items():
            panel[sym] = {
                "timestamp": candle.timestamp,
                "open": candle.open,
                "high": candle.high,
                "low": candle.low,
                "close": candle.close,
                "volume": candle.volume,
                "quote_volume": candle.quote_volume,
                "trade_count": candle.trade_count,
                "buy_volume": candle.buy_volume,
                "sell_volume": candle.sell_volume,
                "vwap": candle.vwap,
                "volume_imbalance": candle.volume_imbalance,
            }
        return panel

    def _build_positions_dict(self) -> dict:
        """현재 포지션을 패널 전달용 dict으로"""
        return self._position.to_dict()

    def _resolve_order_quantity(
        self,
        symbol: str,
        order: Order,
        price: float,
    ) -> float:
        """주문 수량을 계산.

        기본 동작:
        - quantity가 주어진 경우 해당 수량 사용
        - quantity가 0 이하이고 weight가 주어진 경우,
          현재 자본 * position_size_pct * weight * leverage 로 수량 산정
        - weight는 전략 내 배분 비중이며, 기본 cap은 1.0이다. 레버리지
          replay는 ``max_portfolio_weight``로 더 큰 gross budget을 명시한다.
        """
        if order.quantity > 0:
            return order.quantity

        if order.weight is None:
            return 0.0

        if not (0 < order.weight <= self.max_portfolio_weight):
            raise ValueError(f"Invalid order weight for {symbol}: {order.weight}")

        # Compound (default): scale by current capital. Fixed-AUM: scale
        # by the constant initial capital so leg notional is invariant to
        # accumulated PnL — see ``fixed_aum_sizing`` in __init__.
        capital_base = self.initial_capital if self.fixed_aum_sizing else self._capital
        position_value = capital_base * self.position_size_pct * order.weight * self.leverage
        return position_value / price if price > 0 else 0.0

    def _target_weight(self, order: Order) -> float | None:
        if order.weight is None:
            return None
        return float(order.weight) * self.position_size_pct * self.leverage

    def _record_weight_event(
        self,
        *,
        symbol: str,
        order: Order,
        price: float,
        timestamp: datetime,
        source: str,
    ) -> None:
        target_qty = 0.0
        target_notional = 0.0
        target_weight = 0.0
        try:
            qty = self._resolve_order_quantity(symbol, order, price)
            sign = 1.0 if order.side == Side.BUY else -1.0
            target_qty = sign * qty
            target_notional = target_qty * price
            scaled_weight = self._target_weight(order)
            target_weight = (
                sign * scaled_weight
                if scaled_weight is not None
                else target_notional / self._capital if self._capital else 0.0
            )
        except ValueError:
            target_qty = float("nan")
            target_notional = float("nan")
            target_weight = float("nan")

        self._weight_events.append({
            "timestamp": timestamp,
            "alpha_id": self._alpha_id(),
            "symbol": symbol,
            "target_weight": target_weight,
            "target_notional": target_notional,
            "target_qty": target_qty,
            "price": price,
            "bar_type": self.bar_type.value,
            "bar_size": float(self.bar_size),
            "metadata": json.dumps(
                {
                    "source": source,
                    "order_side": order.side.value,
                    "order_type": order.order_type.value,
                    "limit_price": order.limit_price,
                },
                default=str,
            ),
        })

    def _queue_order(
        self,
        symbol: str,
        order: Order,
        timestamp: datetime,
        source: str,
    ) -> None:
        price = self._latest_prices.get(symbol, 0.0)
        if price > 0:
            self._record_weight_event(
                symbol=symbol,
                order=order,
                price=price,
                timestamp=timestamp,
                source=source,
            )
        self._pending_orders[symbol] = (order, timestamp)

    def _execute_pending_order(
        self,
        symbol: str,
        price: float,
        timestamp: datetime,
    ) -> None:
        """Execute the pending order at the next bar arrival.

        The signal-vs-execution boundary uses strict ``<`` so that orders
        queued earlier in a bar event (step 4 of one symbol's processing)
        can fire at a later bar event sharing the same timestamp. This is
        required for daily-bar backtests where every same-day bar shares
        a midnight UTC timestamp: without it, the very first symbol's
        emission overwrites pending orders for every other symbol on the
        same day, and those symbols never trade.

        Within a single bar event there is no self-trigger risk because
        ``_execute_pending_order`` (step 1) is always called BEFORE
        ``_execute_strategy`` (step 4) which sets new pending.
        """
        pending = self._pending_orders.get(symbol)
        if pending is None:
            return
        order, signal_ts = pending
        if timestamp < signal_ts:
            return
        self._pending_orders.pop(symbol, None)
        self._execute_order(symbol, order, price, timestamp)

    def _validate_weight_sum(self, order: PortfolioOrder) -> None:
        """Validate the gross target weight budget for a portfolio order."""
        weighted_orders = [
            o for o in order.active_orders.values()
            if o.weight is not None
        ]
        if not weighted_orders:
            return

        total_weight = sum(o.weight for o in weighted_orders if o.weight is not None)
        # 0 또는 음수는 의도하지 않은 비중 설정으로 간주
        if total_weight <= 0:
            raise ValueError("All weighted orders have non-positive total weight")
        if total_weight > self.max_portfolio_weight + 1e-12:
            raise ValueError(
                f"Sum of order weights exceeds {self.max_portfolio_weight:.6f}: {total_weight:.6f}"
            )

    def _liquidation_price(self, entry_price: float, side: str) -> float | None:
        if self.leverage <= 1:
            return None

        mmr = PaperTrader.MAINTENANCE_MARGIN_RATE
        if side == "LONG":
            return entry_price * (1 / self.leverage - 1) / (mmr - 1)
        return entry_price * (1 / self.leverage + 1) / (mmr + 1)

    def _margin(self, price: float, quantity: float) -> float:
        if self.leverage <= 1:
            return 0.0
        return price * quantity / self.leverage

    def _liquidate_if_needed(
        self,
        symbol: str,
        price: float,
        timestamp: datetime,
    ) -> bool:
        pos = self._position.get(symbol)
        if pos is None or pos.liquidation_price is None:
            return False

        if pos.side == "LONG":
            should_liquidate = price <= pos.liquidation_price
        else:
            should_liquidate = price >= pos.liquidation_price
        if not should_liquidate:
            return False

        if pos.side == "LONG":
            pnl = (pos.liquidation_price - pos.entry_price) * pos.quantity
        else:
            pnl = (pos.entry_price - pos.liquidation_price) * pos.quantity

        remaining_margin = max(0.0, pos.margin + pnl)
        loss = pos.margin - remaining_margin
        self._capital -= loss
        self._position.close(symbol, pos.liquidation_price, timestamp)
        self._trade_log.append({
            "timestamp": timestamp,
            "symbol": symbol,
            "action": "LIQUIDATION",
            "price": pos.liquidation_price,
            "quantity": pos.quantity,
            "pnl": -loss,
            "fee": 0.0,
        })
        return True

    def _liquidate_if_needed_in_bar(
        self,
        symbol: str,
        candle: Candle,
    ) -> bool:
        pos = self._position.get(symbol)
        if pos is None or pos.liquidation_price is None:
            return False
        price = candle.low if pos.side == "LONG" else candle.high
        return self._liquidate_if_needed(symbol, price, candle.timestamp)

    def _execute_order(
        self,
        symbol: str,
        order: Order,
        price: float,
        timestamp: datetime,
    ) -> None:
        """Execute a single-symbol order targeting a notional weight.

        Semantics:
          - close-marker (weight=None, quantity=0): close existing position
            on the matching side, no new position opened.
          - weight-based BUY/SELL: rebalance to a target qty derived from
            ``weight × capital × leverage / price``. The transition between
            current and target position is executed as a DELTA trade — only
            the difference is bought / sold, paying fee on the delta.
            * no position → open at target qty
            * opposite side → close all + open at target (direction flip)
            * same side, target > current → add the missing qty
            * same side, target < current → partial close to target qty
        """
        is_market = order.order_type == OrderType.MARKET
        fee_rate = self.taker_fee_rate if is_market else self.maker_fee_rate

        is_close_marker = (order.weight is None) and (order.quantity == 0)
        current_side = self._position.get_side(symbol) if self._position.has(symbol) else None

        # ---- close-marker: close existing matching-side position only ----
        if is_close_marker:
            if current_side is None:
                return
            closes_long = (order.side == Side.SELL and current_side == "LONG")
            closes_short = (order.side == Side.BUY and current_side == "SHORT")
            if not (closes_long or closes_short):
                return
            self._close_existing(symbol, price, timestamp, fee_rate, current_side)
            return

        # ---- weight-based target order ----
        target_side = "LONG" if order.side == Side.BUY else "SHORT"
        target_qty = self._resolve_order_quantity(symbol, order, price)
        if target_qty <= 0:
            return

        # No prior position: simple open at target.
        if current_side is None:
            self._open_at_target(symbol, target_side, price, target_qty, timestamp, fee_rate)
            return

        # Direction flip: close all of current side, then open new fully.
        if current_side != target_side:
            self._close_existing(symbol, price, timestamp, fee_rate, current_side)
            target_qty = self._resolve_order_quantity(symbol, order, price)
            if target_qty <= 0:
                return
            self._open_at_target(symbol, target_side, price, target_qty, timestamp, fee_rate)
            return

        # Same side: trade only the delta to reach target qty.
        current_qty = self._position.get_qty(symbol)
        delta = target_qty - current_qty
        if abs(delta) < 1e-12:
            return
        if delta > 0:
            # Increase position by ``delta`` (BUY for LONG, SELL for SHORT).
            notional = price * delta
            fee = notional * fee_rate
            self._capital -= fee
            self._position.add(symbol, price, delta, timestamp)
            self._trade_log.append({
                "timestamp": timestamp,
                "symbol": symbol,
                "action": "OPEN_LONG" if target_side == "LONG" else "OPEN_SHORT",
                "price": price,
                "quantity": delta,
                "fee": fee,
            })
        else:
            # Reduce position by |delta| via partial close.
            close_qty = -delta
            pnl = self._position.partial_close(symbol, price, close_qty, timestamp)
            fee = price * close_qty * fee_rate
            self._capital += pnl - fee
            self._trade_log.append({
                "timestamp": timestamp,
                "symbol": symbol,
                "action": "CLOSE_LONG" if target_side == "LONG" else "CLOSE_SHORT",
                "price": price,
                "pnl": pnl,
                "quantity": close_qty,
                "fee": fee,
            })

    def _open_at_target(
        self,
        symbol: str,
        target_side: str,
        price: float,
        target_qty: float,
        timestamp: datetime,
        fee_rate: float,
    ) -> None:
        notional = price * target_qty
        fee = notional * fee_rate
        self._capital -= fee
        self._position.open(
            symbol,
            target_side,
            price,
            target_qty,
            timestamp,
            liquidation_price=self._liquidation_price(price, target_side),
            margin=self._margin(price, target_qty),
        )
        self._trade_log.append({
            "timestamp": timestamp,
            "symbol": symbol,
            "action": "OPEN_LONG" if target_side == "LONG" else "OPEN_SHORT",
            "price": price,
            "quantity": target_qty,
            "fee": fee,
        })

    def _close_existing(
        self,
        symbol: str,
        price: float,
        timestamp: datetime,
        fee_rate: float,
        current_side: str,
    ) -> None:
        """Close a held position, realize PnL into capital, log the close."""
        close_qty = self._position.get_qty(symbol)
        pnl = self._position.close(symbol, price, timestamp)
        fee = price * close_qty * fee_rate
        self._capital += pnl - fee
        self._trade_log.append({
            "timestamp": timestamp,
            "symbol": symbol,
            "action": "CLOSE_LONG" if current_side == "LONG" else "CLOSE_SHORT",
            "price": price,
            "pnl": pnl,
            "fee": fee,
        })

    def _execute_strategy(
        self,
        trigger_symbol: str,
        candle: Candle,
        timestamp: datetime,
    ) -> None:
        """캔들 완성 시 전략 실행"""
        # 패널 데이터 구성
        panel = self._build_panel() if self._latest_candles else None
        positions = self._build_positions_dict() or None

        # position info for the triggering symbol
        pos_side = None
        pos_qty = 0.0
        side_str = self._position.get_side(trigger_symbol)
        if side_str == "LONG":
            pos_side = Side.BUY
            pos_qty = self._position.get_qty(trigger_symbol)
        elif side_str == "SHORT":
            pos_side = Side.SELL
            pos_qty = self._position.get_qty(trigger_symbol)

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
            position_side=pos_side,
            position_qty=pos_qty,
            open=candle.open,
            high=candle.high,
            low=candle.low,
            close=candle.close,
            volume=candle.volume,
            vwap=candle.vwap,
            # 포트폴리오 확장
            symbol=trigger_symbol,
            panel=panel,
            positions=positions,
        )

        result = self.strategy.generate_order(state)

        if result is None:
            return

        if isinstance(result, PortfolioOrder):
            # 포트폴리오 주문
            self._validate_weight_sum(result)
            for sym, order in result.active_orders.items():
                self._queue_order(sym, order, timestamp, source="portfolio_order")
        elif isinstance(result, Order):
            # 단일 심볼 주문 → trigger_symbol에 적용
            self._queue_order(trigger_symbol, result, timestamp, source="single_order")

    def run(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> PortfolioTickResult:
        """백테스트 실행"""
        if self._uses_bar_loaders():
            return self._run_bars(start_time=start_time, end_time=end_time)

        if not self._logger.handlers:
            logging.basicConfig(
                level=logging.INFO,
                format="%(asctime)s | %(levelname)s | %(message)s",
            )

        self._logger.info("[PortfolioTick] Starting portfolio-symbol backtest...")
        self._logger.info("[PortfolioTick] Symbols: %s", ", ".join(self._symbols))
        self._logger.info("[PortfolioTick] Bar Type: %s, Size: %s", self.bar_type.value, self.bar_size)
        self._logger.info("[PortfolioTick] Initial Capital: $%.2f", self.initial_capital)
        if start_time and end_time:
            self._logger.info("[PortfolioTick] Period: %s ~ %s", start_time, end_time)
        elif start_time:
            self._logger.info("[PortfolioTick] Period: %s ~ (end of data)", start_time)
        elif end_time:
            self._logger.info("[PortfolioTick] Period: (start of data) ~ %s", end_time)

        # 리셋
        self._capital = self.initial_capital
        self._equity_points = []
        self._trade_log = []
        self._weight_events = []
        self._event_log = []
        self._pending_orders = {}
        self._last_result = None
        self._tick_counts = {sym: 0 for sym in self._symbols}
        self._bar_counts = {sym: 0 for sym in self._symbols}
        self._wall_start_ts = time.perf_counter()
        self._total_ticks_target = 0
        for loader in self.data_loaders.values():
            self._total_ticks_target += self._estimate_loader_rows(loader, start_time, end_time)
        self._latest_candles = {}
        self._latest_prices = {}
        self._position = _MultiPosition()
        self._start_time = None
        self._end_time = None

        for sym in self._symbols:
            self._candle_builders[sym]._reset()

        total_ticks = 0

        for symbol, trade in self._merge_ticks(start_time, end_time):
            # 시간 기록
            if self._start_time is None:
                self._start_time = trade.timestamp
            self._end_time = trade.timestamp

            self._tick_counts[symbol] += 1
            self._latest_prices[symbol] = trade.price
            total_ticks += 1
            self._liquidate_if_needed(symbol, trade.price, trade.timestamp)
            self._execute_pending_order(symbol, trade.price, trade.timestamp)

            if total_ticks % 10000 == 0:
                self._print_progress(total_ticks, unit="ticks")

            # 심볼별 캔들 빌드
            completed = self._candle_builders[symbol].update(trade)

            if completed:
                self._bar_counts[symbol] += 1
                self._latest_candles[symbol] = completed

                # 전략 실행
                self._execute_strategy(symbol, completed, trade.timestamp)

            # 에쿼티 기록 (1000틱마다)
            if total_ticks % 1000 == 0:
                unrealized = self._position.unrealized_pnl(self._latest_prices)
                equity = self._capital + unrealized
                self._equity_points.append(equity)
                self._equity_timestamps.append(trade.timestamp)

        elapsed = time.perf_counter() - self._wall_start_ts
        total_ticks_processed = sum(self._tick_counts.values())
        self._logger.info("[PortfolioTick] Completed! Ticks: %s, Symbols: %s", f"{total_ticks_processed:,}", len(self._symbols))
        self._logger.info("[PortfolioTick] Completed in %.2fs", elapsed)

        # 최종 청산
        for sym in list(self._position.all_symbols):
            price = self._latest_prices.get(sym, 0)
            if price > 0:
                close_qty = self._position.get_qty(sym)
                pnl = self._position.close(sym, price, self._end_time or datetime.now())
                fee = price * close_qty * self.taker_fee_rate
                self._capital += pnl - fee
                self._trade_log.append({
                    "timestamp": self._end_time,
                    "symbol": sym,
                    "action": "CLOSE_FINAL",
                    "price": price,
                    "pnl": pnl,
                    "fee": fee,
                })

        # 마지막 에쿼티 포인트
        self._equity_points.append(self._capital)
        if self._end_time is not None:
            self._equity_timestamps.append(self._end_time)

        self._last_result = self._compute_result()
        return self._last_result

    def _run_bars(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> PortfolioTickResult:
        """Run from prebuilt bars. Signals use current bar; fills occur next bar open."""
        if not self._logger.handlers:
            logging.basicConfig(
                level=logging.INFO,
                format="%(asctime)s | %(levelname)s | %(message)s",
            )

        self._logger.info("[PortfolioBars] Starting portfolio-symbol backtest...")
        self._logger.info("[PortfolioBars] Symbols: %s", ", ".join(self._symbols))
        self._logger.info("[PortfolioBars] Initial Capital: $%.2f", self.initial_capital)

        self._capital = self.initial_capital
        self._equity_points = []
        self._equity_timestamps = []
        self._trade_log = []
        self._weight_events = []
        self._event_log = []
        self._pending_orders = {}
        self._last_result = None
        self._tick_counts = {sym: 0 for sym in self._symbols}
        self._bar_counts = {sym: 0 for sym in self._symbols}
        self._wall_start_ts = time.perf_counter()
        self._total_ticks_target = 0
        for loader in self.data_loaders.values():
            self._total_ticks_target += self._estimate_loader_rows(loader, start_time, end_time)
        self._latest_candles = {}
        self._latest_prices = {}
        self._position = _MultiPosition()
        self._start_time = None
        self._end_time = None

        total_bars = 0
        for symbol, candle in self._merge_bars(start_time, end_time):
            if self._start_time is None:
                self._start_time = candle.timestamp
            self._end_time = candle.timestamp

            self._tick_counts[symbol] += 1
            self._bar_counts[symbol] += 1
            total_bars += 1

            self._latest_prices[symbol] = candle.open
            self._execute_pending_order(symbol, candle.open, candle.timestamp)
            self._liquidate_if_needed_in_bar(symbol, candle)

            self._latest_prices[symbol] = candle.close
            self._latest_candles[symbol] = candle
            self._execute_strategy(symbol, candle, candle.timestamp)

            unrealized = self._position.unrealized_pnl(self._latest_prices)
            self._equity_points.append(self._capital + unrealized)
            self._equity_timestamps.append(candle.timestamp)

            if total_bars % 10000 == 0:
                self._print_progress(total_bars, unit="bars")

        elapsed = time.perf_counter() - self._wall_start_ts
        self._logger.info("[PortfolioBars] Completed! Bars: %s, Symbols: %s", f"{total_bars:,}", len(self._symbols))
        self._logger.info("[PortfolioBars] Completed in %.2fs", elapsed)

        for sym in list(self._position.all_symbols):
            price = self._latest_prices.get(sym, 0)
            if price > 0:
                close_qty = self._position.get_qty(sym)
                pnl = self._position.close(sym, price, self._end_time or datetime.now())
                fee = price * close_qty * self.taker_fee_rate
                self._capital += pnl - fee
                self._trade_log.append({
                    "timestamp": self._end_time,
                    "symbol": sym,
                    "action": "CLOSE_FINAL",
                    "price": price,
                    "pnl": pnl,
                    "fee": fee,
                })

        self._equity_points.append(self._capital)
        if self._end_time is not None:
            self._equity_timestamps.append(self._end_time)

        self._last_result = self._compute_result()
        return self._last_result

    def _print_progress(self, total_ticks: int, *, unit: str = "ticks") -> None:
        """진행 상황 로그"""
        elapsed = time.perf_counter() - self._wall_start_ts
        speed = total_ticks / elapsed if elapsed > 0 else 0.0

        if self._total_ticks_target:
            pct = min(100.0, total_ticks / self._total_ticks_target * 100)
            remaining = self._total_ticks_target - total_ticks
            eta_sec = remaining / speed if speed > 0 else 0.0
            self._logger.info(
                "[PortfolioTick] Progress: %.2f%% (%s/%s %s) | symbols=%d | speed=%d %s/s | eta=%s",
                pct,
                f"{total_ticks:,}",
                f"{self._total_ticks_target:,}",
                unit,
                len(self._symbols),
                int(speed),
                unit,
                str(timedelta(seconds=int(eta_sec))),
            )
        else:
            self._logger.info(
                "[PortfolioTick] Progress: %s %s | symbols=%d | speed=%d %s/s",
                f"{total_ticks:,}",
                unit,
                len(self._symbols),
                int(speed),
                unit,
            )

    def _compute_result(self) -> PortfolioTickResult:
        """결과 계산"""
        equity_series = pd.Series(
            self._equity_points if self._equity_points else [self.initial_capital]
        )

        total_return = (self._capital - self.initial_capital) / self.initial_capital if self.initial_capital > 0 else 0.0

        # Sharpe
        sharpe = sharpe_daily_annualized(equity_series, timestamps=self._equity_timestamps)

        # Max drawdown
        rolling_max = equity_series.cummax()
        drawdown = (equity_series - rolling_max) / rolling_max
        max_dd = abs(drawdown.min()) if len(drawdown) > 0 else 0.0

        # 거래 통계 (pnl 필드가 있으면 closed trade)
        closed_trades = [t for t in self._trade_log if "pnl" in t]
        winning = len([t for t in closed_trades if t["pnl"] > 0])
        losing = len([t for t in closed_trades if t["pnl"] < 0])

        return PortfolioTickResult(
            initial_capital=self.initial_capital,
            final_capital=self._capital,
            total_return=total_return,
            sharpe_ratio=sharpe,
            max_drawdown=max_dd,
            total_trades=len(closed_trades),
            winning_trades=winning,
            losing_trades=losing,
            equity_curve=equity_series,
            trade_log=self._trade_log,
            tick_counts=self._tick_counts,
            bar_counts=self._bar_counts,
        )

    def save_report(self, output_dir: str | Path) -> Path:
        """Persist the standard alpha artifact set into ``output_dir``."""
        if self._last_result is None:
            raise RuntimeError("run() must complete before save_report()")

        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        result = self._last_result
        generated_at = datetime.now()

        equity_timestamps = list(self._equity_timestamps[: len(self._equity_points)])
        while len(equity_timestamps) < len(self._equity_points):
            equity_timestamps.append(self._end_time)
        equity_df = pd.DataFrame({
            "timestamp": equity_timestamps,
            "equity": self._equity_points,
        })
        if equity_df.empty:
            equity_df = pd.DataFrame(columns=["timestamp", "equity"])

        trades_df = pd.DataFrame(self._trade_log)
        if trades_df.empty:
            trades_df = pd.DataFrame(
                columns=["timestamp", "symbol", "action", "price", "quantity", "pnl", "fee"]
            )

        weights_df = pd.DataFrame(self._weight_events)
        if weights_df.empty:
            weights_df = pd.DataFrame(
                columns=[
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
                ]
            )

        per_symbol = result.get_symbol_breakdown()
        metrics = {
            "artifact_version": 2,
            "run_type": "backtest",
            "strategy_class": self.strategy.__class__.__name__,
            "strategy_source": "strategy_source.py",
            "alpha_id": self._alpha_id(),
            "symbols": self._symbols,
            "bar_type": self.bar_type.value,
            "bar_size": self.bar_size,
            "initial_capital": result.initial_capital,
            "final_capital": result.final_capital,
            "started_at": self._start_time.isoformat() if self._start_time else None,
            "ended_at": self._end_time.isoformat() if self._end_time else None,
            "generated_at": generated_at.isoformat(),
            "tick_counts": result.tick_counts,
            "bar_counts": result.bar_counts,
            "profit_factor": result.profit_factor,
            "total_return": result.total_return,
            "max_drawdown": -result.max_drawdown,
            "total_trades": result.total_trades,
            "win_rate": result.win_rate,
            "sharpe": result.sharpe_ratio,
            "per_symbol": per_symbol,
            "validation_flags": [],
        }

        (out / "metrics.json").write_text(json.dumps(metrics, indent=2, default=str))
        (out / "backtest_report.md").write_text(result.summary())
        equity_df.to_parquet(out / "equity_curve.parquet", index=False)
        trades_df.to_parquet(out / "trades.parquet", index=False)
        weights_df.to_parquet(out / "weights.parquet", index=False)
        self._snapshot_strategy_source(out)
        return out

    def _snapshot_strategy_source(self, output_dir: Path) -> None:
        try:
            src = Path(inspect.getfile(self.strategy.__class__))
        except (TypeError, OSError):
            src = None

        if src is not None and src.exists():
            shutil.copy2(src, output_dir / "strategy_source.py")
        else:
            (output_dir / "strategy_source.py").write_text(
                f"# source unavailable for {self.strategy.__class__.__name__}\n"
            )

        try:
            git_head = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=Path(__file__).resolve().parents[3],
                capture_output=True,
                text=True,
                timeout=3,
            ).stdout.strip()
        except Exception:
            git_head = ""

        metrics_path = output_dir / "metrics.json"
        try:
            metrics = json.loads(metrics_path.read_text())
            metrics["source_original_path"] = str(src) if src is not None else ""
            metrics["git_head"] = git_head
            metrics_path.write_text(json.dumps(metrics, indent=2, default=str))
        except Exception:
            pass
