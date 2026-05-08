"""BTC/ETH log-spread z-score mean-reversion (pair universe).

z = (log(BTC/ETH) - rolling_mean) / rolling_std over a trailing window.
When z > entry_z → expect reversion: SHORT BTC, LONG ETH.
When z < -entry_z → LONG BTC, SHORT ETH.
When |z| < exit_z → close both.
"""
from __future__ import annotations

from collections import deque
from math import log
from statistics import mean, pstdev
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "z_score",
    "horizon": "intraday",
    "universe": "pair",
    "exit": "neutral_zone",
    "idea_family": "pair_spread_meanrev",
}
SOURCE_NOTES: list[str] = ["research/notes/pair_spread_meanrev.md"]


class PairSpreadBtcEthStrategy:
    def __init__(
        self,
        symbols: list[str],
        leg_a: str = "BTCUSDT",
        leg_b: str = "ETHUSDT",
        lookback_bars: int = 480,    # 8h
        rebalance_bars: int = 30,    # 30 min
        entry_z: float = 1.5,
        exit_z: float = 0.3,
        max_weight: float = 0.18,
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")
        self.symbols = [s.upper() for s in symbols]
        self.leg_a = leg_a.upper()
        self.leg_b = leg_b.upper()
        if self.leg_a not in self.symbols or self.leg_b not in self.symbols:
            raise ValueError("legs must be in symbols")
        self.lookback_bars = max(20, int(lookback_bars))
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.entry_z = float(entry_z)
        self.exit_z = float(exit_z)
        self.max_weight = max(0.0, min(1.0, float(max_weight)))

        self._closes: dict[str, deque[float]] = {
            s: deque(maxlen=self.lookback_bars + 5) for s in self.symbols
        }
        self._spread: deque[float] = deque(maxlen=self.lookback_bars + 5)
        self._bar_count = 0

    def _z(self) -> float | None:
        a_closes = list(self._closes[self.leg_a])
        b_closes = list(self._closes[self.leg_b])
        if len(a_closes) < 2 or len(b_closes) < 2:
            return None
        if a_closes[-1] <= 0 or b_closes[-1] <= 0:
            return None
        s = log(a_closes[-1]) - log(b_closes[-1])
        self._spread.append(s)
        if len(self._spread) < self.lookback_bars:
            return None
        seg = list(self._spread)[-self.lookback_bars:]
        mu = mean(seg)
        sd = pstdev(seg) or 1e-12
        return (s - mu) / sd

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
        for s in self.symbols:
            d = state.panel.get(s)
            if not d:
                continue
            close = d.get("close")
            if close is not None and close > 0:
                self._closes[s].append(float(close))

        z = self._z()
        self._bar_count += 1
        if self._bar_count % self.rebalance_bars != 0:
            return None
        if z is None:
            return None

        orders: dict[str, Order | None] = {s: None for s in self.symbols}
        cur_a = self._current_side(state, self.leg_a)
        cur_b = self._current_side(state, self.leg_b)

        if z > self.entry_z:
            # spread too high → SHORT a, LONG b
            if cur_a != "SHORT":
                orders[self.leg_a] = Order(
                    side=Side.SELL, quantity=0.0,
                    weight=self.max_weight, order_type=OrderType.MARKET
                )
            if cur_b != "LONG":
                orders[self.leg_b] = Order(
                    side=Side.BUY, quantity=0.0,
                    weight=self.max_weight, order_type=OrderType.MARKET
                )
        elif z < -self.entry_z:
            if cur_a != "LONG":
                orders[self.leg_a] = Order(
                    side=Side.BUY, quantity=0.0,
                    weight=self.max_weight, order_type=OrderType.MARKET
                )
            if cur_b != "SHORT":
                orders[self.leg_b] = Order(
                    side=Side.SELL, quantity=0.0,
                    weight=self.max_weight, order_type=OrderType.MARKET
                )
        elif abs(z) < self.exit_z:
            orders[self.leg_a] = self._close_for_side(cur_a)
            orders[self.leg_b] = self._close_for_side(cur_b)

        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
