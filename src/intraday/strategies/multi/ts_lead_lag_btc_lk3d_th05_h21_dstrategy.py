"""is_636_ts_lead_lag_btc_lk3d_th05_h21d — long alts if BTC recently up."""
from __future__ import annotations
import math
from collections import deque
from typing import Any
from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME", "transform": "raw", "horizon": "multi_day",
    "universe": "basket_full", "exit": "time_stop",
    "idea_family": "ts_lead_lag_btc_lk3d_th05_h21d",
}
SOURCE_NOTES: list[str] = ["research/notes/ts_lead_lag_btc_lk3d_th05_h21d.md"]


class TsLeadLagBtcLk3dTh05H21DStrategy:
    def __init__(self, symbols, btc_lookback=4320, btc_threshold=0.05,
                 rebalance_bars=240, hold_bars=30240, max_weight=0.1, **_):
        if not symbols: raise ValueError("symbols")
        self.symbols = [s.upper() for s in symbols]
        self.btc_lookback = max(2, int(btc_lookback))
        self.btc_threshold = float(btc_threshold)
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.hold_bars = max(1, int(hold_bars))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._btc_closes = deque(maxlen=self.btc_lookback+1)
        self._open_at: dict[str, int] = {}
        self._bar_count = 0

    def _side(self, state, s):
        if not state.positions: return None
        info = state.positions.get(s); return None if not info else (info.get("side") if info.get("side") in {"LONG","SHORT"} else None)

    def generate_order(self, state):
        if state.panel is None: return None
        btc = state.panel.get("BTCUSDT")
        if btc:
            c = btc.get("close")
            if c is not None and float(c) > 0:
                self._btc_closes.append(float(c))
        self._bar_count += 1

        orders, any_change = {}, False
        for s in self.symbols:
            cs = self._side(state, s); opened = self._open_at.get(s)
            if cs == "LONG" and opened is not None and self._bar_count - opened >= self.hold_bars:
                orders[s] = Order(side=Side.SELL, quantity=0.0, order_type=OrderType.MARKET)
                self._open_at.pop(s, None); any_change = True

        if self._bar_count % self.rebalance_bars == 0:
            if len(self._btc_closes) < self.btc_lookback+1: return PortfolioOrder(orders=orders) if any_change else None
            if self._btc_closes[0] <= 0: return PortfolioOrder(orders=orders) if any_change else None
            btc_ret = math.log(self._btc_closes[-1]/self._btc_closes[0])
            if btc_ret < self.btc_threshold:
                return PortfolioOrder(orders=orders) if any_change else None
            # BTC went up — long all alts (non-BTC) without position
            cands = [s for s in self.symbols if s != "BTCUSDT" and self._side(state, s) is None]
            n = len(cands); w = min(self.max_weight, 1.0/n) if n>0 else 0.0
            for s in cands:
                orders[s] = Order(side=Side.BUY, quantity=0.0, weight=w, order_type=OrderType.MARKET)
                self._open_at[s] = self._bar_count
                any_change = True
        return PortfolioOrder(orders=orders) if any_change else None
