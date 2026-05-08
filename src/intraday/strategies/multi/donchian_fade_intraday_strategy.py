"""Donchian channel fade at intraday horizon (cell variant).

Same family as is_027 (donchian_fade multi_day) but with a shorter intraday
window. Cell horizon value differs.
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
    "idea_family": "donchian_fade",
}
SOURCE_NOTES: list[str] = ["research/notes/donchian_fade.md"]


class DonchianFadeIntradayStrategy:
    def __init__(
        self,
        symbols: list[str],
        channel_bars: int = 480,   # 8h
        max_weight: float = 0.13,
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")
        self.symbols = [s.upper() for s in symbols]
        self.channel_bars = max(60, int(channel_bars))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))

        self._highs: dict[str, deque[float]] = {
            s: deque(maxlen=self.channel_bars + 5) for s in self.symbols
        }
        self._lows: dict[str, deque[float]] = {
            s: deque(maxlen=self.channel_bars + 5) for s in self.symbols
        }

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

        orders: dict[str, Order | None] = {s: None for s in self.symbols}
        for s in self.symbols:
            highs = list(self._highs[s])
            lows = list(self._lows[s])
            if len(highs) < self.channel_bars + 1:
                continue
            d_high = max(highs[-self.channel_bars - 1:-1])
            d_low = min(lows[-self.channel_bars - 1:-1])
            data = state.panel.get(s)
            if not data or data.get("close") is None:
                continue
            close = float(data["close"])
            cur = self._current_side(state, s)
            if close > d_high:
                if cur != "SHORT":
                    orders[s] = Order(
                        side=Side.SELL, quantity=0.0,
                        weight=self.max_weight, order_type=OrderType.MARKET,
                    )
            elif close < d_low:
                if cur != "LONG":
                    orders[s] = Order(
                        side=Side.BUY, quantity=0.0,
                        weight=self.max_weight, order_type=OrderType.MARKET,
                    )

        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
