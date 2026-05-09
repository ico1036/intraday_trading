"""is_002_xs_daily_momentum — daily cross-sectional return momentum.

Different cell from is_001 (intraday → multi_day horizon, idea_family
xs_daily_momentum). The 5-bar rebalance of is_001 incurred fee drag on ~95k
trades over 3 months; this version rebalances once per ``rebalance_bars``
(default 1440 = 24h on 1m TIME bars) and ranks symbols by trailing 24h log
return, going long the top z-quantile and short the bottom.
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
    "horizon": "multi_day",
    "universe": "basket_topk",
    "exit": "signal_flip",
    "idea_family": "xs_daily_momentum",
}
SOURCE_NOTES: list[str] = ["research/notes/xs_daily_momentum.md"]


class XsDailyMomentumStrategy:
    def __init__(
        self,
        symbols: list[str],
        lookback_bars: int = 1440,
        rebalance_bars: int = 1440,
        entry_z: float = 0.5,
        exit_z: float = 0.1,
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
        any_change = False
        for symbol in self.symbols:
            current_side = self._position_side(state, symbol)
            if symbol not in zscores:
                orders[symbol] = None
                continue
            z = zscores[symbol]
            target = active.get(symbol)

            if target == "LONG":
                if current_side != "LONG":
                    orders[symbol] = Order(
                        side=Side.BUY,
                        quantity=0.0,
                        weight=per_leg_weight,
                        order_type=OrderType.MARKET,
                    )
                    any_change = True
                else:
                    orders[symbol] = None
            elif target == "SHORT":
                if current_side != "SHORT":
                    orders[symbol] = Order(
                        side=Side.SELL,
                        quantity=0.0,
                        weight=per_leg_weight,
                        order_type=OrderType.MARKET,
                    )
                    any_change = True
                else:
                    orders[symbol] = None
            elif abs(z) < self.exit_z and current_side is not None:
                orders[symbol] = self._close_order(current_side)
                any_change = True
            else:
                orders[symbol] = None

        return PortfolioOrder(orders=orders) if any_change else None
