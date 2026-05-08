"""BB-fade basket_topk session raw."""
from __future__ import annotations

from collections import deque
from statistics import mean, pstdev
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "raw",
    "horizon": "session",
    "universe": "basket_topk",
    "exit": "signal_flip",
    "idea_family": "bb_band_fade",
}
SOURCE_NOTES: list[str] = ["research/notes/bb_band_fade.md"]


class BbFadeBasketTopkRawStrategy:
    def __init__(
        self,
        symbols: list[str],
        window: int = 1440,
        k: float = 1.8,
        top_k: int = 2,
        rebalance_bars: int = 60,
        max_weight: float = 0.20,
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")
        self.symbols = [s.upper() for s in symbols]
        self.window = max(60, int(window))
        self.k = float(k)
        self.top_k = max(1, int(top_k))
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))

        self._closes: dict[str, deque[float]] = {
            s: deque(maxlen=self.window + 5) for s in self.symbols
        }
        self._bar_count = 0

    def _current_side(self, state: MarketState, symbol: str) -> str | None:
        if not state.positions:
            return None
        info = state.positions.get(symbol)
        if not info:
            return None
        side = info.get("side")
        return side if side in {"LONG", "SHORT"} else None

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

        self._bar_count += 1
        if self._bar_count % self.rebalance_bars != 0:
            return None

        ranked: list[tuple[str, float, str]] = []
        for s in self.symbols:
            closes = list(self._closes[s])
            if len(closes) < self.window:
                continue
            seg = closes[-self.window:]
            mu = mean(seg)
            sd = pstdev(seg) or 1e-12
            upper = mu + self.k * sd
            lower = mu - self.k * sd
            close = closes[-1]
            if close > upper:
                ranked.append((s, (close - upper) / sd, "SHORT"))
            elif close < lower:
                ranked.append((s, (lower - close) / sd, "LONG"))
        ranked.sort(key=lambda kv: kv[1], reverse=True)
        chosen = ranked[: self.top_k]
        target = {sym: side for sym, _, side in chosen}

        orders: dict[str, Order | None] = {}
        for s in self.symbols:
            cur = self._current_side(state, s)
            tgt = target.get(s)
            if tgt == "LONG":
                orders[s] = (
                    None
                    if cur == "LONG"
                    else Order(
                        side=Side.BUY, quantity=0.0,
                        weight=self.max_weight, order_type=OrderType.MARKET,
                    )
                )
            elif tgt == "SHORT":
                orders[s] = (
                    None
                    if cur == "SHORT"
                    else Order(
                        side=Side.SELL, quantity=0.0,
                        weight=self.max_weight, order_type=OrderType.MARKET,
                    )
                )
            else:
                orders[s] = None

        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
