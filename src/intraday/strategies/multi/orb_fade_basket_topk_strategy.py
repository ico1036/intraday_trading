"""ORB-fade with basket_topk universe (rank-by-break-magnitude).

Each rebalance after the OR window, rank symbols by their break magnitude
(close - OR-high) / OR-width. Take top-k SHORT (largest upward breaks) and
bottom-k LONG (largest downward breaks). Cell universe value differs from
is_023 (basket_full → basket_topk).
"""
from __future__ import annotations

from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "raw",
    "horizon": "session",
    "universe": "basket_topk",
    "exit": "signal_flip",
    "idea_family": "orb_fade",
}
SOURCE_NOTES: list[str] = ["research/notes/orb_fade.md"]


class OrbFadeBasketTopkStrategy:
    def __init__(
        self,
        symbols: list[str],
        or_minutes: int = 60,
        top_k: int = 2,
        max_weight: float = 0.20,
        rebalance_bars: int = 30,
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")
        self.symbols = [s.upper() for s in symbols]
        self.or_minutes = max(5, int(or_minutes))
        self.top_k = max(1, int(top_k))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self.rebalance_bars = max(1, int(rebalance_bars))

        self._or_high: dict[str, float | None] = {s: None for s in self.symbols}
        self._or_low: dict[str, float | None] = {s: None for s in self.symbols}
        self._current_day: int | None = None
        self._bar_count = 0

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
        day = ts.toordinal()
        minute_of_day = ts.hour * 60 + ts.minute

        if self._current_day is None or day != self._current_day:
            self._current_day = day
            self._reset()

        if minute_of_day < self.or_minutes:
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

        self._bar_count += 1
        if self._bar_count % self.rebalance_bars != 0:
            return None

        # rank by signed break magnitude
        upper_breaks = []  # (sym, magnitude > 0)
        lower_breaks = []
        for s in self.symbols:
            d = state.panel.get(s)
            if not d:
                continue
            close = d.get("close")
            hi = self._or_high.get(s)
            lo = self._or_low.get(s)
            if close is None or hi is None or lo is None:
                continue
            or_w = max(hi - lo, 1e-9)
            if close > hi:
                upper_breaks.append((s, (close - hi) / or_w))
            elif close < lo:
                lower_breaks.append((s, (lo - close) / or_w))
        upper_breaks.sort(key=lambda kv: kv[1], reverse=True)
        lower_breaks.sort(key=lambda kv: kv[1], reverse=True)

        short_targets = {s for s, _ in upper_breaks[: self.top_k]}
        long_targets = {s for s, _ in lower_breaks[: self.top_k]}

        orders: dict[str, Order | None] = {}
        for s in self.symbols:
            cur = self._current_side(state, s)
            if s in short_targets:
                orders[s] = (
                    None
                    if cur == "SHORT"
                    else Order(
                        side=Side.SELL, quantity=0.0,
                        weight=self.max_weight, order_type=OrderType.MARKET,
                    )
                )
            elif s in long_targets:
                orders[s] = (
                    None
                    if cur == "LONG"
                    else Order(
                        side=Side.BUY, quantity=0.0,
                        weight=self.max_weight, order_type=OrderType.MARKET,
                    )
                )
            else:
                orders[s] = None  # signal_flip: hold existing position until break of opposite side flips

        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
