"""ORB-fade single BTC at intraday horizon (4-hour resetting OR).

Cell horizon value differs from is_040 (session → intraday).
"""
from __future__ import annotations

from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "raw",
    "horizon": "intraday",
    "universe": "single",
    "exit": "signal_flip",
    "idea_family": "orb_fade",
}
SOURCE_NOTES: list[str] = ["research/notes/orb_fade.md"]


class OrbFadeSingleBtcIntradayStrategy:
    def __init__(
        self,
        symbols: list[str],
        target: str = "BTCUSDT",
        block_hours: int = 4,
        or_minutes: int = 30,
        max_weight: float = 0.5,
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")
        self.symbols = [s.upper() for s in symbols]
        self.target = target.upper()
        if self.target not in self.symbols:
            raise ValueError(f"target {self.target} not in symbols")
        self.block_hours = max(1, int(block_hours))
        self.or_minutes = max(5, int(or_minutes))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))

        self._or_high: float | None = None
        self._or_low: float | None = None
        self._current_block: tuple[int, int] | None = None

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
        block_idx = ts.hour // self.block_hours
        block_start_minute = block_idx * self.block_hours * 60
        minute_in_block = (ts.hour * 60 + ts.minute) - block_start_minute

        if self._current_block is None or (day, block_idx) != self._current_block:
            self._current_block = (day, block_idx)
            self._or_high = None
            self._or_low = None

        d = state.panel.get(self.target)

        if minute_in_block < self.or_minutes:
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
            return None

        orders: dict[str, Order | None] = {s: None for s in self.symbols}
        if not d:
            return None
        close = d.get("close")
        if close is None or self._or_high is None or self._or_low is None:
            return None
        cur = self._current_side(state)
        if close > self._or_high:
            if cur != "SHORT":
                orders[self.target] = Order(
                    side=Side.SELL, quantity=0.0,
                    weight=self.max_weight, order_type=OrderType.MARKET,
                )
        elif close < self._or_low:
            if cur != "LONG":
                orders[self.target] = Order(
                    side=Side.BUY, quantity=0.0,
                    weight=self.max_weight, order_type=OrderType.MARKET,
                )

        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
