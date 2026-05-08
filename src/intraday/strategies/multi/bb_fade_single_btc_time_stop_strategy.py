"""BB-fade single BTC with TIME_STOP exit (cell variant).

Cell exit value differs from is_044 (signal_flip → time_stop).
"""
from __future__ import annotations

from collections import deque
from statistics import mean, pstdev
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "z_score",
    "horizon": "intraday",
    "universe": "single",
    "exit": "time_stop",
    "idea_family": "bb_band_fade",
}
SOURCE_NOTES: list[str] = ["research/notes/bb_band_fade.md"]


class BbFadeSingleBtcTimeStopStrategy:
    def __init__(
        self,
        symbols: list[str],
        target: str = "BTCUSDT",
        window: int = 480,
        k: float = 2.0,
        hold_bars: int = 240,
        rebalance_bars: int = 60,
        max_weight: float = 0.5,
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")
        self.symbols = [s.upper() for s in symbols]
        self.target = target.upper()
        if self.target not in self.symbols:
            raise ValueError(f"target {self.target} not in symbols")
        self.window = max(20, int(window))
        self.k = float(k)
        self.hold_bars = max(1, int(hold_bars))
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))

        self._closes: deque[float] = deque(maxlen=self.window + 5)
        self._held: int = 0
        self._bar_count = 0

    def _current_side(self, state: MarketState) -> str | None:
        if not state.positions:
            return None
        info = state.positions.get(self.target)
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
        d = state.panel.get(self.target)
        if d:
            close = d.get("close")
            if close is not None and close > 0:
                self._closes.append(float(close))

        if self._current_side(state) is not None:
            self._held += 1
        else:
            self._held = 0

        self._bar_count += 1
        if self._bar_count % self.rebalance_bars != 0:
            return None
        if len(self._closes) < self.window:
            return None

        cur = self._current_side(state)
        orders: dict[str, Order | None] = {s: None for s in self.symbols}

        if cur is not None and self._held >= self.hold_bars:
            o = self._close_for_side(cur)
            if o is not None:
                orders[self.target] = o
            self._held = 0
            active = {s: o for s, o in orders.items() if o is not None}
            return PortfolioOrder(orders=orders) if active else None

        if cur is not None:
            return None

        seg = list(self._closes)[-self.window:]
        mu = mean(seg)
        sd = pstdev(seg) or 1e-12
        upper = mu + self.k * sd
        lower = mu - self.k * sd
        close = self._closes[-1]
        if close > upper:
            orders[self.target] = Order(
                side=Side.SELL, quantity=0.0,
                weight=self.max_weight, order_type=OrderType.MARKET,
            )
            self._held = 1
        elif close < lower:
            orders[self.target] = Order(
                side=Side.BUY, quantity=0.0,
                weight=self.max_weight, order_type=OrderType.MARKET,
            )
            self._held = 1

        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
