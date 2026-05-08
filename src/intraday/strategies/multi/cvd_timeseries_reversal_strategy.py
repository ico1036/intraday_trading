"""is_006 — per-symbol time-series CVD reversal, top-k.

Mirrors the design that produced the is_001 winner (OpenSearchAlpha
trend_reversal idea) but on the orderflow primitive: signal is the
negative of a per-symbol z-score of recent CVD ratio against its own
historical distribution. Cross-sectional top-k longs by score, bottom-k
shorts.

Why this differs from is_002–is_005:
    - per-symbol z-score (vs cross-sectional)
    - normalized against the symbol's own CVD distribution, not against
      other symbols at the same instant
    - reversal sign (extreme buy aggression → short, exhaustion → long)
    - rebalance hourly, lookback 2h fast / 1d historical std
"""
from __future__ import annotations

import math
from collections import deque
from statistics import mean, pstdev
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


class CvdTimeseriesReversalStrategy:
    def __init__(
        self,
        symbols: list[str],
        fast_window: int = 120,
        slow_window: int = 1440,
        rebalance_bars: int = 60,
        top_k: int = 2,
        max_weight: float = 0.2,
        entry_z: float = 1.0,
        exit_z: float = 0.3,
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")
        if slow_window <= fast_window:
            raise ValueError("slow_window must exceed fast_window")

        self.symbols = [s.upper() for s in symbols]
        self.fast_window = max(2, int(fast_window))
        self.slow_window = max(self.fast_window + 1, int(slow_window))
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.top_k = max(1, int(top_k))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self.entry_z = float(entry_z)
        self.exit_z = float(exit_z)

        self._signed_vol: dict[str, deque[float]] = {
            s: deque(maxlen=self.slow_window + 5) for s in self.symbols
        }
        self._total_vol: dict[str, deque[float]] = {
            s: deque(maxlen=self.slow_window + 5) for s in self.symbols
        }
        self._bar_count = 0

    def _rolling_cvd_series(self, symbol: str) -> list[float]:
        """Build a list of fast-window CVD ratios stepped over slow_window."""
        sv = list(self._signed_vol[symbol])
        tv = list(self._total_vol[symbol])
        if len(sv) < self.slow_window:
            return []
        out: list[float] = []
        # iterate window endings within the slow_window most recent bars
        end_lo = len(sv) - self.slow_window + self.fast_window
        for end in range(end_lo, len(sv) + 1):
            seg_sv = sv[end - self.fast_window : end]
            seg_tv = tv[end - self.fast_window : end]
            total = sum(seg_tv)
            if total <= 0:
                continue
            out.append(sum(seg_sv) / total)
        return out

    def _score(self, symbol: str) -> float | None:
        series = self._rolling_cvd_series(symbol)
        if len(series) < 5:
            return None
        recent = series[-1]
        history = series[:-1]
        sigma = pstdev(history) if len(history) > 2 else 0.0
        if sigma <= 0 or not math.isfinite(sigma):
            return None
        z = (recent - mean(history)) / sigma
        if not math.isfinite(z):
            return None
        return -z  # reversal

    def _position_side(self, state: MarketState, symbol: str) -> str | None:
        if not state.positions:
            return None
        info = state.positions.get(symbol)
        if not info:
            return None
        side = info.get("side")
        return side if side in {"LONG", "SHORT"} else None

    def _close_order(self, side: str | None) -> Order | None:
        if side == "LONG":
            return Order(side=Side.SELL, quantity=0.0, order_type=OrderType.MARKET)
        if side == "SHORT":
            return Order(side=Side.BUY, quantity=0.0, order_type=OrderType.MARKET)
        return None

    def generate_order(self, state: MarketState) -> PortfolioOrder | None:
        if state.panel is None:
            return None

        for symbol in self.symbols:
            data = state.panel.get(symbol)
            if not data:
                continue
            vol = data.get("volume")
            imb = data.get("volume_imbalance")
            if vol is None or imb is None:
                continue
            v = float(vol)
            i = float(imb)
            if not (math.isfinite(v) and math.isfinite(i)) or v <= 0:
                continue
            self._signed_vol[symbol].append(i * v)
            self._total_vol[symbol].append(v)

        self._bar_count += 1
        if self._bar_count % self.rebalance_bars != 0:
            return None

        scores: dict[str, float] = {}
        for symbol in self.symbols:
            s = self._score(symbol)
            if s is not None:
                scores[symbol] = s

        if len(scores) < 2 * self.top_k:
            return None

        sorted_syms = sorted(scores.keys(), key=lambda s: scores[s])
        bottom = set(sorted_syms[: self.top_k])
        top = set(sorted_syms[-self.top_k :])

        longs = {s for s in top if scores[s] > self.entry_z}
        shorts = {s for s in bottom if scores[s] < -self.entry_z}

        n_active = len(longs) + len(shorts)
        per_leg_weight = (
            min(self.max_weight, 1.0 / n_active) if n_active > 0 else 0.0
        )

        orders: dict[str, Order | None] = {}
        for symbol in self.symbols:
            current_side = self._position_side(state, symbol)
            score = scores.get(symbol)
            if symbol in longs:
                orders[symbol] = (
                    None
                    if current_side == "LONG"
                    else Order(
                        side=Side.BUY,
                        quantity=0.0,
                        weight=per_leg_weight,
                        order_type=OrderType.MARKET,
                    )
                )
            elif symbol in shorts:
                orders[symbol] = (
                    None
                    if current_side == "SHORT"
                    else Order(
                        side=Side.SELL,
                        quantity=0.0,
                        weight=per_leg_weight,
                        order_type=OrderType.MARKET,
                    )
                )
            elif score is not None and abs(score) < self.exit_z:
                orders[symbol] = self._close_order(current_side)
            else:
                orders[symbol] = None

        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
