"""Session VWAP fade across basket.

Compute per-symbol session VWAP (resets daily). When close deviates from
VWAP by > threshold (in fractional units), fade. Hold until opposite cross.
"""
from __future__ import annotations

from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "raw",
    "horizon": "session",
    "universe": "basket_full",
    "exit": "signal_flip",
    "idea_family": "vwap_fade",
}
SOURCE_NOTES: list[str] = ["research/notes/vwap_fade.md"]


class VwapFadeBasketStrategy:
    def __init__(
        self,
        symbols: list[str],
        deviation_threshold: float = 0.005,   # 0.5% above/below VWAP
        max_weight: float = 0.13,
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")
        self.symbols = [s.upper() for s in symbols]
        self.deviation_threshold = float(deviation_threshold)
        self.max_weight = max(0.0, min(1.0, float(max_weight)))

        self._notional_sum: dict[str, float] = {s: 0.0 for s in self.symbols}
        self._volume_sum: dict[str, float] = {s: 0.0 for s in self.symbols}
        self._current_day: int | None = None

    def _reset(self) -> None:
        for s in self.symbols:
            self._notional_sum[s] = 0.0
            self._volume_sum[s] = 0.0

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
        ts = state.timestamp
        day = ts.toordinal()

        if self._current_day is None or day != self._current_day:
            self._current_day = day
            self._reset()

        # update VWAP accumulators
        for s in self.symbols:
            d = state.panel.get(s)
            if not d:
                continue
            close = d.get("close")
            volume = d.get("volume", 0.0) or 0.0
            if close is not None and close > 0 and volume > 0:
                self._notional_sum[s] += float(close) * float(volume)
                self._volume_sum[s] += float(volume)

        orders: dict[str, Order | None] = {s: None for s in self.symbols}
        for s in self.symbols:
            if self._volume_sum[s] <= 0:
                continue
            vwap = self._notional_sum[s] / self._volume_sum[s]
            d = state.panel.get(s)
            if not d:
                continue
            close = d.get("close")
            if close is None:
                continue
            cur = self._current_side(state, s)
            dev = (close - vwap) / vwap if vwap > 0 else 0.0
            if dev > self.deviation_threshold:
                if cur != "SHORT":
                    orders[s] = Order(
                        side=Side.SELL, quantity=0.0,
                        weight=self.max_weight, order_type=OrderType.MARKET,
                    )
            elif dev < -self.deviation_threshold:
                if cur != "LONG":
                    orders[s] = Order(
                        side=Side.BUY, quantity=0.0,
                        weight=self.max_weight, order_type=OrderType.MARKET,
                    )

        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
