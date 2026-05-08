"""Session extreme revert — fade when close == running session high/low."""
from __future__ import annotations

from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "raw",
    "horizon": "session",
    "universe": "basket_full",
    "exit": "signal_flip",
    "idea_family": "session_extreme_revert",
}
SOURCE_NOTES: list[str] = ["research/notes/session_extreme_revert.md"]


class SessionExtremeRevertBasketStrategy:
    def __init__(
        self,
        symbols: list[str],
        warmup_minutes: int = 30,
        max_weight: float = 0.13,
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")
        self.symbols = [s.upper() for s in symbols]
        self.warmup_minutes = max(5, int(warmup_minutes))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))

        self._sess_high: dict[str, float | None] = {s: None for s in self.symbols}
        self._sess_low: dict[str, float | None] = {s: None for s in self.symbols}
        self._current_day: int | None = None

    def _reset(self) -> None:
        for s in self.symbols:
            self._sess_high[s] = None
            self._sess_low[s] = None

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
        minute_of_day = ts.hour * 60 + ts.minute

        if self._current_day is None or day != self._current_day:
            self._current_day = day
            self._reset()

        for s in self.symbols:
            d = state.panel.get(s)
            if not d:
                continue
            high = d.get("high")
            low = d.get("low")
            close = d.get("close")
            if high is None and close is not None:
                high = close
            if low is None and close is not None:
                low = close
            if high is None or low is None:
                continue
            cur_h = self._sess_high[s]
            cur_l = self._sess_low[s]
            self._sess_high[s] = high if cur_h is None else max(cur_h, float(high))
            self._sess_low[s] = low if cur_l is None else min(cur_l, float(low))

        if minute_of_day < self.warmup_minutes:
            return None

        orders: dict[str, Order | None] = {s: None for s in self.symbols}
        for s in self.symbols:
            d = state.panel.get(s)
            if not d:
                continue
            close = d.get("close")
            sh = self._sess_high.get(s)
            sl = self._sess_low.get(s)
            if close is None or sh is None or sl is None:
                continue
            cur = self._current_side(state, s)
            # close at session high → SHORT (fade)
            if close >= sh - 1e-9:
                if cur != "SHORT":
                    orders[s] = Order(
                        side=Side.SELL, quantity=0.0,
                        weight=self.max_weight, order_type=OrderType.MARKET,
                    )
            elif close <= sl + 1e-9:
                if cur != "LONG":
                    orders[s] = Order(
                        side=Side.BUY, quantity=0.0,
                        weight=self.max_weight, order_type=OrderType.MARKET,
                    )

        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
