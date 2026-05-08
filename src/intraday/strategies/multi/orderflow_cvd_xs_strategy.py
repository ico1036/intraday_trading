"""is_002_orderflow_cvd_xs — cross-sectional CVD orderflow alpha.

Hypothesis: persistent taker-buy aggression over a lookback window predicts
near-term return continuation. Each bar we compute a CVD ratio per symbol and
rank cross-sectionally; longs go to the top, shorts to the bottom. This is
orthogonal to price-based momentum because the signal is built from the
signed-volume residual (buy_volume - sell_volume), not from price changes.

Signal per symbol over the rolling window:
    signed_volume[t] = volume_imbalance[t] * volume[t]
    cvd_ratio = sum(signed_volume) / sum(volume)

Cross-section across symbols:
    z = (cvd_ratio - mean) / std

Long if z > entry_z, short if z < -entry_z. Exit when |z| < exit_z.
"""
from __future__ import annotations

import math
from collections import deque
from statistics import mean, pstdev
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


class OrderflowCvdXsStrategy:
    def __init__(
        self,
        symbols: list[str],
        lookback_bars: int = 240,
        rebalance_bars: int = 1,
        entry_z: float = 1.0,
        exit_z: float = 0.3,
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

        self._signed_vol: dict[str, deque[float]] = {
            s: deque(maxlen=self.lookback_bars) for s in self.symbols
        }
        self._total_vol: dict[str, deque[float]] = {
            s: deque(maxlen=self.lookback_bars) for s in self.symbols
        }
        self._bar_count = 0

    def _cvd_ratio(self, symbol: str) -> float | None:
        sv = self._signed_vol[symbol]
        tv = self._total_vol[symbol]
        if len(sv) < self.lookback_bars:
            return None
        total = sum(tv)
        if total <= 0:
            return None
        return sum(sv) / total

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
            self._total_vol[symbol].append(v)

        self._bar_count += 1
        if self._bar_count % self.rebalance_bars != 0:
            return None

        ratios: dict[str, float] = {}
        for symbol in self.symbols:
            r = self._cvd_ratio(symbol)
            if r is not None and math.isfinite(r):
                ratios[symbol] = r

        if len(ratios) < 2:
            return None

        values = list(ratios.values())
        mu = mean(values)
        sigma = pstdev(values)
        if sigma <= 0 or not math.isfinite(sigma):
            return None

        active_signals: dict[str, str] = {}
        for symbol in self.symbols:
            if symbol not in ratios:
                continue
            z = (ratios[symbol] - mu) / sigma
            if z > self.entry_z:
                active_signals[symbol] = "LONG"
            elif z < -self.entry_z:
                active_signals[symbol] = "SHORT"

        n_active = len(active_signals)
        per_leg_weight = (
            min(self.max_weight, 1.0 / n_active) if n_active > 0 else 0.0
        )

        orders: dict[str, Order | None] = {}
        for symbol in self.symbols:
            current_side = self._position_side(state, symbol)
            if symbol not in ratios:
                orders[symbol] = None
                continue
            z = (ratios[symbol] - mu) / sigma
            target = active_signals.get(symbol)

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

        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
