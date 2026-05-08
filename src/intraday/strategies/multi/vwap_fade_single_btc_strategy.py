"""Session VWAP fade single BTC."""
from __future__ import annotations

from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "raw",
    "horizon": "session",
    "universe": "single",
    "exit": "signal_flip",
    "idea_family": "vwap_fade",
}
SOURCE_NOTES: list[str] = ["research/notes/vwap_fade.md"]


class VwapFadeSingleBtcStrategy:
    def __init__(
        self,
        symbols: list[str],
        target: str = "BTCUSDT",
        deviation_threshold: float = 0.005,
        max_weight: float = 0.5,
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")
        self.symbols = [s.upper() for s in symbols]
        self.target = target.upper()
        if self.target not in self.symbols:
            raise ValueError(f"target {self.target} not in symbols")
        self.deviation_threshold = float(deviation_threshold)
        self.max_weight = max(0.0, min(1.0, float(max_weight)))

        self._notional_sum: float = 0.0
        self._volume_sum: float = 0.0
        self._current_day: int | None = None

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
        ts = state.timestamp
        day = ts.toordinal()
        if self._current_day is None or day != self._current_day:
            self._current_day = day
            self._notional_sum = 0.0
            self._volume_sum = 0.0

        d = state.panel.get(self.target)
        if d:
            close = d.get("close")
            volume = d.get("volume", 0.0) or 0.0
            if close is not None and close > 0 and volume > 0:
                self._notional_sum += float(close) * float(volume)
                self._volume_sum += float(volume)

        orders: dict[str, Order | None] = {s: None for s in self.symbols}
        if self._volume_sum <= 0 or not d:
            return None
        vwap = self._notional_sum / self._volume_sum
        close = d.get("close")
        if close is None or vwap <= 0:
            return None
        cur = self._current_side(state)
        dev = (close - vwap) / vwap
        if dev > self.deviation_threshold:
            if cur != "SHORT":
                orders[self.target] = Order(
                    side=Side.SELL, quantity=0.0,
                    weight=self.max_weight, order_type=OrderType.MARKET,
                )
        elif dev < -self.deviation_threshold:
            if cur != "LONG":
                orders[self.target] = Order(
                    side=Side.BUY, quantity=0.0,
                    weight=self.max_weight, order_type=OrderType.MARKET,
                )

        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
