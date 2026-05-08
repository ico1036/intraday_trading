"""ORB-fade with rolling_rank transform (cell variant of is_023).

Per-symbol rolling rank of break magnitude vs trailing N breaks.
Cell transform value differs (raw → rolling_rank).
"""
from __future__ import annotations

from collections import deque
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "rolling_rank",
    "horizon": "session",
    "universe": "basket_full",
    "exit": "signal_flip",
    "idea_family": "orb_fade",
}
SOURCE_NOTES: list[str] = ["research/notes/orb_fade.md"]


class OrbFadeRollingRankStrategy:
    def __init__(
        self,
        symbols: list[str],
        or_minutes: int = 60,
        history_size: int = 30,
        rank_threshold: float = 0.30,
        max_weight: float = 0.13,
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")
        self.symbols = [s.upper() for s in symbols]
        self.or_minutes = max(5, int(or_minutes))
        self.history_size = max(10, int(history_size))
        self.rank_threshold = max(0.0, min(1.0, float(rank_threshold)))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))

        self._or_high: dict[str, float | None] = {s: None for s in self.symbols}
        self._or_low: dict[str, float | None] = {s: None for s in self.symbols}
        self._mag_history: dict[str, deque[float]] = {
            s: deque(maxlen=self.history_size) for s in self.symbols
        }
        self._current_day: int | None = None

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
            or_w = max(hi - lo, 1e-9)
            mag = 0.0
            side_target = None
            if close > hi:
                mag = (close - hi) / or_w
                side_target = "SHORT"
            elif close < lo:
                mag = (lo - close) / or_w
                side_target = "LONG"
            else:
                continue

            hist = list(self._mag_history[s])
            self._mag_history[s].append(mag)
            if len(hist) >= 5:
                rank = sum(1 for x in hist if x <= mag) / len(hist)
                if rank < (1.0 - self.rank_threshold):
                    continue

            cur = self._current_side(state, s)
            if side_target == "SHORT" and cur != "SHORT":
                orders[s] = Order(
                    side=Side.SELL, quantity=0.0,
                    weight=self.max_weight, order_type=OrderType.MARKET,
                )
            elif side_target == "LONG" and cur != "LONG":
                orders[s] = Order(
                    side=Side.BUY, quantity=0.0,
                    weight=self.max_weight, order_type=OrderType.MARKET,
                )

        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
