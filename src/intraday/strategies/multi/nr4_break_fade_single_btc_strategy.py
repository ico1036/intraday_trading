"""NR4-break fade single BTC."""
from __future__ import annotations

from collections import deque
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "raw",
    "horizon": "intraday",
    "universe": "single",
    "exit": "signal_flip",
    "idea_family": "nr4_break_fade",
}
SOURCE_NOTES: list[str] = ["research/notes/nr4_break_fade.md"]


class Nr4BreakFadeSingleBtcStrategy:
    def __init__(
        self,
        symbols: list[str],
        target: str = "BTCUSDT",
        n: int = 4,
        max_weight: float = 0.5,
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")
        self.symbols = [s.upper() for s in symbols]
        self.target = target.upper()
        if self.target not in self.symbols:
            raise ValueError(f"target {self.target} not in symbols")
        self.n = max(2, int(n))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))

        self._highs: deque[float] = deque(maxlen=self.n + 5)
        self._lows: deque[float] = deque(maxlen=self.n + 5)
        self._nr_high: float | None = None
        self._nr_low: float | None = None

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
        d = state.panel.get(self.target)
        if d:
            close = d.get("close")
            high = d.get("high", close)
            low = d.get("low", close)
            if close is not None and high is not None and low is not None:
                self._highs.append(float(high))
                self._lows.append(float(low))

        highs = list(self._highs)
        lows = list(self._lows)
        if len(highs) >= self.n + 1:
            ranges = [highs[i] - lows[i] for i in range(-self.n - 1, -1)]
            prev_range = highs[-2] - lows[-2]
            if prev_range == min(ranges):
                self._nr_high = highs[-2]
                self._nr_low = lows[-2]

        if not d or d.get("close") is None or self._nr_high is None or self._nr_low is None:
            return None
        close = float(d["close"])
        cur = self._current_side(state)
        orders: dict[str, Order | None] = {s: None for s in self.symbols}
        if close > self._nr_high:
            if cur != "SHORT":
                orders[self.target] = Order(
                    side=Side.SELL, quantity=0.0,
                    weight=self.max_weight, order_type=OrderType.MARKET,
                )
        elif close < self._nr_low:
            if cur != "LONG":
                orders[self.target] = Order(
                    side=Side.BUY, quantity=0.0,
                    weight=self.max_weight, order_type=OrderType.MARKET,
                )
        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
