"""ORB-fade single BTC with ewma_residual transform."""
from __future__ import annotations

from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "ewma_residual",
    "horizon": "session",
    "universe": "single",
    "exit": "signal_flip",
    "idea_family": "orb_fade",
}
SOURCE_NOTES: list[str] = ["research/notes/orb_fade.md"]


class OrbFadeSingleBtcEwmaResidualStrategy:
    def __init__(
        self,
        symbols: list[str],
        target: str = "BTCUSDT",
        or_minutes: int = 60,
        ema_window: int = 20,
        max_weight: float = 0.5,
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")
        self.symbols = [s.upper() for s in symbols]
        self.target = target.upper()
        if self.target not in self.symbols:
            raise ValueError(f"target {self.target} not in symbols")
        self.or_minutes = max(5, int(or_minutes))
        self.ema_window = max(5, int(ema_window))
        self.alpha_ema = 2.0 / (self.ema_window + 1.0)
        self.max_weight = max(0.0, min(1.0, float(max_weight)))

        self._or_high: float | None = None
        self._or_low: float | None = None
        self._ema_mag: float = 0.0
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
            self._or_high = None
            self._or_low = None

        d = state.panel.get(self.target)

        if minute_of_day < self.or_minutes:
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
        or_w = max(self._or_high - self._or_low, 1e-9)
        cur = self._current_side(state)
        mag = 0.0
        side_target = None
        if close > self._or_high:
            mag = (close - self._or_high) / or_w
            side_target = "SHORT"
        elif close < self._or_low:
            mag = (self._or_low - close) / or_w
            side_target = "LONG"
        self._ema_mag = self.alpha_ema * mag + (1 - self.alpha_ema) * self._ema_mag
        if side_target is None:
            return None
        residual = mag - self._ema_mag
        if residual <= 0:
            return None
        if side_target == "SHORT" and cur != "SHORT":
            orders[self.target] = Order(
                side=Side.SELL, quantity=0.0,
                weight=self.max_weight, order_type=OrderType.MARKET,
            )
        elif side_target == "LONG" and cur != "LONG":
            orders[self.target] = Order(
                side=Side.BUY, quantity=0.0,
                weight=self.max_weight, order_type=OrderType.MARKET,
            )

        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
