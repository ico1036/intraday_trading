"""is_004_ts_daily_momentum — per-symbol time-series momentum at daily horizon.

Cell distinct from is_002/is_003 (universe=basket_full, idea_family=
ts_daily_momentum). Each symbol is judged against its own trailing 7-day
distribution of 24h log returns. If today's 24h move is z-score > entry_z
the position is LONG; if < -entry_z the position is SHORT. Rebalanced once
per day to keep round-trip fees small.
"""
from __future__ import annotations

import math
from collections import deque
from statistics import mean, pstdev
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "z_score",
    "horizon": "multi_day",
    "universe": "basket_full",
    "exit": "signal_flip",
    "idea_family": "ts_daily_momentum",
}
SOURCE_NOTES: list[str] = ["research/notes/ts_daily_momentum.md"]


class TsDailyMomentumStrategy:
    def __init__(
        self,
        symbols: list[str],
        lookback_bars: int = 1440,
        history_window: int = 7,
        rebalance_bars: int = 1440,
        entry_z: float = 1.0,
        exit_z: float = 0.3,
        max_weight: float = 0.2,
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")

        self.symbols = [s.upper() for s in symbols]
        self.lookback_bars = max(2, int(lookback_bars))
        self.history_window = max(3, int(history_window))
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.entry_z = float(entry_z)
        self.exit_z = float(exit_z)
        self.max_weight = max(0.0, min(1.0, float(max_weight)))

        self._closes: dict[str, deque[float]] = {
            s: deque(maxlen=self.lookback_bars + 1) for s in self.symbols
        }
        self._return_history: dict[str, deque[float]] = {
            s: deque(maxlen=self.history_window) for s in self.symbols
        }
        self._bar_count = 0

    def _current_24h_return(self, symbol: str) -> float | None:
        prices = self._closes[symbol]
        if len(prices) < self.lookback_bars + 1:
            return None
        start, end = prices[0], prices[-1]
        if start <= 0 or end <= 0:
            return None
        return math.log(end / start)

    def _z_for(self, symbol: str) -> float | None:
        cur = self._current_24h_return(symbol)
        if cur is None:
            return None
        history = self._return_history[symbol]
        if len(history) < self.history_window:
            return None
        sigma = pstdev(history)
        mu = mean(history)
        if sigma <= 0 or not math.isfinite(sigma):
            return None
        return (cur - mu) / sigma

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
            if close is not None and float(close) > 0:
                self._closes[symbol].append(float(close))

        self._bar_count += 1
        if self._bar_count % self.rebalance_bars != 0:
            return None

        # update rolling history of 24h returns once per rebalance
        for symbol in self.symbols:
            r = self._current_24h_return(symbol)
            if r is not None and math.isfinite(r):
                self._return_history[symbol].append(r)

        # First pass: classify signals and count active legs for weight cap.
        targets: dict[str, str] = {}
        zscores: dict[str, float] = {}
        for symbol in self.symbols:
            z = self._z_for(symbol)
            if z is None:
                continue
            zscores[symbol] = z
            if z > self.entry_z:
                targets[symbol] = "LONG"
            elif z < -self.entry_z:
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
            z = zscores.get(symbol)

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
            elif z is not None and abs(z) < self.exit_z and current_side is not None:
                orders[symbol] = self._close_order(current_side)
                any_change = True
            else:
                orders[symbol] = None

        return PortfolioOrder(orders=orders) if any_change else None
