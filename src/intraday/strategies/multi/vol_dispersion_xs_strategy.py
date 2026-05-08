"""Cross-sectional realized-vol dispersion (intraday rebalance).

Compute per-symbol trailing realized vol; rank cross-sectionally.
LONG the lowest-rv coin, SHORT the highest-rv coin. Hourly rebalance.
The signal bets on rv mean-reversion across the basket.
"""
from __future__ import annotations

from collections import deque
from statistics import pstdev
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "rolling_rank",
    "horizon": "intraday",
    "universe": "basket_topk",
    "exit": "signal_flip",
    "idea_family": "vol_dispersion_xs",
}
SOURCE_NOTES: list[str] = ["research/notes/vol_dispersion.md"]


class VolDispersionXsStrategy:
    def __init__(
        self,
        symbols: list[str],
        rv_bars: int = 240,           # 4h
        rebalance_bars: int = 240,    # 4h
        top_k: int = 1,
        max_weight: float = 0.16,
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")
        self.symbols = [s.upper() for s in symbols]
        self.rv_bars = max(10, int(rv_bars))
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.top_k = max(1, int(top_k))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))

        self._closes: dict[str, deque[float]] = {
            s: deque(maxlen=self.rv_bars + 5) for s in self.symbols
        }
        self._bar_count = 0

    def _rv(self, s: str) -> float | None:
        closes = list(self._closes[s])
        if len(closes) < self.rv_bars + 1:
            return None
        rets = []
        for prev, cur in zip(closes[-self.rv_bars - 1:-1], closes[-self.rv_bars:]):
            rets.append((cur - prev) / prev if prev > 0 else 0.0)
        if len(rets) < 5:
            return None
        return pstdev(rets)

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

        self._bar_count += 1
        if self._bar_count % self.rebalance_bars != 0:
            return None

        rvs: dict[str, float] = {}
        for s in self.symbols:
            v = self._rv(s)
            if v is not None:
                rvs[s] = v
        if len(rvs) < 2:
            return None

        ranked = sorted(rvs.items(), key=lambda kv: kv[1])
        # lowest rv → LONG
        long_pick = [s for s, _ in ranked[: self.top_k]]
        # highest rv → SHORT
        short_pick = [s for s, _ in ranked[-self.top_k:]]

        orders: dict[str, Order | None] = {}
        for s in self.symbols:
            cur = self._current_side(state, s)
            if s in long_pick:
                orders[s] = (
                    None
                    if cur == "LONG"
                    else Order(
                        side=Side.BUY,
                        quantity=0.0,
                        weight=self.max_weight,
                        order_type=OrderType.MARKET,
                    )
                )
            elif s in short_pick:
                orders[s] = (
                    None
                    if cur == "SHORT"
                    else Order(
                        side=Side.SELL,
                        quantity=0.0,
                        weight=self.max_weight,
                        order_type=OrderType.MARKET,
                    )
                )
            else:
                orders[s] = self._close_for_side(cur)

        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
