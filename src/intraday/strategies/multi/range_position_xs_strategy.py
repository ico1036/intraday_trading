"""Cross-sectional range-position mean reversion (intraday rebalance).

Per symbol compute Williams %R-style position p in [0,1] over the last
``range_bars`` bars: p = (close - low_N) / (high_N - low_N). Rank cross
sectionally; LONG bottom-rank (oversold), SHORT top-rank (overbought).
Neutral-zone exit when p drifts back to mid.
"""
from __future__ import annotations

from collections import deque
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "percentile",
    "horizon": "intraday",
    "universe": "basket_topk",
    "exit": "neutral_zone",
    "idea_family": "range_position_xs",
}
SOURCE_NOTES: list[str] = ["research/notes/range_position.md"]


class RangePositionXsStrategy:
    def __init__(
        self,
        symbols: list[str],
        range_bars: int = 480,       # 8h
        rebalance_bars: int = 120,   # 2h
        top_k: int = 2,
        max_weight: float = 0.16,
        entry_extreme: float = 0.10,  # |p - 0.5| > 0.40 => entry
        exit_extreme: float = 0.30,   # |p - 0.5| < 0.20 => close
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")
        self.symbols = [s.upper() for s in symbols]
        self.range_bars = max(10, int(range_bars))
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.top_k = max(1, int(top_k))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self.entry_extreme = float(entry_extreme)
        self.exit_extreme = float(exit_extreme)

        self._highs: dict[str, deque[float]] = {
            s: deque(maxlen=self.range_bars + 5) for s in self.symbols
        }
        self._lows: dict[str, deque[float]] = {
            s: deque(maxlen=self.range_bars + 5) for s in self.symbols
        }
        self._closes: dict[str, deque[float]] = {
            s: deque(maxlen=self.range_bars + 5) for s in self.symbols
        }
        self._bar_count = 0

    def _position(self, symbol: str) -> float | None:
        h = list(self._highs[symbol])
        lo = list(self._lows[symbol])
        c = list(self._closes[symbol])
        if len(c) < self.range_bars:
            return None
        seg_h = max(h[-self.range_bars:])
        seg_l = min(lo[-self.range_bars:])
        rng = seg_h - seg_l
        if rng <= 0:
            return None
        return (c[-1] - seg_l) / rng

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
            high = data.get("high", close)
            low = data.get("low", close)
            if close is None or high is None or low is None:
                continue
            self._closes[s].append(float(close))
            self._highs[s].append(float(high))
            self._lows[s].append(float(low))

        self._bar_count += 1
        if self._bar_count % self.rebalance_bars != 0:
            return None

        positions: dict[str, float] = {}
        for s in self.symbols:
            p = self._position(s)
            if p is not None:
                positions[s] = p
        if len(positions) < 2:
            return None

        # Bottom rank (oversold) → LONG; top rank (overbought) → SHORT
        ranked = sorted(positions.items(), key=lambda kv: kv[1])
        long_pick = [s for s, v in ranked[: self.top_k] if v < (0.5 - self.entry_extreme)]
        short_pick = [s for s, v in ranked[-self.top_k:] if v > (0.5 + self.entry_extreme)]

        orders: dict[str, Order | None] = {}
        for s in self.symbols:
            cur = self._current_side(state, s)
            p = positions.get(s)
            if s in long_pick:
                orders[s] = (
                    None
                    if cur == "LONG"
                    else Order(
                        side=Side.BUY,
                        quantity=0.0,
                        weight=self.max_weight,
                        order_type=OrderType.MARKET,
                    )
                )
            elif s in short_pick:
                orders[s] = (
                    None
                    if cur == "SHORT"
                    else Order(
                        side=Side.SELL,
                        quantity=0.0,
                        weight=self.max_weight,
                        order_type=OrderType.MARKET,
                    )
                )
            elif p is not None and abs(p - 0.5) < self.exit_extreme:
                orders[s] = self._close_for_side(cur)
            else:
                orders[s] = None

        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
