"""Donchian fade single BTC with percentile transform."""
from __future__ import annotations

from collections import deque
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "percentile",
    "horizon": "session",
    "universe": "single",
    "exit": "signal_flip",
    "idea_family": "donchian_fade",
}
SOURCE_NOTES: list[str] = ["research/notes/donchian_fade.md"]


class DonchianFadeSingleBtcPctileStrategy:
    def __init__(
        self,
        symbols: list[str],
        target: str = "BTCUSDT",
        channel_bars: int = 1440,
        history_size: int = 30,
        entry_pctile: float = 0.30,
        max_weight: float = 0.5,
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")
        self.symbols = [s.upper() for s in symbols]
        self.target = target.upper()
        if self.target not in self.symbols:
            raise ValueError(f"target {self.target} not in symbols")
        self.channel_bars = max(60, int(channel_bars))
        self.history_size = max(10, int(history_size))
        self.entry_pctile = max(0.0, min(1.0, float(entry_pctile)))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))

        self._highs: deque[float] = deque(maxlen=self.channel_bars + 5)
        self._lows: deque[float] = deque(maxlen=self.channel_bars + 5)
        self._mag_hist: deque[float] = deque(maxlen=self.history_size)

    def _current_side(self, state: MarketState) -> str | None:
        if not state.positions:
            return None
        info = state.positions.get(self.target)
        if not info:
            return None
        side = info.get("side")
        return side if side in {"LONG", "SHORT"} else None

    def generate_order(self, state: MarketState) -> PortfolioOrder | None:
        if state.panel is None:
            return None
        d = state.panel.get(self.target)
        if d:
            close = d.get("close")
            high = d.get("high", close)
            low = d.get("low", close)
            if close is not None and high is not None and low is not None:
                self._highs.append(float(high))
                self._lows.append(float(low))

        if len(self._highs) < self.channel_bars + 1:
            return None
        d_high = max(list(self._highs)[-self.channel_bars - 1:-1])
        d_low = min(list(self._lows)[-self.channel_bars - 1:-1])
        if not d or d.get("close") is None:
            return None
        close = float(d["close"])
        channel_w = max(d_high - d_low, 1e-9)
        mag = 0.0
        side_target = None
        if close > d_high:
            mag = (close - d_high) / channel_w
            side_target = "SHORT"
        elif close < d_low:
            mag = (d_low - close) / channel_w
            side_target = "LONG"
        if side_target is None:
            return None
        hist = list(self._mag_hist)
        self._mag_hist.append(mag)
        if len(hist) >= 5:
            hist_sorted = sorted(hist)
            idx = int((1.0 - self.entry_pctile) * (len(hist_sorted) - 1))
            threshold = hist_sorted[idx]
            if mag < threshold:
                return None
        cur = self._current_side(state)
        orders: dict[str, Order | None] = {s: None for s in self.symbols}
        if side_target == "SHORT" and cur != "SHORT":
            orders[self.target] = Order(
                side=Side.SELL, quantity=0.0,
                weight=self.max_weight, order_type=OrderType.MARKET,
            )
        elif side_target == "LONG" and cur != "LONG":
            orders[self.target] = Order(
                side=Side.BUY, quantity=0.0,
                weight=self.max_weight, order_type=OrderType.MARKET,
            )
        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
