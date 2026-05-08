"""ATR-band fade with TIME_STOP exit (cell variant of is_033).

Same family as is_033 but uses lower k threshold and time_stop exit so the
trigger fires more frequently. Cell exit value differs.
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
    "exit": "time_stop",
    "idea_family": "atr_band_fade",
}
SOURCE_NOTES: list[str] = ["research/notes/atr_band_fade.md"]


class AtrBandFadeTimeStopStrategy:
    def __init__(
        self,
        symbols: list[str],
        atr_window: int = 240,
        k: float = 2.0,
        hold_bars: int = 240,
        rebalance_bars: int = 1,
        max_weight: float = 0.13,
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")
        self.symbols = [s.upper() for s in symbols]
        self.atr_window = max(10, int(atr_window))
        self.k = float(k)
        self.hold_bars = max(1, int(hold_bars))
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
        self._held: dict[str, int] = {s: 0 for s in self.symbols}
        self._bar_count = 0

    def _atr(self, s: str) -> float | None:
        h = list(self._highs[s])
        lo = list(self._lows[s])
        c = list(self._closes[s])
        if len(c) < self.atr_window + 1:
            return None
        trs = []
        for i in range(-self.atr_window, 0):
            tr = max(h[i] - lo[i], abs(h[i] - c[i - 1]), abs(lo[i] - c[i - 1]))
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

    def _close_for_side(self, side: str | None) -> Order | None:
        if side == "LONG":
            return Order(side=Side.SELL, quantity=0.0, order_type=OrderType.MARKET)
        if side == "SHORT":
            return Order(side=Side.BUY, quantity=0.0, order_type=OrderType.MARKET)
        return None

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

        for s in self.symbols:
            cur = self._current_side(state, s)
            if cur is not None:
                self._held[s] += 1
            else:
                self._held[s] = 0

        self._bar_count += 1
        if self._bar_count % self.rebalance_bars != 0:
            return None

        orders: dict[str, Order | None] = {s: None for s in self.symbols}
        for s in self.symbols:
            cur = self._current_side(state, s)
            if cur is not None and self._held[s] >= self.hold_bars:
                orders[s] = self._close_for_side(cur)
                self._held[s] = 0
                continue
            if cur is not None:
                continue
            atr = self._atr(s)
            if atr is None or atr <= 0:
                continue
            c = list(self._closes[s])
            if len(c) < 2:
                continue
            bar_move = c[-1] - c[-2]
            threshold = self.k * atr
            if bar_move > threshold:
                orders[s] = Order(
                    side=Side.SELL, quantity=0.0,
                    weight=self.max_weight, order_type=OrderType.MARKET,
                )
                self._held[s] = 1
            elif bar_move < -threshold:
                orders[s] = Order(
                    side=Side.BUY, quantity=0.0,
                    weight=self.max_weight, order_type=OrderType.MARKET,
                )
                self._held[s] = 1

        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
