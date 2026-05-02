"""Unified portfolio alpha template.

Copy this file when creating a generated alpha. Do not create separate
single-symbol templates: ``symbols=["BTCUSDT"]`` is the single-coin case,
and ``symbols=[...]`` with length > 1 is the multi-coin case.

Agent edit surface:
    - class name
    - ``__init__`` parameters
    - ``_score_symbol``
    - optional target construction in ``generate_order``

Infrastructure that must stay outside strategy files:
    - data loading
    - candle/tick synchronization
    - execution simulation
    - fee/PnL/equity calculations
    - artifact writing, especially ``weights.parquet``
"""
from __future__ import annotations

from collections import deque
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


class AlphaTemplateStrategy:
    """Minimal long/short alpha that works for one or many symbols.

    This example scores each symbol by lookback return. Generated alphas should
    replace ``_score_symbol`` with the intended signal while preserving the
    contract: return ``PortfolioOrder`` with target weights.
    """

    def __init__(
        self,
        symbols: list[str],
        lookback_bars: int = 24,
        rebalance_bars: int = 1,
        entry_threshold: float = 0.003,
        exit_threshold: float = 0.001,
        max_weight: float = 0.3,
        mode: str = "momentum",
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")

        self.symbols = [s.upper() for s in symbols]
        self.lookback_bars = max(2, int(lookback_bars))
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.entry_threshold = float(entry_threshold)
        self.exit_threshold = float(exit_threshold)
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self.mode = mode

        self._prices: dict[str, deque[float]] = {
            symbol: deque(maxlen=self.lookback_bars + 1)
            for symbol in self.symbols
        }
        self._bar_count = 0

    def _score_symbol(self, symbol: str) -> float | None:
        """Return signed alpha score for one symbol.

        Positive means target long, negative means target short. ``None``
        means not enough information yet.
        """
        prices = self._prices[symbol]
        if len(prices) < self.lookback_bars + 1:
            return None

        start = prices[0]
        end = prices[-1]
        if start <= 0:
            return None

        score = (end - start) / start
        if self.mode == "reversal":
            score = -score
        return score

    def _position_side(self, state: MarketState, symbol: str) -> str | None:
        if not state.positions:
            return None
        info = state.positions.get(symbol)
        if not info:
            return None
        side = info.get("side")
        return side if side in {"LONG", "SHORT"} else None

    def _close_order(self, side: str | None) -> Order | None:
        if side == "LONG":
            return Order(side=Side.SELL, quantity=0.0, order_type=OrderType.MARKET)
        if side == "SHORT":
            return Order(side=Side.BUY, quantity=0.0, order_type=OrderType.MARKET)
        return None

    def generate_order(self, state: MarketState) -> PortfolioOrder | None:
        """Return target-weight orders for the current panel state."""
        if state.panel is None:
            return None

        for symbol in self.symbols:
            data = state.panel.get(symbol)
            if not data:
                continue
            close = data.get("close")
            if close is not None and close > 0:
                self._prices[symbol].append(float(close))

        self._bar_count += 1
        if self._bar_count % self.rebalance_bars != 0:
            return None

        orders: dict[str, Order | None] = {}
        for symbol in self.symbols:
            score = self._score_symbol(symbol)
            current_side = self._position_side(state, symbol)

            if score is None:
                orders[symbol] = None
                continue

            if score > self.entry_threshold:
                orders[symbol] = (
                    None
                    if current_side == "LONG"
                    else Order(
                        side=Side.BUY,
                        quantity=0.0,
                        weight=self.max_weight,
                        order_type=OrderType.MARKET,
                    )
                )
            elif score < -self.entry_threshold:
                orders[symbol] = (
                    None
                    if current_side == "SHORT"
                    else Order(
                        side=Side.SELL,
                        quantity=0.0,
                        weight=self.max_weight,
                        order_type=OrderType.MARKET,
                    )
                )
            elif abs(score) < self.exit_threshold:
                orders[symbol] = self._close_order(current_side)
            else:
                orders[symbol] = None

        active = {symbol: order for symbol, order in orders.items() if order is not None}
        return PortfolioOrder(orders=orders) if active else None
