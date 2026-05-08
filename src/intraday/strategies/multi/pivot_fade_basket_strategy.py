"""Daily pivot-point fade across full basket.

Distinct cell from pivot_fade_single_btc (universe=single → basket_full).
"""
from __future__ import annotations

from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "raw",
    "horizon": "session",
    "universe": "basket_full",
    "exit": "signal_flip",
    "idea_family": "pivot_fade",
}
SOURCE_NOTES: list[str] = ["research/notes/pivot_fade.md"]


class PivotFadeBasketStrategy:
    def __init__(
        self,
        symbols: list[str],
        max_weight: float = 0.13,
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")
        self.symbols = [s.upper() for s in symbols]
        self.max_weight = max(0.0, min(1.0, float(max_weight)))

        self._cur_day: int | None = None
        self._cur_h: dict[str, float | None] = {s: None for s in self.symbols}
        self._cur_l: dict[str, float | None] = {s: None for s in self.symbols}
        self._cur_c: dict[str, float | None] = {s: None for s in self.symbols}
        self._prev_h: dict[str, float | None] = {s: None for s in self.symbols}
        self._prev_l: dict[str, float | None] = {s: None for s in self.symbols}
        self._prev_c: dict[str, float | None] = {s: None for s in self.symbols}

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
        ts = state.timestamp
        day = ts.toordinal()

        if self._cur_day is None or day != self._cur_day:
            for s in self.symbols:
                if self._cur_h[s] is not None and self._cur_l[s] is not None and self._cur_c[s] is not None:
                    self._prev_h[s] = self._cur_h[s]
                    self._prev_l[s] = self._cur_l[s]
                    self._prev_c[s] = self._cur_c[s]
                self._cur_h[s] = None
                self._cur_l[s] = None
                self._cur_c[s] = None
            self._cur_day = day

        for s in self.symbols:
            d = state.panel.get(s)
            if not d:
                continue
            close = d.get("close")
            high = d.get("high", close)
            low = d.get("low", close)
            if close is not None:
                self._cur_c[s] = float(close)
            if high is not None:
                self._cur_h[s] = high if self._cur_h[s] is None else max(self._cur_h[s], float(high))
            if low is not None:
                self._cur_l[s] = low if self._cur_l[s] is None else min(self._cur_l[s], float(low))

        orders: dict[str, Order | None] = {s: None for s in self.symbols}
        for s in self.symbols:
            ph = self._prev_h[s]
            pl = self._prev_l[s]
            pc = self._prev_c[s]
            cc = self._cur_c[s]
            if ph is None or pl is None or pc is None or cc is None:
                continue
            pp = (ph + pl + pc) / 3.0
            r1 = 2 * pp - pl
            s1 = 2 * pp - ph
            cur = self._current_side(state, s)
            if cc > r1:
                if cur != "SHORT":
                    orders[s] = Order(
                        side=Side.SELL, quantity=0.0,
                        weight=self.max_weight, order_type=OrderType.MARKET,
                    )
            elif cc < s1:
                if cur != "LONG":
                    orders[s] = Order(
                        side=Side.BUY, quantity=0.0,
                        weight=self.max_weight, order_type=OrderType.MARKET,
                    )

        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
