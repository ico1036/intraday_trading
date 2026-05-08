"""ORB-fade single BTC time_stop composite."""
from __future__ import annotations

from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "composite",
    "horizon": "session",
    "universe": "single",
    "exit": "time_stop",
    "idea_family": "orb_fade",
}
SOURCE_NOTES: list[str] = ["research/notes/orb_fade.md"]


class OrbFadeSingleBtcTsCompStrategy:
    def __init__(
        self,
        symbols: list[str],
        target: str = "BTCUSDT",
        or_minutes: int = 60,
        flat_at_minute: int = 1410,
        composite_threshold: float = 0.10,
        max_weight: float = 0.5,
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")
        self.symbols = [s.upper() for s in symbols]
        self.target = target.upper()
        if self.target not in self.symbols:
            raise ValueError(f"target {self.target} not in symbols")
        self.or_minutes = max(5, int(or_minutes))
        self.flat_at_minute = int(flat_at_minute)
        self.composite_threshold = float(composite_threshold)
        self.max_weight = max(0.0, min(1.0, float(max_weight)))

        self._or_high: float | None = None
        self._or_low: float | None = None
        self._or_mid: float | None = None
        self._current_day: int | None = None

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
        ts = state.timestamp
        day = ts.toordinal()
        minute_of_day = ts.hour * 60 + ts.minute

        if self._current_day is None or day != self._current_day:
            self._current_day = day
            self._or_high = None
            self._or_low = None
            self._or_mid = None

        d = state.panel.get(self.target)

        if minute_of_day < self.or_minutes:
            if d:
                hi = d.get("high")
                lo = d.get("low")
                close = d.get("close")
                if hi is None and close is not None:
                    hi = close
                if lo is None and close is not None:
                    lo = close
                if hi is not None and lo is not None:
                    self._or_high = hi if self._or_high is None else max(self._or_high, float(hi))
                    self._or_low = lo if self._or_low is None else min(self._or_low, float(lo))
            if self._or_high is not None and self._or_low is not None:
                self._or_mid = (self._or_high + self._or_low) / 2
            return None

        orders: dict[str, Order | None] = {s: None for s in self.symbols}

        if minute_of_day >= self.flat_at_minute:
            cur = self._current_side(state)
            o = self._close_for_side(cur)
            if o is not None:
                orders[self.target] = o
            active = {s: o for s, o in orders.items() if o is not None}
            return PortfolioOrder(orders=orders) if active else None

        if not d:
            return None
        close = d.get("close")
        if close is None or self._or_high is None or self._or_low is None or self._or_mid is None:
            return None
        or_w = max(self._or_high - self._or_low, 1e-9)
        cur = self._current_side(state)
        if close > self._or_high:
            composite = (close - self._or_high) / or_w + (close - self._or_mid) / or_w
            if composite > self.composite_threshold and cur != "SHORT":
                orders[self.target] = Order(
                    side=Side.SELL, quantity=0.0,
                    weight=self.max_weight, order_type=OrderType.MARKET,
                )
        elif close < self._or_low:
            composite = (self._or_low - close) / or_w + (self._or_mid - close) / or_w
            if composite > self.composite_threshold and cur != "LONG":
                orders[self.target] = Order(
                    side=Side.BUY, quantity=0.0,
                    weight=self.max_weight, order_type=OrderType.MARKET,
                )
        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
