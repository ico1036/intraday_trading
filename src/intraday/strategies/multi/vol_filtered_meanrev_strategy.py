"""Vol-regime filtered per-symbol reversal.

Trade only when trailing 4h rv exceeds a percentile threshold of its own
recent history. When triggered, fade the last 30m return.
"""
from __future__ import annotations

from collections import deque
from statistics import pstdev
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "ewma_residual",
    "horizon": "intraday",
    "universe": "basket_full",
    "exit": "vol_stop",
    "idea_family": "vol_filtered_meanrev",
}
SOURCE_NOTES: list[str] = ["research/notes/vol_filtered_meanrev.md"]


class VolFilteredMeanrevStrategy:
    def __init__(
        self,
        symbols: list[str],
        burst_bars: int = 30,
        sigma_bars: int = 240,
        rv_history_bars: int = 1440,
        rv_pctile: float = 0.70,
        hold_bars: int = 120,
        rebalance_bars: int = 30,
        entry_z: float = 1.5,
        max_weight: float = 0.13,
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")
        self.symbols = [s.upper() for s in symbols]
        self.burst_bars = max(2, int(burst_bars))
        self.sigma_bars = max(self.burst_bars + 5, int(sigma_bars))
        self.rv_history_bars = max(self.sigma_bars + 5, int(rv_history_bars))
        self.rv_pctile = max(0.05, min(0.95, float(rv_pctile)))
        self.hold_bars = max(1, int(hold_bars))
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.entry_z = float(entry_z)
        self.max_weight = max(0.0, min(1.0, float(max_weight)))

        self._closes: dict[str, deque[float]] = {
            s: deque(maxlen=self.rv_history_bars + self.burst_bars + 5)
            for s in self.symbols
        }
        self._held: dict[str, int] = {s: 0 for s in self.symbols}
        self._bar_count = 0

    def _rv(self, closes: list[float], window: int) -> float | None:
        if len(closes) < window + 1:
            return None
        rets = []
        for prev, cur in zip(closes[-window - 1:-1], closes[-window:]):
            rets.append((cur - prev) / prev if prev > 0 else 0.0)
        return pstdev(rets) if len(rets) >= 5 else None

    def _vol_regime_high(self, s: str) -> bool:
        closes = list(self._closes[s])
        if len(closes) < self.rv_history_bars + 1:
            return False
        # current rv
        cur_rv = self._rv(closes, self.sigma_bars)
        if cur_rv is None:
            return False
        # past distribution: rolling rvs over the history window
        rvs = []
        # compute past rv at each step
        step = max(1, self.sigma_bars // 4)
        for i in range(self.sigma_bars + step, len(closes), step):
            seg = closes[i - self.sigma_bars - 1: i]
            v = self._rv(seg, self.sigma_bars)
            if v is not None:
                rvs.append(v)
        if len(rvs) < 5:
            return False
        rvs.sort()
        idx = int(self.rv_pctile * (len(rvs) - 1))
        return cur_rv >= rvs[idx]

    def _burst_z(self, s: str) -> float | None:
        closes = list(self._closes[s])
        if len(closes) < self.sigma_bars + self.burst_bars + 1:
            return None
        old = closes[-self.burst_bars - 1]
        cur = closes[-1]
        if old <= 0:
            return None
        burst = (cur - old) / old
        # sigma of burst-scale returns
        burst_rets = []
        for i in range(self.sigma_bars):
            p = closes[-(self.sigma_bars + self.burst_bars) + i]
            n = closes[-(self.sigma_bars + self.burst_bars) + i + self.burst_bars]
            if p > 0:
                burst_rets.append((n - p) / p)
        if len(burst_rets) < 5:
            return None
        sigma = pstdev(burst_rets) or 1e-9
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
            if self._current_side(state, s) is not None:
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
            if not self._vol_regime_high(s):
                continue
            z = self._burst_z(s)
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
