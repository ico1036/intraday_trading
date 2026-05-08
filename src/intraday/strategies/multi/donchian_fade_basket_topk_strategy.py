"""Donchian fade session basket_topk."""
from __future__ import annotations

from collections import deque
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "raw",
    "horizon": "session",
    "universe": "basket_topk",
    "exit": "signal_flip",
    "idea_family": "donchian_fade",
}
SOURCE_NOTES: list[str] = ["research/notes/donchian_fade.md"]


class DonchianFadeBasketTopkStrategy:
    def __init__(
        self,
        symbols: list[str],
        channel_bars: int = 1440,
        top_k: int = 2,
        rebalance_bars: int = 60,
        max_weight: float = 0.20,
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")
        self.symbols = [s.upper() for s in symbols]
        self.channel_bars = max(60, int(channel_bars))
        self.top_k = max(1, int(top_k))
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))

        self._highs: dict[str, deque[float]] = {
            s: deque(maxlen=self.channel_bars + 5) for s in self.symbols
        }
        self._lows: dict[str, deque[float]] = {
            s: deque(maxlen=self.channel_bars + 5) for s in self.symbols
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
            high = d.get("high", close)
            low = d.get("low", close)
            if close is None or high is None or low is None:
                continue
            self._highs[s].append(float(high))
            self._lows[s].append(float(low))

        self._bar_count += 1
        if self._bar_count % self.rebalance_bars != 0:
            return None

        ranked: list[tuple[str, float, str]] = []
        for s in self.symbols:
            highs = list(self._highs[s])
            lows = list(self._lows[s])
            if len(highs) < self.channel_bars + 1:
                continue
            d_high = max(highs[-self.channel_bars - 1:-1])
            d_low = min(lows[-self.channel_bars - 1:-1])
            data = state.panel.get(s)
            if not data or data.get("close") is None:
                continue
            close = float(data["close"])
            channel_w = max(d_high - d_low, 1e-9)
            if close > d_high:
                ranked.append((s, (close - d_high) / channel_w, "SHORT"))
            elif close < d_low:
                ranked.append((s, (d_low - close) / channel_w, "LONG"))
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
