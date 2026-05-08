"""Per-symbol return-burst reversal at 4h horizon.

For each symbol, compute z = (last 30m return) / (4h-rolling sigma of 30m returns).
When |z| > entry_z, take the opposite side. Hold for hold_bars then close.

Distinct from is_006/is_007 (hourly, neutral_zone exit) by horizon and exit.
"""
from __future__ import annotations

from collections import deque
from statistics import pstdev
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "z_score",
    "horizon": "intraday",
    "universe": "basket_full",
    "exit": "time_stop",
    "idea_family": "ts_burst_revert",
}
SOURCE_NOTES: list[str] = ["research/notes/ts_burst_revert.md"]


class TsBurstRevertStrategy:
    def __init__(
        self,
        symbols: list[str],
        burst_bars: int = 30,
        sigma_bars: int = 240,
        hold_bars: int = 240,
        rebalance_bars: int = 30,
        entry_z: float = 2.0,
        max_weight: float = 0.13,
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")
        self.symbols = [s.upper() for s in symbols]
        self.burst_bars = max(2, int(burst_bars))
        self.sigma_bars = max(self.burst_bars + 5, int(sigma_bars))
        self.hold_bars = max(1, int(hold_bars))
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.entry_z = float(entry_z)
        self.max_weight = max(0.0, min(1.0, float(max_weight)))

        self._closes: dict[str, deque[float]] = {
            s: deque(maxlen=self.sigma_bars + self.burst_bars + 5)
            for s in self.symbols
        }
        self._held: dict[str, int] = {s: 0 for s in self.symbols}
        self._bar_count = 0

    def _z(self, s: str) -> float | None:
        closes = list(self._closes[s])
        n_needed = self.sigma_bars + self.burst_bars + 1
        if len(closes) < n_needed:
            return None
        rets = []
        for i in range(self.sigma_bars):
            prev = closes[-n_needed + i]
            cur = closes[-n_needed + i + self.burst_bars]
            if prev > 0:
                rets.append((cur - prev) / prev)
        if len(rets) < 5:
            return None
        sigma = pstdev(rets) or 1e-9
        old = closes[-self.burst_bars - 1]
        recent = closes[-1]
        if old <= 0:
            return None
        burst = (recent - old) / old
        return burst / sigma

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
            if close is not None and close > 0:
                self._closes[s].append(float(close))

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

            z = self._z(s)
            if z is None:
                continue
            if z > self.entry_z:
                orders[s] = Order(
                    side=Side.SELL, quantity=0.0,
                    weight=self.max_weight, order_type=OrderType.MARKET,
                )
                self._held[s] = 1
            elif z < -self.entry_z:
                orders[s] = Order(
                    side=Side.BUY, quantity=0.0,
                    weight=self.max_weight, order_type=OrderType.MARKET,
                )
                self._held[s] = 1

        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
