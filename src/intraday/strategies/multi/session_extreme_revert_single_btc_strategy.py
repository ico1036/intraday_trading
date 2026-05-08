"""Session extreme revert single BTC."""
from __future__ import annotations

from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "raw",
    "horizon": "session",
    "universe": "single",
    "exit": "signal_flip",
    "idea_family": "session_extreme_revert",
}
SOURCE_NOTES: list[str] = ["research/notes/session_extreme_revert.md"]


class SessionExtremeRevertSingleBtcStrategy:
    def __init__(
        self,
        symbols: list[str],
        target: str = "BTCUSDT",
        warmup_minutes: int = 30,
        max_weight: float = 0.5,
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")
        self.symbols = [s.upper() for s in symbols]
        self.target = target.upper()
        if self.target not in self.symbols:
            raise ValueError(f"target {self.target} not in symbols")
        self.warmup_minutes = max(5, int(warmup_minutes))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))

        self._sess_high: float | None = None
        self._sess_low: float | None = None
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
        minute_of_day = ts.hour * 60 + ts.minute

        if self._current_day is None or day != self._current_day:
            self._current_day = day
            self._sess_high = None
            self._sess_low = None

        d = state.panel.get(self.target)
        if d:
            high = d.get("high")
            low = d.get("low")
            close = d.get("close")
            if high is None and close is not None:
                high = close
            if low is None and close is not None:
                low = close
            if high is not None and low is not None:
                self._sess_high = high if self._sess_high is None else max(self._sess_high, float(high))
                self._sess_low = low if self._sess_low is None else min(self._sess_low, float(low))

        if minute_of_day < self.warmup_minutes:
            return None
        if not d:
            return None
        close = d.get("close")
        if close is None or self._sess_high is None or self._sess_low is None:
            return None
        cur = self._current_side(state)
        orders: dict[str, Order | None] = {s: None for s in self.symbols}
        if close >= self._sess_high - 1e-9:
            if cur != "SHORT":
                orders[self.target] = Order(
                    side=Side.SELL, quantity=0.0,
                    weight=self.max_weight, order_type=OrderType.MARKET,
                )
        elif close <= self._sess_low + 1e-9:
            if cur != "LONG":
                orders[self.target] = Order(
                    side=Side.BUY, quantity=0.0,
                    weight=self.max_weight, order_type=OrderType.MARKET,
                )
        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
