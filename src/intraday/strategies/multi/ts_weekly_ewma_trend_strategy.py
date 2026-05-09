"""is_010_ts_weekly_ewma_trend — per-symbol EWMA-residual weekly trend.

Cell-distinct from is_005 by transform=ewma_residual (vs z_score). The signal
is the residual between a fast EWMA (1 day) and a slow EWMA (1 week)
normalized by the slow EWMA. Same weekly rebalance and signal_flip exit.
"""
from __future__ import annotations

import math
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "ewma_residual",
    "horizon": "multi_day",
    "universe": "basket_full",
    "exit": "signal_flip",
    "idea_family": "ts_weekly_ewma_trend",
}
SOURCE_NOTES: list[str] = ["research/notes/ts_weekly_ewma_trend.md"]


class TsWeeklyEwmaTrendStrategy:
    def __init__(
        self,
        symbols: list[str],
        fast_period_bars: int = 1440,
        slow_period_bars: int = 10080,
        rebalance_bars: int = 10080,
        entry_threshold: float = 0.005,
        exit_threshold: float = 0.001,
        max_weight: float = 0.14,
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")
        if slow_period_bars <= fast_period_bars:
            raise ValueError("slow_period_bars must exceed fast_period_bars")

        self.symbols = [s.upper() for s in symbols]
        self.fast_period = max(2, int(fast_period_bars))
        self.slow_period = max(self.fast_period + 1, int(slow_period_bars))
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.entry_threshold = float(entry_threshold)
        self.exit_threshold = float(exit_threshold)
        self.max_weight = max(0.0, min(1.0, float(max_weight)))

        # EWMA smoothing factors: alpha = 2/(N+1)
        self._alpha_fast = 2.0 / (self.fast_period + 1)
        self._alpha_slow = 2.0 / (self.slow_period + 1)

        self._fast_ewma: dict[str, float | None] = {s: None for s in self.symbols}
        self._slow_ewma: dict[str, float | None] = {s: None for s in self.symbols}
        self._update_count: dict[str, int] = {s: 0 for s in self.symbols}
        self._bar_count = 0

    def _residual(self, symbol: str) -> float | None:
        slow = self._slow_ewma[symbol]
        fast = self._fast_ewma[symbol]
        if slow is None or fast is None or slow <= 0:
            return None
        if self._update_count[symbol] < self.slow_period:
            return None
        return (fast - slow) / slow

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
        if state.panel is None:
            return None

        for symbol in self.symbols:
            data = state.panel.get(symbol)
            if not data:
                continue
            close = data.get("close")
            if close is None or float(close) <= 0:
                continue
            x = float(close)
            f = self._fast_ewma[symbol]
            s = self._slow_ewma[symbol]
            self._fast_ewma[symbol] = x if f is None else self._alpha_fast * x + (1 - self._alpha_fast) * f
            self._slow_ewma[symbol] = x if s is None else self._alpha_slow * x + (1 - self._alpha_slow) * s
            self._update_count[symbol] += 1

        self._bar_count += 1
        if self._bar_count % self.rebalance_bars != 0:
            return None

        targets: dict[str, str] = {}
        residuals: dict[str, float] = {}
        for symbol in self.symbols:
            r = self._residual(symbol)
            if r is None or not math.isfinite(r):
                continue
            residuals[symbol] = r
            if r > self.entry_threshold:
                targets[symbol] = "LONG"
            elif r < -self.entry_threshold:
                targets[symbol] = "SHORT"

        n_active = len(targets)
        per_leg_weight = (
            min(self.max_weight, 1.0 / n_active) if n_active > 0 else 0.0
        )

        orders: dict[str, Order | None] = {}
        any_change = False
        for symbol in self.symbols:
            current_side = self._position_side(state, symbol)
            target = targets.get(symbol)
            r = residuals.get(symbol)

            if target == "LONG":
                if current_side != "LONG":
                    orders[symbol] = Order(
                        side=Side.BUY,
                        quantity=0.0,
                        weight=per_leg_weight,
                        order_type=OrderType.MARKET,
                    )
                    any_change = True
                else:
                    orders[symbol] = None
            elif target == "SHORT":
                if current_side != "SHORT":
                    orders[symbol] = Order(
                        side=Side.SELL,
                        quantity=0.0,
                        weight=per_leg_weight,
                        order_type=OrderType.MARKET,
                    )
                    any_change = True
                else:
                    orders[symbol] = None
            elif r is not None and abs(r) < self.exit_threshold and current_side is not None:
                orders[symbol] = self._close_order(current_side)
                any_change = True
            else:
                orders[symbol] = None

        return PortfolioOrder(orders=orders) if any_change else None
