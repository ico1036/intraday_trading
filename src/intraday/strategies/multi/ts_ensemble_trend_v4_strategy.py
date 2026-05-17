"""is_107_ts_ensemble_trend_v4 — ensemble of 3 trend-filter slots."""
from __future__ import annotations

import math
from collections import deque
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "composite",
    "horizon": "multi_day",
    "universe": "basket_full",
    "exit": "time_stop",
    "idea_family": "ts_ensemble_trend_v4",
}
SOURCE_NOTES: list[str] = ["research/notes/ts_ensemble_trend_v4.md"]

_SLOTS = [(7200, 14400, 7200), (7200, 20160, 7200), (7200, 30240, 10080)]  # list of (fast, slow, hold)


class TsEnsembleTrendV4Strategy:
    def __init__(self, symbols, slots=None, rebalance_bars=240, max_weight_per_slot=0.07, **_):
        if not symbols: raise ValueError("symbols")
        self.symbols = [s.upper() for s in symbols]
        self.slots = slots if slots is not None else _SLOTS
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.max_weight_per_slot = max(0.0, min(1.0, float(max_weight_per_slot)))

        # one set of state dicts per (slot_index, symbol)
        self._fast_h = []; self._fast_l = []; self._slow_h = []; self._slow_l = []; self._closes = []
        self._regime = []; self._open_at = []; self._has_traded = []
        for fast, slow, hold in self.slots:
            self._fast_h.append({s: deque(maxlen=fast) for s in self.symbols})
            self._fast_l.append({s: deque(maxlen=fast) for s in self.symbols})
            self._slow_h.append({s: deque(maxlen=slow) for s in self.symbols})
            self._slow_l.append({s: deque(maxlen=slow) for s in self.symbols})
            self._closes.append({s: deque(maxlen=slow) for s in self.symbols})
            self._regime.append({s: 0 for s in self.symbols})
            self._open_at.append({})
            self._has_traded.append({s: False for s in self.symbols})
        self._bar_count = 0

    def _side(self, state, s):
        if not state.positions: return None
        info = state.positions.get(s); return None if not info else (info.get("side") if info.get("side") in {"LONG", "SHORT"} else None)

    def generate_order(self, state):
        if state.panel is None: return None
        for s in self.symbols:
            d = state.panel.get(s)
            if not d: continue
            h, l, c = d.get("high"), d.get("low"), d.get("close")
            if h is None or l is None or c is None: continue
            for i in range(len(self.slots)):
                self._fast_h[i][s].append(float(h)); self._fast_l[i][s].append(float(l))
                self._slow_h[i][s].append(float(h)); self._slow_l[i][s].append(float(l))
                self._closes[i][s].append(float(c))
        self._bar_count += 1

        # Aggregate desired direction across slots: net = sum of slot signals.
        # Each slot can independently OPEN / TIME-STOP its 'virtual' position.
        # We translate the AGGREGATE virtual exposure to a single real position
        # per symbol (broker only allows one), with weight scaled by total slot
        # exposure (each slot contributes max_weight_per_slot when active).
        #
        # First: do time-stops for each slot.
        for i, (fast, slow, hold) in enumerate(self.slots):
            for s in self.symbols:
                opened = self._open_at[i].get(s)
                if opened is not None and self._bar_count - opened >= hold:
                    self._open_at[i].pop(s, None)
                    # virtual close — handled in aggregation below

        if self._bar_count % self.rebalance_bars != 0:
            return None

        # Update slot regimes + decide each slot's intended direction at this bar.
        slot_dir = []  # per slot: dict[s -> +1/-1/0]
        for i, (fast, slow, hold) in enumerate(self.slots):
            slot_dir.append({})
            for s in self.symbols:
                if len(self._fast_h[i][s]) < fast: continue
                if len(self._slow_h[i][s]) < slow: continue
                if not self._closes[i][s]: continue
                fhi = max(self._fast_h[i][s]); flo = min(self._fast_l[i][s])
                shi = max(self._slow_h[i][s]); slo = min(self._slow_l[i][s])
                close = self._closes[i][s][-1]
                if not all(map(math.isfinite, [fhi, flo, shi, slo, close])): continue
                prev_reg = self._regime[i][s]
                if close >= shi: self._regime[i][s] = +1
                elif close <= slo: self._regime[i][s] = -1
                if self._regime[i][s] != prev_reg:
                    self._has_traded[i][s] = False
                reg = self._regime[i][s]
                opened = self._open_at[i].get(s)
                # Slot considers itself "in trade" if open_at is set.
                if opened is None:
                    if reg > 0 and ((close >= fhi) or self._has_traded[i][s]):
                        slot_dir[i][s] = +1
                        self._open_at[i][s] = self._bar_count
                        self._has_traded[i][s] = True
                    elif reg < 0 and ((close <= flo) or self._has_traded[i][s]):
                        slot_dir[i][s] = -1
                        self._open_at[i][s] = self._bar_count
                        self._has_traded[i][s] = True
                else:
                    # Already holding a virtual position for this slot in same direction
                    slot_dir[i][s] = +1 if reg > 0 else (-1 if reg < 0 else 0)

        # Aggregate target weight per symbol = max_weight_per_slot * sum of slot_dir
        target_weight = {s: 0.0 for s in self.symbols}
        for i, sd in enumerate(slot_dir):
            for s, d in sd.items():
                target_weight[s] += d * self.max_weight_per_slot

        # Cap aggregate weight to keep total exposure ≤ 1.0
        sum_abs = sum(abs(w) for w in target_weight.values())
        if sum_abs > 1.0:
            scale = 1.0 / sum_abs
            target_weight = {s: w * scale for s, w in target_weight.items()}

        orders = {}
        any_change = False
        for s in self.symbols:
            tw = target_weight[s]
            cs = self._side(state, s)
            if abs(tw) < 1e-9:
                if cs is not None:
                    orders[s] = Order(side=Side.SELL if cs == "LONG" else Side.BUY, quantity=0.0, order_type=OrderType.MARKET)
                    any_change = True
            else:
                want_long = tw > 0
                if want_long and cs != "LONG":
                    orders[s] = Order(side=Side.BUY, quantity=0.0, weight=abs(tw), order_type=OrderType.MARKET)
                    any_change = True
                elif (not want_long) and cs != "SHORT":
                    orders[s] = Order(side=Side.SELL, quantity=0.0, weight=abs(tw), order_type=OrderType.MARKET)
                    any_change = True
        return PortfolioOrder(orders=orders) if any_change else None
