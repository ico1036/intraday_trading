"""is_008_ts_weekly_long_only — long-only weekly TS momentum with time-stop.

Cell-distinct from is_005 by exit (time_stop vs signal_flip) and idea_family.
Drops the SHORT leg entirely; on each weekly rebalance, any symbol whose
trailing 7-day log return exceeds entry_z (vs its own 4-week history) is
entered LONG and held for hold_bars regardless of subsequent signal flips.
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
    "exit": "time_stop",
    "idea_family": "ts_weekly_long_only",
}
SOURCE_NOTES: list[str] = ["research/notes/ts_weekly_long_only.md"]


class TsWeeklyLongOnlyStrategy:
    def __init__(
        self,
        symbols: list[str],
        lookback_bars: int = 10080,
        history_window: int = 4,
        rebalance_bars: int = 10080,
        hold_bars: int = 10080,
        entry_z: float = 0.5,
        max_weight: float = 0.14,
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")

        self.symbols = [s.upper() for s in symbols]
        self.lookback_bars = max(2, int(lookback_bars))
        self.history_window = max(3, int(history_window))
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.hold_bars = max(1, int(hold_bars))
        self.entry_z = float(entry_z)
        self.max_weight = max(0.0, min(1.0, float(max_weight)))

        self._closes: dict[str, deque[float]] = {
            s: deque(maxlen=self.lookback_bars + 1) for s in self.symbols
        }
        self._return_history: dict[str, deque[float]] = {
            s: deque(maxlen=self.history_window) for s in self.symbols
        }
        self._bar_count = 0
        self._open_at: dict[str, int] = {}  # symbol -> bar_count when opened

    def _current_return(self, symbol: str) -> float | None:
        prices = self._closes[symbol]
        if len(prices) < self.lookback_bars + 1:
            return None
        start, end = prices[0], prices[-1]
        if start <= 0 or end <= 0:
            return None
        return math.log(end / start)

    def _z_for(self, symbol: str) -> float | None:
        cur = self._current_return(symbol)
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

        # Process time-stops every bar (so positions exit even between rebalances)
        orders: dict[str, Order | None] = {}
        any_change = False
        for symbol in self.symbols:
            current_side = self._position_side(state, symbol)
            opened = self._open_at.get(symbol)
            if current_side == "LONG" and opened is not None:
                if self._bar_count - opened >= self.hold_bars:
                    orders[symbol] = Order(
                        side=Side.SELL, quantity=0.0, order_type=OrderType.MARKET
                    )
                    self._open_at.pop(symbol, None)
                    any_change = True

        # Only consider new entries on rebalance ticks
        if self._bar_count % self.rebalance_bars == 0:
            for symbol in self.symbols:
                r = self._current_return(symbol)
                if r is not None and math.isfinite(r):
                    self._return_history[symbol].append(r)

            # Determine LONG candidates
            candidates: dict[str, float] = {}
            for symbol in self.symbols:
                z = self._z_for(symbol)
                if z is not None and z > self.entry_z:
                    candidates[symbol] = z

            n_active = len(candidates)
            per_leg_weight = (
                min(self.max_weight, 1.0 / n_active) if n_active > 0 else 0.0
            )

            for symbol in candidates:
                current_side = self._position_side(state, symbol)
                # If we just decided to time-stop above, current_side may still
                # read LONG in this state; we still want to issue a fresh entry
                # only when no live position remains. Skip entry while LONG.
                if current_side == "LONG" and symbol not in orders:
                    continue
                # Open LONG
                orders[symbol] = Order(
                    side=Side.BUY,
                    quantity=0.0,
                    weight=per_leg_weight,
                    order_type=OrderType.MARKET,
                )
                self._open_at[symbol] = self._bar_count
                any_change = True

        return PortfolioOrder(orders=orders) if any_change else None
