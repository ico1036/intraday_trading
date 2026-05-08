"""Cross-sectional dispersion mean-reversion with signal-flip exit.

Same idea family as is_012 (dispersion_meanrev_xs intraday) but the exit
swaps from neutral_zone (close on |z|<0.3) to signal_flip (close only when
the cross-sectional rank changes which symbol is in the extreme slot).
Cell exit value differs.
"""
from __future__ import annotations

from collections import deque
from statistics import mean, pstdev
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "z_score",
    "horizon": "intraday",
    "universe": "basket_topk",
    "exit": "signal_flip",
    "idea_family": "dispersion_meanrev_xs",
}
SOURCE_NOTES: list[str] = ["research/notes/dispersion_meanrev.md"]


class DispersionSignalFlipStrategy:
    def __init__(
        self,
        symbols: list[str],
        lookback_bars: int = 240,
        rebalance_bars: int = 240,   # 4h
        top_k: int = 2,
        max_weight: float = 0.16,
        entry_z: float = 1.0,
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")
        self.symbols = [s.upper() for s in symbols]
        self.lookback_bars = max(20, int(lookback_bars))
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.top_k = max(1, int(top_k))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self.entry_z = float(entry_z)

        self._closes: dict[str, deque[float]] = {
            s: deque(maxlen=self.lookback_bars + 2) for s in self.symbols
        }
        self._bar_count = 0

    def _residual_z(self) -> dict[str, float]:
        rets: dict[str, list[float]] = {}
        for s in self.symbols:
            closes = list(self._closes[s])
            if len(closes) < self.lookback_bars + 1:
                continue
            seg = closes[-(self.lookback_bars + 1):]
            r = []
            for prev, cur in zip(seg[:-1], seg[1:]):
                r.append((cur - prev) / prev if prev > 0 else 0.0)
            rets[s] = r
        if len(rets) < 2:
            return {}

        basket = []
        for i in range(self.lookback_bars):
            basket.append(mean([rets[s][i] for s in rets]))

        residuals: dict[str, list[float]] = {}
        for s, r in rets.items():
            residuals[s] = [ri - bi for ri, bi in zip(r, basket)]

        out: dict[str, float] = {}
        for s, res in residuals.items():
            cum_path: list[float] = []
            c = 0.0
            for x in res:
                c += x
                cum_path.append(c)
            if len(cum_path) < 5:
                continue
            sd = pstdev(cum_path) or 1e-9
            out[s] = cum_path[-1] / sd
        return out

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
            data = state.panel.get(s)
            if not data:
                continue
            close = data.get("close")
            if close is not None and close > 0:
                self._closes[s].append(float(close))

        self._bar_count += 1
        if self._bar_count % self.rebalance_bars != 0:
            return None

        z = self._residual_z()
        if not z:
            return None

        ranked = sorted(z.items(), key=lambda kv: kv[1])
        longs = [s for s, v in ranked[: self.top_k] if v <= -self.entry_z]
        shorts = [s for s, v in ranked[-self.top_k:] if v >= self.entry_z]
        target = {s: None for s in self.symbols}
        for s in longs:
            target[s] = "LONG"
        for s in shorts:
            target[s] = "SHORT"

        orders: dict[str, Order | None] = {}
        for s in self.symbols:
            cur = self._current_side(state, s)
            tgt = target[s]
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
                if cur == "LONG":
                    orders[s] = Order(side=Side.SELL, quantity=0.0, order_type=OrderType.MARKET)
                elif cur == "SHORT":
                    orders[s] = Order(side=Side.BUY, quantity=0.0, order_type=OrderType.MARKET)
                else:
                    orders[s] = None

        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
