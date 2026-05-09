"""is_008_ts_orderflow_momentum — per-symbol orderflow momentum.

For each symbol independently, accumulate signed taker-buy volume over the
``flow_window`` lookback and z-score it against the rolling ``norm_window``
window of the same accumulator. If the z exceeds ``entry_z`` go long; if
below ``-entry_z`` go short. Close when |z| falls under ``exit_z``.

Distinct from is_002_orderflow_cvd_xs (cross-sectional CVD ranking) because
each symbol's signal is computed against its own past — there is no
cross-symbol comparison.
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
    "universe": "basket_full",
    "exit": "signal_flip",
    "idea_family": "ts_orderflow_momentum",
}
SOURCE_NOTES: list[str] = ["research/notes/ts_orderflow_momentum.md"]


class TsOrderflowMomentumStrategy:
    def __init__(
        self,
        symbols: list[str],
        flow_window: int = 240,
        norm_window: int = 1440,
        rebalance_bars: int = 30,
        entry_z: float = 1.5,
        exit_z: float = 0.5,
        max_weight: float = 0.2,
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")
        if norm_window <= flow_window:
            raise ValueError("norm_window must exceed flow_window")

        self.symbols = [s.upper() for s in symbols]
        self.flow_window = max(2, int(flow_window))
        self.norm_window = max(self.flow_window + 1, int(norm_window))
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.entry_z = float(entry_z)
        self.exit_z = float(exit_z)
        self.max_weight = max(0.0, min(1.0, float(max_weight)))

        # rolling per-bar signed volume
        self._signed_vol: dict[str, deque[float]] = {
            s: deque(maxlen=self.flow_window) for s in self.symbols
        }
        # rolling history of completed flow_window sums for z-score
        self._flow_history: dict[str, deque[float]] = {
            s: deque(maxlen=self.norm_window) for s in self.symbols
        }
        self._bar_count = 0

    def _z_for(self, symbol: str) -> float | None:
        sv = self._signed_vol[symbol]
        history = self._flow_history[symbol]
        if len(sv) < self.flow_window:
            return None
        if len(history) < self.flow_window:  # need some warm history
            return None
        flow = sum(sv)
        sigma = pstdev(history)
        mu = mean(history)
        if sigma <= 0 or not math.isfinite(sigma):
            return None
        return (flow - mu) / sigma

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
            self._signed_vol[symbol].append(i * v)
            # update rolling flow_window sum into history when full
            if len(self._signed_vol[symbol]) == self.flow_window:
                self._flow_history[symbol].append(sum(self._signed_vol[symbol]))

        self._bar_count += 1
        if self._bar_count % self.rebalance_bars != 0:
            return None

        orders: dict[str, Order | None] = {}
        any_active = False
        for symbol in self.symbols:
            z = self._z_for(symbol)
            current_side = self._position_side(state, symbol)
            if z is None:
                orders[symbol] = None
                continue

            if z > self.entry_z:
                if current_side != "LONG":
                    orders[symbol] = Order(
                        side=Side.BUY,
                        quantity=0.0,
                        weight=self.max_weight,
                        order_type=OrderType.MARKET,
                    )
                    any_active = True
                else:
                    orders[symbol] = None
            elif z < -self.entry_z:
                if current_side != "SHORT":
                    orders[symbol] = Order(
                        side=Side.SELL,
                        quantity=0.0,
                        weight=self.max_weight,
                        order_type=OrderType.MARKET,
                    )
                    any_active = True
                else:
                    orders[symbol] = None
            elif abs(z) < self.exit_z and current_side is not None:
                orders[symbol] = self._close_order(current_side)
                any_active = True
            else:
                orders[symbol] = None

        return PortfolioOrder(orders=orders) if any_active else None
