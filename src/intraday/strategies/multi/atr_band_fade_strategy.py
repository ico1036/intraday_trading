"""ATR-band fade with signal-flip exit.

For each symbol, compute rolling ATR over N bars. When |bar_return| >
k·ATR/close, fade the direction. Hold until opposite trigger.
"""
from __future__ import annotations

from collections import deque
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "z_score",
    "horizon": "intraday",
    "universe": "basket_full",
    "exit": "signal_flip",
    "idea_family": "atr_band_fade",
}
SOURCE_NOTES: list[str] = ["research/notes/atr_band_fade.md"]


class AtrBandFadeStrategy:
    def __init__(
        self,
        symbols: list[str],
        atr_window: int = 240,    # 4h
        k: float = 3.0,
        rebalance_bars: int = 1,
        max_weight: float = 0.13,
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")
        self.symbols = [s.upper() for s in symbols]
        self.atr_window = max(10, int(atr_window))
        self.k = float(k)
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))

        self._highs: dict[str, deque[float]] = {
            s: deque(maxlen=self.atr_window + 5) for s in self.symbols
        }
        self._lows: dict[str, deque[float]] = {
            s: deque(maxlen=self.atr_window + 5) for s in self.symbols
        }
        self._closes: dict[str, deque[float]] = {
            s: deque(maxlen=self.atr_window + 5) for s in self.symbols
        }
        self._bar_count = 0

    def _atr(self, s: str) -> float | None:
        h = list(self._highs[s])
        lo = list(self._lows[s])
        c = list(self._closes[s])
        if len(c) < self.atr_window + 1:
            return None
        trs = []
        for i in range(-self.atr_window, 0):
            high = h[i]
            low = lo[i]
            prev_close = c[i - 1]
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            trs.append(tr)
        return sum(trs) / len(trs)

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
            self._closes[s].append(float(close))
            self._highs[s].append(float(high))
            self._lows[s].append(float(low))

        self._bar_count += 1
        if self._bar_count % self.rebalance_bars != 0:
            return None

        orders: dict[str, Order | None] = {s: None for s in self.symbols}
        for s in self.symbols:
            atr = self._atr(s)
            if atr is None or atr <= 0:
                continue
            c = list(self._closes[s])
            if len(c) < 2:
                continue
            bar_move = c[-1] - c[-2]
            threshold = self.k * atr
            cur = self._current_side(state, s)
            if bar_move > threshold:
                if cur != "SHORT":
                    orders[s] = Order(
                        side=Side.SELL, quantity=0.0,
                        weight=self.max_weight, order_type=OrderType.MARKET,
                    )
            elif bar_move < -threshold:
                if cur != "LONG":
                    orders[s] = Order(
                        side=Side.BUY, quantity=0.0,
                        weight=self.max_weight, order_type=OrderType.MARKET,
                    )

        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
