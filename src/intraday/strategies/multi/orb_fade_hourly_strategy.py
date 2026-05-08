"""ORB-fade with hourly resetting OR (ultra_short horizon).

Same family as is_023 (orb_fade) but the OR resets every hour.
Cell horizon value differs (session → ultra_short).
"""
from __future__ import annotations

from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "raw",
    "horizon": "ultra_short",
    "universe": "basket_full",
    "exit": "signal_flip",
    "idea_family": "orb_fade",
}
SOURCE_NOTES: list[str] = ["research/notes/orb_fade.md"]


class OrbFadeHourlyStrategy:
    def __init__(
        self,
        symbols: list[str],
        or_minutes: int = 10,
        max_weight: float = 0.13,
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")
        self.symbols = [s.upper() for s in symbols]
        self.or_minutes = max(2, int(or_minutes))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))

        self._or_high: dict[str, float | None] = {s: None for s in self.symbols}
        self._or_low: dict[str, float | None] = {s: None for s in self.symbols}
        self._current_hour: tuple[int, int] | None = None

    def _reset(self) -> None:
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

    def generate_order(self, state: MarketState) -> PortfolioOrder | None:
        if state.panel is None:
            return None

        ts = state.timestamp
        key = (ts.toordinal(), ts.hour)
        minute = ts.minute

        if self._current_hour is None or key != self._current_hour:
            self._current_hour = key
            self._reset()

        if minute < self.or_minutes:
            for s in self.symbols:
                d = state.panel.get(s)
                if not d:
                    continue
                hi = d.get("high")
                lo = d.get("low")
                close = d.get("close")
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
        for s in self.symbols:
            d = state.panel.get(s)
            if not d:
                continue
            close = d.get("close")
            hi = self._or_high.get(s)
            lo = self._or_low.get(s)
            if close is None or hi is None or lo is None:
                continue
            cur = self._current_side(state, s)
            if close > hi:
                if cur != "SHORT":
                    orders[s] = Order(
                        side=Side.SELL, quantity=0.0,
                        weight=self.max_weight, order_type=OrderType.MARKET,
                    )
            elif close < lo:
                if cur != "LONG":
                    orders[s] = Order(
                        side=Side.BUY, quantity=0.0,
                        weight=self.max_weight, order_type=OrderType.MARKET,
                    )

        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
