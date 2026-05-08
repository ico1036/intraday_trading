"""is_004 — orderflow rank top-1/bottom-1, daily rebalance.

Hypothesis: aggregating taker-buy aggression over a full day produces a
slow-moving signal that does not require frequent re-decisions. Take only
the most extreme long and most extreme short by rank, hold for the next
day, and accept low turnover as the dominant cost defense at 0.20% taker
fee.

Differences vs is_002 / is_003:
    - rank-based selection (top-1, bottom-1), not threshold-based
    - rebalance_bars defaults to 1440 (one decision per day at TIME 60s)
    - lookback_bars defaults to 1440 (daily CVD)
    - direction parameter: ``"continuation"`` or ``"reversion"`` for breadth
"""
from __future__ import annotations

import math
from collections import deque
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


class OrderflowRankDailyStrategy:
    def __init__(
        self,
        symbols: list[str],
        lookback_bars: int = 1440,
        rebalance_bars: int = 1440,
        top_k: int = 1,
        max_weight: float = 0.4,
        direction: str = "continuation",
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")
        if direction not in {"continuation", "reversion"}:
            raise ValueError("direction must be 'continuation' or 'reversion'")

        self.symbols = [s.upper() for s in symbols]
        self.lookback_bars = max(2, int(lookback_bars))
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.top_k = max(1, int(top_k))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self.direction = direction

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

        if len(ratios) < 2 * self.top_k:
            return None

        sorted_syms = sorted(ratios.keys(), key=lambda s: ratios[s])
        bottom = set(sorted_syms[: self.top_k])
        top = set(sorted_syms[-self.top_k :])

        if self.direction == "continuation":
            longs = top
            shorts = bottom
        else:
            longs = bottom
            shorts = top

        n_active = len(longs) + len(shorts)
        per_leg_weight = (
            min(self.max_weight, 1.0 / n_active) if n_active > 0 else 0.0
        )

        orders: dict[str, Order | None] = {}
        for symbol in self.symbols:
            current_side = self._position_side(state, symbol)
            if symbol in longs:
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
            elif symbol in shorts:
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
            else:
                orders[symbol] = self._close_order(current_side)

        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
