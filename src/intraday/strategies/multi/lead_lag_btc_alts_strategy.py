"""BTC leads alts: trade alt direction = sign of recent BTC return.

At each rebalance, compute BTC's trailing N-bar return; LONG all alts when
return > entry threshold, SHORT when < -entry. Hold to signal flip. BTC
itself is held as a small same-direction position to maintain basket
alignment with the signal.
"""
from __future__ import annotations

from collections import deque
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "raw",
    "horizon": "intraday",
    "universe": "basket_full",
    "exit": "signal_flip",
    "idea_family": "lead_lag_btc",
}
SOURCE_NOTES: list[str] = ["research/notes/lead_lag_btc.md"]


class LeadLagBtcAltsStrategy:
    def __init__(
        self,
        symbols: list[str],
        signal_bars: int = 30,
        rebalance_bars: int = 30,
        entry_threshold: float = 0.005,
        exit_threshold: float = 0.001,
        max_weight_alt: float = 0.13,
        max_weight_btc: float = 0.10,
        leader: str = "BTCUSDT",
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")
        self.symbols = [s.upper() for s in symbols]
        self.leader = leader.upper()
        if self.leader not in self.symbols:
            raise ValueError(f"leader {self.leader} not in symbols")
        self.signal_bars = max(2, int(signal_bars))
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.entry_threshold = float(entry_threshold)
        self.exit_threshold = float(exit_threshold)
        self.max_weight_alt = max(0.0, min(1.0, float(max_weight_alt)))
        self.max_weight_btc = max(0.0, min(1.0, float(max_weight_btc)))

        self._closes: dict[str, deque[float]] = {
            s: deque(maxlen=self.signal_bars + 5) for s in self.symbols
        }
        self._bar_count = 0

    def _signal(self) -> float | None:
        closes = list(self._closes[self.leader])
        if len(closes) < self.signal_bars + 1:
            return None
        old = closes[-self.signal_bars - 1]
        if old <= 0:
            return None
        return (closes[-1] - old) / old

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
            data = state.panel.get(s)
            if not data:
                continue
            close = data.get("close")
            if close is not None and close > 0:
                self._closes[s].append(float(close))

        self._bar_count += 1
        if self._bar_count % self.rebalance_bars != 0:
            return None

        sig = self._signal()
        if sig is None:
            return None

        orders: dict[str, Order | None] = {}
        if sig > self.entry_threshold:
            for s in self.symbols:
                cur = self._current_side(state, s)
                w = self.max_weight_btc if s == self.leader else self.max_weight_alt
                orders[s] = (
                    None
                    if cur == "LONG"
                    else Order(
                        side=Side.BUY,
                        quantity=0.0,
                        weight=w,
                        order_type=OrderType.MARKET,
                    )
                )
        elif sig < -self.entry_threshold:
            for s in self.symbols:
                cur = self._current_side(state, s)
                w = self.max_weight_btc if s == self.leader else self.max_weight_alt
                orders[s] = (
                    None
                    if cur == "SHORT"
                    else Order(
                        side=Side.SELL,
                        quantity=0.0,
                        weight=w,
                        order_type=OrderType.MARKET,
                    )
                )
        elif abs(sig) < self.exit_threshold:
            for s in self.symbols:
                cur = self._current_side(state, s)
                orders[s] = self._close_for_side(cur)

        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
