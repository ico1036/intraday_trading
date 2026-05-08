"""Two-bar reversal fade across basket (with magnitude filter)."""
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
    "exit": "signal_flip",
    "idea_family": "two_bar_revert",
}
SOURCE_NOTES: list[str] = ["research/notes/two_bar_reversal_fade.md"]


class TwoBarRevertBasketStrategy:
    def __init__(
        self,
        symbols: list[str],
        n_bars: int = 3,
        sigma_window: int = 240,
        entry_z: float = 2.0,
        rebalance_bars: int = 5,
        max_weight: float = 0.13,
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")
        self.symbols = [s.upper() for s in symbols]
        self.n_bars = max(2, int(n_bars))
        self.sigma_window = max(20, int(sigma_window))
        self.entry_z = float(entry_z)
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))

        self._closes: dict[str, deque[float]] = {
            s: deque(maxlen=self.sigma_window + self.n_bars + 5) for s in self.symbols
        }
        self._bar_count = 0

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
            closes = list(self._closes[s])
            if len(closes) < self.sigma_window + self.n_bars:
                continue
            # check N consecutive same-direction bars
            recent = closes[-self.n_bars - 1:]
            diffs = [recent[i+1] - recent[i] for i in range(len(recent) - 1)]
            up_run = all(d > 0 for d in diffs)
            down_run = all(d < 0 for d in diffs)
            if not up_run and not down_run:
                continue
            # magnitude filter: cumulative N-bar return / sigma > entry_z
            cum_ret = (closes[-1] - closes[-self.n_bars - 1]) / closes[-self.n_bars - 1]
            sigma_seg = closes[-self.sigma_window:]
            single_rets = [(sigma_seg[i+1] - sigma_seg[i]) / sigma_seg[i] for i in range(len(sigma_seg) - 1) if sigma_seg[i] > 0]
            sigma = pstdev(single_rets) if len(single_rets) >= 5 else 0.0
            if sigma == 0:
                continue
            n_bar_sigma = sigma * (self.n_bars ** 0.5)
            z = cum_ret / n_bar_sigma
            cur = self._current_side(state, s)
            if up_run and z > self.entry_z and cur != "SHORT":
                orders[s] = Order(
                    side=Side.SELL, quantity=0.0,
                    weight=self.max_weight, order_type=OrderType.MARKET,
                )
            elif down_run and z < -self.entry_z and cur != "LONG":
                orders[s] = Order(
                    side=Side.BUY, quantity=0.0,
                    weight=self.max_weight, order_type=OrderType.MARKET,
                )

        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
