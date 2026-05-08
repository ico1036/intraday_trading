"""Session-extreme revert basket z_score (cell variant)."""
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
    "idea_family": "session_extreme_revert",
}
SOURCE_NOTES: list[str] = ["research/notes/session_extreme_revert.md"]


class SessionExtremeRevertBasketZscoreStrategy:
    def __init__(
        self,
        symbols: list[str],
        warmup_minutes: int = 60,
        sigma_window: int = 480,
        entry_z: float = 1.0,
        max_weight: float = 0.13,
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")
        self.symbols = [s.upper() for s in symbols]
        self.warmup_minutes = max(5, int(warmup_minutes))
        self.sigma_window = max(20, int(sigma_window))
        self.entry_z = float(entry_z)
        self.max_weight = max(0.0, min(1.0, float(max_weight)))

        self._sess_high: dict[str, float | None] = {s: None for s in self.symbols}
        self._sess_low: dict[str, float | None] = {s: None for s in self.symbols}
        self._sess_open: dict[str, float | None] = {s: None for s in self.symbols}
        self._closes: dict[str, deque[float]] = {
            s: deque(maxlen=self.sigma_window + 5) for s in self.symbols
        }
        self._current_day: int | None = None

    def _reset(self) -> None:
        for s in self.symbols:
            self._sess_high[s] = None
            self._sess_low[s] = None
            self._sess_open[s] = None

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
            if self._sess_open[s] is None and close is not None:
                self._sess_open[s] = float(close)
            if close is not None and close > 0:
                self._closes[s].append(float(close))

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
            so = self._sess_open.get(s)
            if close is None or sh is None or sl is None or so is None or so <= 0:
                continue
            # z-score of (close - open) in units of trailing return sigma
            closes = list(self._closes[s])
            if len(closes) < self.sigma_window:
                continue
            seg = closes[-self.sigma_window:]
            rets = [(seg[i+1] - seg[i]) / seg[i] for i in range(len(seg) - 1) if seg[i] > 0]
            sigma = pstdev(rets) if len(rets) >= 5 else 0.0
            if sigma == 0:
                continue
            stretch = (close - so) / so
            n_bar_sigma = sigma * (minute_of_day ** 0.5)  # approximate
            if n_bar_sigma == 0:
                continue
            z = stretch / n_bar_sigma
            absz = abs(z)
            cur = self._current_side(state, s)
            # require both at session extreme AND |z| > entry_z
            if close >= sh - 1e-9 and z > self.entry_z and cur != "SHORT":
                orders[s] = Order(
                    side=Side.SELL, quantity=0.0,
                    weight=self.max_weight, order_type=OrderType.MARKET,
                )
            elif close <= sl + 1e-9 and z < -self.entry_z and cur != "LONG":
                orders[s] = Order(
                    side=Side.BUY, quantity=0.0,
                    weight=self.max_weight, order_type=OrderType.MARKET,
                )

        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
