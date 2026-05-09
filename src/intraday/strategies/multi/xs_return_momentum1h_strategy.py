"""is_007_xs_return_momentum_1h — cross-sectional 1h return momentum.

For each rebalance step, score each symbol by its trailing `lookback_bars`
log-return. Cross-sectional z-score across the panel; longs go to the top
z-quantile, shorts to the bottom. Holds until signal flips (z drops past
``exit_z`` magnitude or sign change).

This is a relative-return momentum signal — distinct from the existing
orderflow-based alphas which key off CVD / volume_imbalance.
"""
from __future__ import annotations

import math
from collections import deque
from statistics import mean, pstdev
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "z_score",
    "horizon": "intraday",
    "universe": "basket_topk",
    "exit": "signal_flip",
    "idea_family": "xs_return_momentum_1h",
}
SOURCE_NOTES: list[str] = ["research/notes/xs_return_momentum_1h.md"]


class XsReturnMomentum1hStrategy:
    def __init__(
        self,
        symbols: list[str],
        lookback_bars: int = 60,
        rebalance_bars: int = 5,
        entry_z: float = 0.8,
        exit_z: float = 0.2,
        max_weight: float = 0.3,
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")

        self.symbols = [s.upper() for s in symbols]
        self.lookback_bars = max(2, int(lookback_bars))
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.entry_z = float(entry_z)
        self.exit_z = float(exit_z)
        self.max_weight = max(0.0, min(1.0, float(max_weight)))

        self._closes: dict[str, deque[float]] = {
            s: deque(maxlen=self.lookback_bars + 1) for s in self.symbols
        }
        self._bar_count = 0

    def _log_return(self, symbol: str) -> float | None:
        prices = self._closes[symbol]
        if len(prices) < self.lookback_bars + 1:
            return None
        start = prices[0]
        end = prices[-1]
        if start <= 0 or end <= 0:
            return None
        return math.log(end / start)

    def _position_side(self, state: MarketState, symbol: str) -> str | None:
        if not state.positions:
            return None
        info = state.positions.get(symbol)
        if not info:
            return None
        side = info.get("side")
        return side if side in {"LONG", "SHORT"} else None

    def _close_order(self, side: str | None) -> Order | None:
        if side == "LONG":
            return Order(side=Side.SELL, quantity=0.0, order_type=OrderType.MARKET)
        if side == "SHORT":
            return Order(side=Side.BUY, quantity=0.0, order_type=OrderType.MARKET)
        return None

    def generate_order(self, state: MarketState) -> PortfolioOrder | None:
        if state.panel is None:
            return None

        for symbol in self.symbols:
            data = state.panel.get(symbol)
            if not data:
                continue
            close = data.get("close")
            if close is not None and float(close) > 0:
                self._closes[symbol].append(float(close))

        self._bar_count += 1
        if self._bar_count % self.rebalance_bars != 0:
            return None

        rets: dict[str, float] = {}
        for symbol in self.symbols:
            r = self._log_return(symbol)
            if r is not None and math.isfinite(r):
                rets[symbol] = r

        if len(rets) < 2:
            return None

        values = list(rets.values())
        mu = mean(values)
        sigma = pstdev(values)
        if sigma <= 0 or not math.isfinite(sigma):
            return None

        zscores = {s: (rets[s] - mu) / sigma for s in rets}

        active: dict[str, str] = {}
        for symbol, z in zscores.items():
            if z > self.entry_z:
                active[symbol] = "LONG"
            elif z < -self.entry_z:
                active[symbol] = "SHORT"

        n_active = len(active)
        per_leg_weight = (
            min(self.max_weight, 1.0 / n_active) if n_active > 0 else 0.0
        )

        orders: dict[str, Order | None] = {}
        for symbol in self.symbols:
            current_side = self._position_side(state, symbol)
            if symbol not in zscores:
                orders[symbol] = None
                continue
            z = zscores[symbol]
            target = active.get(symbol)

            if target == "LONG":
                orders[symbol] = (
                    None
                    if current_side == "LONG"
                    else Order(
                        side=Side.BUY,
                        quantity=0.0,
                        weight=per_leg_weight,
                        order_type=OrderType.MARKET,
                    )
                )
            elif target == "SHORT":
                orders[symbol] = (
                    None
                    if current_side == "SHORT"
                    else Order(
                        side=Side.SELL,
                        quantity=0.0,
                        weight=per_leg_weight,
                        order_type=OrderType.MARKET,
                    )
                )
            elif abs(z) < self.exit_z:
                orders[symbol] = self._close_order(current_side)
            else:
                orders[symbol] = None

        active_orders = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active_orders else None
