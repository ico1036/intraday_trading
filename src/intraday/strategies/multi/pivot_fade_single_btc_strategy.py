"""Daily pivot-point fade applied to BTC single asset.

PP, R1, S1 derived from previous UTC day's HLC. SHORT when close > R1; LONG
when close < S1. Signal_flip exit.
"""
from __future__ import annotations

from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "raw",
    "horizon": "session",
    "universe": "single",
    "exit": "signal_flip",
    "idea_family": "pivot_fade",
}
SOURCE_NOTES: list[str] = ["research/notes/pivot_fade.md"]


class PivotFadeSingleBtcStrategy:
    def __init__(
        self,
        symbols: list[str],
        target: str = "BTCUSDT",
        max_weight: float = 0.5,
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")
        self.symbols = [s.upper() for s in symbols]
        self.target = target.upper()
        if self.target not in self.symbols:
            raise ValueError(f"target {self.target} not in symbols")
        self.max_weight = max(0.0, min(1.0, float(max_weight)))

        # accumulate today's H/L/C and yesterday's HLC
        self._cur_day: int | None = None
        self._cur_high: float | None = None
        self._cur_low: float | None = None
        self._cur_close: float | None = None
        self._prev_h: float | None = None
        self._prev_l: float | None = None
        self._prev_c: float | None = None

    def _current_side(self, state: MarketState) -> str | None:
        if not state.positions:
            return None
        info = state.positions.get(self.target)
        if not info:
            return None
        side = info.get("side")
        return side if side in {"LONG", "SHORT"} else None

    def generate_order(self, state: MarketState) -> PortfolioOrder | None:
        if state.panel is None:
            return None
        ts = state.timestamp
        day = ts.toordinal()
        d = state.panel.get(self.target)

        if self._cur_day is None or day != self._cur_day:
            # rollover: yesterday's accumulated values become prev
            if self._cur_high is not None and self._cur_low is not None and self._cur_close is not None:
                self._prev_h = self._cur_high
                self._prev_l = self._cur_low
                self._prev_c = self._cur_close
            self._cur_day = day
            self._cur_high = None
            self._cur_low = None
            self._cur_close = None

        if d:
            close = d.get("close")
            high = d.get("high", close)
            low = d.get("low", close)
            if close is not None:
                self._cur_close = float(close)
            if high is not None:
                self._cur_high = high if self._cur_high is None else max(self._cur_high, float(high))
            if low is not None:
                self._cur_low = low if self._cur_low is None else min(self._cur_low, float(low))

        if self._prev_h is None or self._prev_l is None or self._prev_c is None:
            return None
        if self._cur_close is None:
            return None

        pp = (self._prev_h + self._prev_l + self._prev_c) / 3.0
        r1 = 2 * pp - self._prev_l
        s1 = 2 * pp - self._prev_h
        close = self._cur_close
        cur = self._current_side(state)

        orders: dict[str, Order | None] = {s: None for s in self.symbols}
        if close > r1:
            if cur != "SHORT":
                orders[self.target] = Order(
                    side=Side.SELL, quantity=0.0,
                    weight=self.max_weight, order_type=OrderType.MARKET,
                )
        elif close < s1:
            if cur != "LONG":
                orders[self.target] = Order(
                    side=Side.BUY, quantity=0.0,
                    weight=self.max_weight, order_type=OrderType.MARKET,
                )

        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
