"""is_621_xs_vs_btc_lk28d_r14d — basket top vs BTC spread."""
from __future__ import annotations
import math
from collections import deque
from typing import Any
from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME", "transform": "rolling_rank", "horizon": "multi_day",
    "universe": "pair", "exit": "signal_flip",
    "idea_family": "xs_vs_btc_lk28d_r14d",
}
SOURCE_NOTES: list[str] = ["research/notes/xs_vs_btc_lk28d_r14d.md"]


class XsVsBtcLk28dR14dStrategy:
    def __init__(self, symbols, lookback_bars=40320, rebalance_bars=20160, max_weight=0.3, **_):
        if not symbols: raise ValueError("symbols")
        self.symbols = [s.upper() for s in symbols]
        self.lookback = max(2, int(lookback_bars))
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._closes = {s: deque(maxlen=self.lookback+1) for s in self.symbols}
        self._bar_count = 0

    def _side(self, state, s):
        if not state.positions: return None
        info = state.positions.get(s); return None if not info else (info.get("side") if info.get("side") in {"LONG","SHORT"} else None)

    def generate_order(self, state):
        if state.panel is None: return None
        for s in self.symbols:
            d = state.panel.get(s)
            if not d: continue
            c = d.get("close")
            if c is None or float(c) <= 0: continue
            self._closes[s].append(float(c))
        self._bar_count += 1
        if self._bar_count % self.rebalance_bars != 0: return None

        rets = {}
        for s in self.symbols:
            cl = self._closes[s]
            if len(cl) < self.lookback+1: continue
            if cl[0] <= 0: continue
            rets[s] = math.log(cl[-1]/cl[0])
        if "BTCUSDT" not in rets: return None
        # Long the best non-BTC, short BTC
        non_btc = {s: r for s, r in rets.items() if s != "BTCUSDT"}
        if not non_btc: return None
        winner = max(non_btc, key=lambda s: non_btc[s])
        w = self.max_weight / 2

        orders = {}
        any_change = False
        for s in self.symbols:
            cs = self._side(state, s)
            if s == winner:
                if cs != "LONG":
                    orders[s] = Order(side=Side.BUY, quantity=0.0, weight=w, order_type=OrderType.MARKET)
                    any_change = True
            elif s == "BTCUSDT":
                if cs != "SHORT":
                    orders[s] = Order(side=Side.SELL, quantity=0.0, weight=w, order_type=OrderType.MARKET)
                    any_change = True
            else:
                if cs == "LONG":
                    orders[s] = Order(side=Side.SELL, quantity=0.0, order_type=OrderType.MARKET); any_change = True
                elif cs == "SHORT":
                    orders[s] = Order(side=Side.BUY, quantity=0.0, order_type=OrderType.MARKET); any_change = True
        return PortfolioOrder(orders=orders) if any_change else None
