"""ORB-fade multi_day topk ewma_residual."""
from __future__ import annotations

from collections import deque
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "ewma_residual",
    "horizon": "multi_day",
    "universe": "basket_topk",
    "exit": "signal_flip",
    "idea_family": "orb_fade",
}
SOURCE_NOTES: list[str] = ["research/notes/orb_fade.md"]


class OrbFadeMultidayTopkEwmaStrategy:
    def __init__(self, symbols, top_k=3, or_minutes=30, lookback_days=3, alpha=0.1, entry_thr=0.05,
                 max_weight=0.25, **_):
        self.symbols = [s.upper() for s in symbols]
        self.top_k = max(1, int(top_k))
        self.or_minutes = max(5, int(or_minutes))
        self.lookback_days = max(2, int(lookback_days))
        self.alpha = float(alpha)
        self.entry_thr = float(entry_thr)
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._or_high_today = {s: None for s in self.symbols}
        self._or_low_today = {s: None for s in self.symbols}
        self._past_or = {s: deque(maxlen=self.lookback_days) for s in self.symbols}
        self._mag_ewma = {s: None for s in self.symbols}
        self._day = None

    def _reset(self):
        for s in self.symbols:
            if self._or_high_today[s] is not None and self._or_low_today[s] is not None:
                self._past_or[s].append((self._or_high_today[s], self._or_low_today[s]))
            self._or_high_today[s] = None; self._or_low_today[s] = None

    def _current_side(self, state, sym):
        if not state.positions: return None
        info = state.positions.get(sym)
        if not info: return None
        side = info.get("side")
        return side if side in {"LONG", "SHORT"} else None

    def generate_order(self, state):
        if state.panel is None: return None
        ts = state.timestamp
        day = ts.toordinal()
        if self._day != day:
            self._reset(); self._day = day
        m = ts.hour * 60 + ts.minute
        if m < self.or_minutes:
            for s in self.symbols:
                d = state.panel.get(s)
                if not d: continue
                hi = d.get("high"); lo = d.get("low"); cl = d.get("close")
                if hi is None and cl is not None: hi = cl
                if lo is None and cl is not None: lo = cl
                if hi is None or lo is None: continue
                self._or_high_today[s] = hi if self._or_high_today[s] is None else max(self._or_high_today[s], float(hi))
                self._or_low_today[s] = lo if self._or_low_today[s] is None else min(self._or_low_today[s], float(lo))
            return None
        candidates = []
        for s in self.symbols:
            d = state.panel.get(s)
            if not d: continue
            cl = d.get("close")
            if cl is None: continue
            past = list(self._past_or[s])
            if not past or self._or_high_today[s] is None: continue
            all_highs = [h for h, _ in past] + [self._or_high_today[s]]
            all_lows = [l for _, l in past] + [self._or_low_today[s]]
            multi_hi = max(all_highs); multi_lo = min(all_lows)
            mw = max(multi_hi - multi_lo, 1e-9)
            mag = 0.0; tgt = None
            if cl > multi_hi: mag = (cl - multi_hi) / mw + 0.001; tgt = "SHORT"
            elif cl < multi_lo: mag = (multi_lo - cl) / mw + 0.001; tgt = "LONG"
            if tgt is None: continue
            ema = self._mag_ewma[s]
            ema_new = mag if ema is None else self.alpha * mag + (1 - self.alpha) * ema
            self._mag_ewma[s] = ema_new
            if ema is not None and (mag - ema) < self.entry_thr: continue
            score = mag if ema is None else mag - ema
            candidates.append((s, tgt, score))
        if not candidates: return None
        candidates.sort(key=lambda x: -x[2])
        chosen = {s: t for s, t, _ in candidates[: self.top_k]}
        orders = {s: None for s in self.symbols}
        for s, tgt in chosen.items():
            cur = self._current_side(state, s)
            if tgt == "SHORT" and cur != "SHORT":
                orders[s] = Order(side=Side.SELL, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
            elif tgt == "LONG" and cur != "LONG":
                orders[s] = Order(side=Side.BUY, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
        active = {s: o for s, o in orders.items() if o is not None}
        if not active: return None
        return PortfolioOrder(orders=orders)
