"""BB-fade session single BTC with ewma_residual transform."""
from __future__ import annotations

from collections import deque
from statistics import mean, pstdev
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "ewma_residual",
    "horizon": "session",
    "universe": "single",
    "exit": "signal_flip",
    "idea_family": "bb_band_fade",
}
SOURCE_NOTES: list[str] = ["research/notes/bb_band_fade.md"]


class BbFadeSingleBtcEwmaResidualStrategy:
    def __init__(
        self,
        symbols: list[str],
        target: str = "BTCUSDT",
        window: int = 1440,
        k: float = 2.0,
        ema_window: int = 20,
        rebalance_bars: int = 60,
        max_weight: float = 0.5,
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")
        self.symbols = [s.upper() for s in symbols]
        self.target = target.upper()
        if self.target not in self.symbols:
            raise ValueError(f"target {self.target} not in symbols")
        self.window = max(60, int(window))
        self.k = float(k)
        self.ema_window = max(5, int(ema_window))
        self.alpha_ema = 2.0 / (self.ema_window + 1.0)
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))

        self._closes: deque[float] = deque(maxlen=self.window + 5)
        self._ema_z: float = 0.0
        self._bar_count = 0

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
        d = state.panel.get(self.target)
        if d:
            close = d.get("close")
            if close is not None and close > 0:
                self._closes.append(float(close))

        self._bar_count += 1
        if self._bar_count % self.rebalance_bars != 0:
            return None
        if len(self._closes) < self.window:
            return None

        seg = list(self._closes)[-self.window:]
        mu = mean(seg)
        sd = pstdev(seg) or 1e-12
        close = self._closes[-1]
        z = (close - mu) / sd
        absz = abs(z)
        self._ema_z = self.alpha_ema * absz + (1 - self.alpha_ema) * self._ema_z
        residual = absz - self._ema_z
        if absz < self.k or residual <= 0:
            return None
        cur = self._current_side(state)
        orders: dict[str, Order | None] = {s: None for s in self.symbols}
        if z > 0 and cur != "SHORT":
            orders[self.target] = Order(
                side=Side.SELL, quantity=0.0,
                weight=self.max_weight, order_type=OrderType.MARKET,
            )
        elif z < 0 and cur != "LONG":
            orders[self.target] = Order(
                side=Side.BUY, quantity=0.0,
                weight=self.max_weight, order_type=OrderType.MARKET,
            )
        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
