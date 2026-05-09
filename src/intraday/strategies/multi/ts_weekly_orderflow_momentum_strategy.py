"""is_009_ts_weekly_orderflow_momentum — per-symbol weekly orderflow momentum.

Cell-distinct from is_005 by idea_family. Same weekly cadence and exit
(signal_flip), but the signal is built from cumulative signed taker-buy
volume over the past week, z-scored against the trailing 4-week history.
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
    "universe": "basket_full",
    "exit": "signal_flip",
    "idea_family": "ts_weekly_orderflow_momentum",
}
SOURCE_NOTES: list[str] = ["research/notes/ts_weekly_orderflow_momentum.md"]


class TsWeeklyOrderflowMomentumStrategy:
    def __init__(
        self,
        symbols: list[str],
        lookback_bars: int = 10080,
        history_window: int = 4,
        rebalance_bars: int = 10080,
        entry_z: float = 0.5,
        exit_z: float = 0.1,
        max_weight: float = 0.14,
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")

        self.symbols = [s.upper() for s in symbols]
        self.lookback_bars = max(2, int(lookback_bars))
        self.history_window = max(3, int(history_window))
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.entry_z = float(entry_z)
        self.exit_z = float(exit_z)
        self.max_weight = max(0.0, min(1.0, float(max_weight)))

        # rolling per-bar signed flow
        self._signed_flow: dict[str, deque[float]] = {
            s: deque(maxlen=self.lookback_bars) for s in self.symbols
        }
        # rolling history of completed weekly flow sums
        self._flow_history: dict[str, deque[float]] = {
            s: deque(maxlen=self.history_window) for s in self.symbols
        }
        self._bar_count = 0

    def _current_flow(self, symbol: str) -> float | None:
        sf = self._signed_flow[symbol]
        if len(sf) < self.lookback_bars:
            return None
        return float(sum(sf))

    def _z_for(self, symbol: str) -> float | None:
        cur = self._current_flow(symbol)
        if cur is None:
            return None
        history = self._flow_history[symbol]
        if len(history) < self.history_window:
            return None
        sigma = pstdev(history)
        mu = mean(history)
        if sigma <= 0 or not math.isfinite(sigma):
            return None
        return (cur - mu) / sigma

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
            vol = data.get("volume")
            imb = data.get("volume_imbalance")
            if vol is None or imb is None:
                continue
            v = float(vol)
            i = float(imb)
            if not (math.isfinite(v) and math.isfinite(i)) or v <= 0:
                continue
            self._signed_flow[symbol].append(i * v)

        self._bar_count += 1
        if self._bar_count % self.rebalance_bars != 0:
            return None

        for symbol in self.symbols:
            cur = self._current_flow(symbol)
            if cur is not None and math.isfinite(cur):
                self._flow_history[symbol].append(cur)

        targets: dict[str, str] = {}
        zscores: dict[str, float] = {}
        for symbol in self.symbols:
            z = self._z_for(symbol)
            if z is None:
                continue
            zscores[symbol] = z
            if z > self.entry_z:
                targets[symbol] = "LONG"
            elif z < -self.entry_z:
                targets[symbol] = "SHORT"

        n_active = len(targets)
        per_leg_weight = (
            min(self.max_weight, 1.0 / n_active) if n_active > 0 else 0.0
        )

        orders: dict[str, Order | None] = {}
        any_change = False
        for symbol in self.symbols:
            current_side = self._position_side(state, symbol)
            target = targets.get(symbol)
            z = zscores.get(symbol)

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
            elif z is not None and abs(z) < self.exit_z and current_side is not None:
                orders[symbol] = self._close_order(current_side)
                any_change = True
            else:
                orders[symbol] = None

        return PortfolioOrder(orders=orders) if any_change else None
