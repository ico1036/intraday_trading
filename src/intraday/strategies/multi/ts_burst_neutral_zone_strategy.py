"""Per-symbol return-burst reversal with neutral-zone exit (cell variant).

Same idea family as is_020 (ts_burst_revert intraday) but exit on
|z| < exit_z instead of time-stop. Cell exit value differs.
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
    "exit": "neutral_zone",
    "idea_family": "ts_burst_revert",
}
SOURCE_NOTES: list[str] = ["research/notes/ts_burst_revert.md"]


class TsBurstNeutralZoneStrategy:
    def __init__(
        self,
        symbols: list[str],
        burst_bars: int = 60,         # 1h
        sigma_bars: int = 480,        # 8h
        rebalance_bars: int = 60,     # 1h
        entry_z: float = 1.5,
        exit_z: float = 0.3,
        max_weight: float = 0.13,
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")
        self.symbols = [s.upper() for s in symbols]
        self.burst_bars = max(2, int(burst_bars))
        self.sigma_bars = max(self.burst_bars + 5, int(sigma_bars))
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.entry_z = float(entry_z)
        self.exit_z = float(exit_z)
        self.max_weight = max(0.0, min(1.0, float(max_weight)))

        self._closes: dict[str, deque[float]] = {
            s: deque(maxlen=self.sigma_bars + self.burst_bars + 5)
            for s in self.symbols
        }
        self._bar_count = 0

    def _z(self, s: str) -> float | None:
        closes = list(self._closes[s])
        n_needed = self.sigma_bars + self.burst_bars + 1
        if len(closes) < n_needed:
            return None
        rets = []
        for i in range(self.sigma_bars):
            p = closes[-n_needed + i]
            n = closes[-n_needed + i + self.burst_bars]
            if p > 0:
                rets.append((n - p) / p)
        if len(rets) < 5:
            return None
        sigma = pstdev(rets) or 1e-9
        old = closes[-self.burst_bars - 1]
        cur = closes[-1]
        if old <= 0:
            return None
        return ((cur - old) / old) / sigma

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

        orders: dict[str, Order | None] = {}
        for s in self.symbols:
            cur = self._current_side(state, s)
            z = self._z(s)
            if z is None:
                orders[s] = None
                continue
            # FADE: positive burst → SHORT
            if z > self.entry_z:
                orders[s] = (
                    None
                    if cur == "SHORT"
                    else Order(
                        side=Side.SELL, quantity=0.0,
                        weight=self.max_weight, order_type=OrderType.MARKET,
                    )
                )
            elif z < -self.entry_z:
                orders[s] = (
                    None
                    if cur == "LONG"
                    else Order(
                        side=Side.BUY, quantity=0.0,
                        weight=self.max_weight, order_type=OrderType.MARKET,
                    )
                )
            elif abs(z) < self.exit_z:
                if cur == "LONG":
                    orders[s] = Order(side=Side.SELL, quantity=0.0, order_type=OrderType.MARKET)
                elif cur == "SHORT":
                    orders[s] = Order(side=Side.BUY, quantity=0.0, order_type=OrderType.MARKET)
                else:
                    orders[s] = None
            else:
                orders[s] = None

        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
