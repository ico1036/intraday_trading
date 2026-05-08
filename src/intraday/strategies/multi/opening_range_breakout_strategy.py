"""Per-symbol opening-range breakout (session-level).

Each calendar UTC day: build (high, low) range over the first
``or_minutes`` minutes from 00:00. After the OR window:
    - LONG when close > OR-high
    - SHORT when close < OR-low
Hold one direction per symbol; flip on opposite break; flat at end of day.

This is a low-turnover, session-horizon cell.
"""
from __future__ import annotations

from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "raw",
    "horizon": "session",
    "universe": "basket_full",
    "exit": "time_stop",
    "idea_family": "opening_range_breakout",
}
SOURCE_NOTES: list[str] = ["research/notes/opening_range_breakout.md"]


class OpeningRangeBreakoutStrategy:
    def __init__(
        self,
        symbols: list[str],
        or_minutes: int = 60,
        max_weight: float = 0.13,
        flat_at_minute: int = 1410,  # 23:30 UTC
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")
        self.symbols = [s.upper() for s in symbols]
        self.or_minutes = max(5, int(or_minutes))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self.flat_at_minute = int(flat_at_minute)

        self._or_high: dict[str, float | None] = {s: None for s in self.symbols}
        self._or_low: dict[str, float | None] = {s: None for s in self.symbols}
        self._current_day: int | None = None

    def _reset_day(self) -> None:
        for s in self.symbols:
            self._or_high[s] = None
            self._or_low[s] = None

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

        ts = state.timestamp
        day = ts.toordinal()
        minute_of_day = ts.hour * 60 + ts.minute

        if self._current_day is None or day != self._current_day:
            self._current_day = day
            self._reset_day()

        # Update OR window from each symbol's high/low (or close if hi/lo absent)
        if minute_of_day < self.or_minutes:
            for s in self.symbols:
                data = state.panel.get(s)
                if not data:
                    continue
                hi = data.get("high")
                lo = data.get("low")
                close = data.get("close")
                if hi is None and close is not None:
                    hi = close
                if lo is None and close is not None:
                    lo = close
                if hi is None or lo is None:
                    continue
                cur_h = self._or_high[s]
                cur_l = self._or_low[s]
                self._or_high[s] = hi if cur_h is None else max(cur_h, float(hi))
                self._or_low[s] = lo if cur_l is None else min(cur_l, float(lo))
            return None

        orders: dict[str, Order | None] = {s: None for s in self.symbols}

        # End-of-day flatten
        if minute_of_day >= self.flat_at_minute:
            for s in self.symbols:
                cur = self._current_side(state, s)
                orders[s] = self._close_for_side(cur)
            active = {s: o for s, o in orders.items() if o is not None}
            return PortfolioOrder(orders=orders) if active else None

        # Trading window: act on break of OR
        for s in self.symbols:
            data = state.panel.get(s)
            if not data:
                continue
            close = data.get("close")
            hi = self._or_high.get(s)
            lo = self._or_low.get(s)
            if close is None or hi is None or lo is None:
                continue
            cur = self._current_side(state, s)
            if close > hi:
                if cur != "LONG":
                    orders[s] = Order(
                        side=Side.BUY,
                        quantity=0.0,
                        weight=self.max_weight,
                        order_type=OrderType.MARKET,
                    )
            elif close < lo:
                if cur != "SHORT":
                    orders[s] = Order(
                        side=Side.SELL,
                        quantity=0.0,
                        weight=self.max_weight,
                        order_type=OrderType.MARKET,
                    )

        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
