"""Per-symbol RSI extreme fade with signal-flip exit.

Compute Wilder's 14-period RSI (period configurable). SHORT when RSI > 70,
LONG when RSI < 30; hold until opposite extreme. Hourly rebalance.
"""
from __future__ import annotations

from collections import deque
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "rolling_rank",
    "horizon": "intraday",
    "universe": "basket_full",
    "exit": "signal_flip",
    "idea_family": "rsi_extreme_fade",
}
SOURCE_NOTES: list[str] = ["research/notes/rsi_extreme_fade.md"]


class RsiExtremeFadeStrategy:
    def __init__(
        self,
        symbols: list[str],
        period: int = 240,           # 4h RSI on 1m bars
        upper: float = 70.0,
        lower: float = 30.0,
        rebalance_bars: int = 60,
        max_weight: float = 0.13,
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")
        self.symbols = [s.upper() for s in symbols]
        self.period = max(5, int(period))
        self.upper = float(upper)
        self.lower = float(lower)
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))

        self._closes: dict[str, deque[float]] = {
            s: deque(maxlen=self.period + 5) for s in self.symbols
        }
        self._bar_count = 0

    def _rsi(self, s: str) -> float | None:
        c = list(self._closes[s])
        if len(c) < self.period + 1:
            return None
        gains = []
        losses = []
        for prev, cur in zip(c[-self.period - 1:-1], c[-self.period:]):
            d = cur - prev
            if d > 0:
                gains.append(d)
                losses.append(0.0)
            else:
                gains.append(0.0)
                losses.append(-d)
        if not gains:
            return None
        avg_g = sum(gains) / len(gains)
        avg_l = sum(losses) / len(losses)
        if avg_l == 0:
            return 100.0
        rs = avg_g / avg_l
        return 100.0 - (100.0 / (1.0 + rs))

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
            if close is not None and close > 0:
                self._closes[s].append(float(close))

        self._bar_count += 1
        if self._bar_count % self.rebalance_bars != 0:
            return None

        orders: dict[str, Order | None] = {s: None for s in self.symbols}
        for s in self.symbols:
            r = self._rsi(s)
            if r is None:
                continue
            cur = self._current_side(state, s)
            if r > self.upper:
                if cur != "SHORT":
                    orders[s] = Order(
                        side=Side.SELL, quantity=0.0,
                        weight=self.max_weight, order_type=OrderType.MARKET,
                    )
            elif r < self.lower:
                if cur != "LONG":
                    orders[s] = Order(
                        side=Side.BUY, quantity=0.0,
                        weight=self.max_weight, order_type=OrderType.MARKET,
                    )

        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
