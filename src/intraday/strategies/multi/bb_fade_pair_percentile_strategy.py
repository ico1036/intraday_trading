"""BB-fade pair (BTC + ETH) percentile."""
from __future__ import annotations

from collections import deque
from statistics import mean, pstdev
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "percentile",
    "horizon": "session",
    "universe": "pair",
    "exit": "signal_flip",
    "idea_family": "bb_band_fade",
}
SOURCE_NOTES: list[str] = ["research/notes/bb_band_fade.md"]


class BbFadePairPercentileStrategy:
    def __init__(
        self,
        symbols: list[str],
        leg_a: str = "BTCUSDT",
        leg_b: str = "ETHUSDT",
        window: int = 1440,
        history_size: int = 30,
        entry_pctile: float = 0.30,
        rebalance_bars: int = 60,
        max_weight: float = 0.30,
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")
        self.symbols = [s.upper() for s in symbols]
        self.leg_a = leg_a.upper()
        self.leg_b = leg_b.upper()
        if self.leg_a not in self.symbols or self.leg_b not in self.symbols:
            raise ValueError("legs must be in symbols")
        self.active = [self.leg_a, self.leg_b]
        self.window = max(60, int(window))
        self.history_size = max(10, int(history_size))
        self.entry_pctile = max(0.0, min(1.0, float(entry_pctile)))
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))

        self._closes: dict[str, deque[float]] = {
            s: deque(maxlen=self.window + 5) for s in self.active
        }
        self._z_hist: dict[str, deque[float]] = {
            s: deque(maxlen=self.history_size) for s in self.active
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
        for s in self.active:
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
        for s in self.active:
            closes = list(self._closes[s])
            if len(closes) < self.window:
                continue
            seg = closes[-self.window:]
            mu = mean(seg)
            sd = pstdev(seg) or 1e-12
            close = closes[-1]
            z = (close - mu) / sd
            absz = abs(z)
            hist = list(self._z_hist[s])
            self._z_hist[s].append(absz)
            if len(hist) >= 5:
                hist_sorted = sorted(hist)
                idx = int((1.0 - self.entry_pctile) * (len(hist_sorted) - 1))
                threshold = hist_sorted[idx]
                if absz < threshold:
                    continue
            else:
                if absz < 1.5:
                    continue
            cur = self._current_side(state, s)
            if z > 0 and cur != "SHORT":
                orders[s] = Order(
                    side=Side.SELL, quantity=0.0,
                    weight=self.max_weight, order_type=OrderType.MARKET,
                )
            elif z < 0 and cur != "LONG":
                orders[s] = Order(
                    side=Side.BUY, quantity=0.0,
                    weight=self.max_weight, order_type=OrderType.MARKET,
                )

        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
