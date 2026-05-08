"""Session-extreme revert basket_topk."""
from __future__ import annotations

from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "raw",
    "horizon": "session",
    "universe": "basket_topk",
    "exit": "signal_flip",
    "idea_family": "session_extreme_revert",
}
SOURCE_NOTES: list[str] = ["research/notes/session_extreme_revert.md"]


class SessionExtremeRevertBasketTopkStrategy:
    def __init__(
        self,
        symbols: list[str],
        warmup_minutes: int = 30,
        top_k: int = 2,
        max_weight: float = 0.20,
        rebalance_bars: int = 30,
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")
        self.symbols = [s.upper() for s in symbols]
        self.warmup_minutes = max(5, int(warmup_minutes))
        self.top_k = max(1, int(top_k))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self.rebalance_bars = max(1, int(rebalance_bars))

        self._sess_high: dict[str, float | None] = {s: None for s in self.symbols}
        self._sess_low: dict[str, float | None] = {s: None for s in self.symbols}
        self._sess_open: dict[str, float | None] = {s: None for s in self.symbols}
        self._current_day: int | None = None
        self._bar_count = 0

    def _reset(self) -> None:
        for s in self.symbols:
            self._sess_high[s] = None
            self._sess_low[s] = None
            self._sess_open[s] = None

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
        ts = state.timestamp
        day = ts.toordinal()
        minute_of_day = ts.hour * 60 + ts.minute

        if self._current_day is None or day != self._current_day:
            self._current_day = day
            self._reset()

        for s in self.symbols:
            d = state.panel.get(s)
            if not d:
                continue
            high = d.get("high")
            low = d.get("low")
            close = d.get("close")
            if high is None and close is not None:
                high = close
            if low is None and close is not None:
                low = close
            if high is None or low is None:
                continue
            cur_h = self._sess_high[s]
            cur_l = self._sess_low[s]
            self._sess_high[s] = high if cur_h is None else max(cur_h, float(high))
            self._sess_low[s] = low if cur_l is None else min(cur_l, float(low))
            if self._sess_open[s] is None and close is not None:
                self._sess_open[s] = float(close)

        if minute_of_day < self.warmup_minutes:
            return None

        self._bar_count += 1
        if self._bar_count % self.rebalance_bars != 0:
            return None

        # Rank by stretch from open: stretch = (close - open) / open
        ranked: list[tuple[str, float, str]] = []
        for s in self.symbols:
            d = state.panel.get(s)
            if not d:
                continue
            close = d.get("close")
            sh = self._sess_high.get(s)
            sl = self._sess_low.get(s)
            so = self._sess_open.get(s)
            if close is None or sh is None or sl is None or so is None or so <= 0:
                continue
            stretch = (close - so) / so
            # SHORT if at session high & stretched up
            if close >= sh - 1e-9 and stretch > 0:
                ranked.append((s, stretch, "SHORT"))
            elif close <= sl + 1e-9 and stretch < 0:
                ranked.append((s, -stretch, "LONG"))

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
