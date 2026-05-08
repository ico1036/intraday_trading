"""ORB-fade with z-score-magnitude trigger (transform=z_score variant).

Same horizon/universe/exit/family as is_023 but the entry trigger requires
the break to be > k sigma of recent daily ranges (rather than any close
beyond OR). Cell transform value differs (raw → z_score).
"""
from __future__ import annotations

from collections import deque
from statistics import pstdev
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "z_score",
    "horizon": "session",
    "universe": "basket_full",
    "exit": "signal_flip",
    "idea_family": "orb_fade",
}
SOURCE_NOTES: list[str] = ["research/notes/orb_fade.md"]


class OrbFadeZscoreStrategy:
    def __init__(
        self,
        symbols: list[str],
        or_minutes: int = 60,
        history_days: int = 14,
        entry_z: float = 0.5,
        max_weight: float = 0.13,
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")
        self.symbols = [s.upper() for s in symbols]
        self.or_minutes = max(5, int(or_minutes))
        self.history_days = max(2, int(history_days))
        self.entry_z = float(entry_z)
        self.max_weight = max(0.0, min(1.0, float(max_weight)))

        self._or_high: dict[str, float | None] = {s: None for s in self.symbols}
        self._or_low: dict[str, float | None] = {s: None for s in self.symbols}
        # historical break magnitudes (close - OR boundary) / OR width
        self._break_mags: dict[str, deque[float]] = {
            s: deque(maxlen=self.history_days * 5)
            for s in self.symbols
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
            or_width = max(hi - lo, 1e-9)
            cur = self._current_side(state, s)
            if close > hi:
                mag = (close - hi) / or_width
                self._break_mags[s].append(mag)
                hist = list(self._break_mags[s])[:-1]
                if len(hist) >= 5:
                    sd = pstdev(hist) or 1e-9
                    z = mag / sd
                    if z > self.entry_z and cur != "SHORT":
                        orders[s] = Order(
                            side=Side.SELL, quantity=0.0,
                            weight=self.max_weight, order_type=OrderType.MARKET,
                        )
            elif close < lo:
                mag = (lo - close) / or_width
                self._break_mags[s].append(mag)
                hist = list(self._break_mags[s])[:-1]
                if len(hist) >= 5:
                    sd = pstdev(hist) or 1e-9
                    z = mag / sd
                    if z > self.entry_z and cur != "LONG":
                        orders[s] = Order(
                            side=Side.BUY, quantity=0.0,
                            weight=self.max_weight, order_type=OrderType.MARKET,
                        )

        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
