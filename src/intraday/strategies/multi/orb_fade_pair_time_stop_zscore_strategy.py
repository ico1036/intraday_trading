"""ORB-fade pair with TIME_STOP exit + z_score."""
from __future__ import annotations

from collections import deque
from statistics import pstdev
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "z_score",
    "horizon": "session",
    "universe": "pair",
    "exit": "time_stop",
    "idea_family": "orb_fade",
}
SOURCE_NOTES: list[str] = ["research/notes/orb_fade.md"]


class OrbFadePairTimeStopZscoreStrategy:
    def __init__(
        self,
        symbols: list[str],
        leg_a: str = "BTCUSDT",
        leg_b: str = "ETHUSDT",
        or_minutes: int = 60,
        flat_at_minute: int = 1410,
        history_size: int = 30,
        entry_z: float = 0.5,
        max_weight: float = 0.30,
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")
        self.symbols = [s.upper() for s in symbols]
        self.leg_a = leg_a.upper()
        self.leg_b = leg_b.upper()
        if self.leg_a not in self.symbols or self.leg_b not in self.symbols:
            raise ValueError("legs must be in symbols")
        self.active = [self.leg_a, self.leg_b]
        self.or_minutes = max(5, int(or_minutes))
        self.flat_at_minute = int(flat_at_minute)
        self.history_size = max(10, int(history_size))
        self.entry_z = float(entry_z)
        self.max_weight = max(0.0, min(1.0, float(max_weight)))

        self._or_high: dict[str, float | None] = {s: None for s in self.active}
        self._or_low: dict[str, float | None] = {s: None for s in self.active}
        self._mag_hist: dict[str, deque[float]] = {
            s: deque(maxlen=self.history_size) for s in self.active
        }
        self._current_day: int | None = None

    def _reset(self) -> None:
        for s in self.active:
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
            self._reset()

        if minute_of_day < self.or_minutes:
            for s in self.active:
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

        if minute_of_day >= self.flat_at_minute:
            for s in self.active:
                cur = self._current_side(state, s)
                o = self._close_for_side(cur)
                if o is not None:
                    orders[s] = o
            active = {s: o for s, o in orders.items() if o is not None}
            return PortfolioOrder(orders=orders) if active else None

        for s in self.active:
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
            if side_target is None:
                continue
            hist = list(self._mag_hist[s])
            self._mag_hist[s].append(mag)
            if len(hist) >= 5:
                sd = pstdev(hist) or 1e-9
                z = mag / sd
                if z < self.entry_z:
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
