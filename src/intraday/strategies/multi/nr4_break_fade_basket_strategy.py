"""NR4-break fade across basket.

When the previous bar is the narrowest of the past 4 bars, mark its
high/low as NR4 boundary. SHORT on close > NR4-high; LONG on close < NR4-low.
Hold until opposite break.
"""
from __future__ import annotations

from collections import deque
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "raw",
    "horizon": "intraday",
    "universe": "basket_full",
    "exit": "signal_flip",
    "idea_family": "nr4_break_fade",
}
SOURCE_NOTES: list[str] = ["research/notes/nr4_break_fade.md"]


class Nr4BreakFadeBasketStrategy:
    def __init__(
        self,
        symbols: list[str],
        n: int = 4,
        max_weight: float = 0.13,
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")
        self.symbols = [s.upper() for s in symbols]
        self.n = max(2, int(n))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))

        self._highs: dict[str, deque[float]] = {
            s: deque(maxlen=self.n + 5) for s in self.symbols
        }
        self._lows: dict[str, deque[float]] = {
            s: deque(maxlen=self.n + 5) for s in self.symbols
        }
        self._nr_high: dict[str, float | None] = {s: None for s in self.symbols}
        self._nr_low: dict[str, float | None] = {s: None for s in self.symbols}

    def _current_side(self, state: MarketState, symbol: str) -> str | None:
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
        for s in self.symbols:
            d = state.panel.get(s)
            if not d:
                continue
            close = d.get("close")
            high = d.get("high", close)
            low = d.get("low", close)
            if close is None or high is None or low is None:
                continue
            self._highs[s].append(float(high))
            self._lows[s].append(float(low))

        # Check NR{n} on previous bar (last appended is current bar)
        for s in self.symbols:
            highs = list(self._highs[s])
            lows = list(self._lows[s])
            if len(highs) < self.n + 1:
                continue
            # last n bars range
            ranges = [highs[i] - lows[i] for i in range(-self.n - 1, -1)]
            prev_range = highs[-2] - lows[-2]
            if prev_range == min(ranges):
                self._nr_high[s] = highs[-2]
                self._nr_low[s] = lows[-2]

        orders: dict[str, Order | None] = {s: None for s in self.symbols}
        for s in self.symbols:
            d = state.panel.get(s)
            if not d:
                continue
            close = d.get("close")
            nh = self._nr_high.get(s)
            nl = self._nr_low.get(s)
            if close is None or nh is None or nl is None:
                continue
            cur = self._current_side(state, s)
            if close > nh:
                if cur != "SHORT":
                    orders[s] = Order(
                        side=Side.SELL, quantity=0.0,
                        weight=self.max_weight, order_type=OrderType.MARKET,
                    )
            elif close < nl:
                if cur != "LONG":
                    orders[s] = Order(
                        side=Side.BUY, quantity=0.0,
                        weight=self.max_weight, order_type=OrderType.MARKET,
                    )

        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
