"""Execution cost models shared by the backtest runners.

Slippage: a half-spread tier on the symbol's trailing 30-bar median quote
volume plus a square-root impact term,

    bps = half_spread(ADV) + 0.5 * vol20 * sqrt(notional / ADV) * 1e4

with ADV tiers (USDT/day) > 50M: 0.5, > 10M: 1.5, > 5M: 3, > 1M: 6, else 12,
and 6 bps with no impact while fewer than 10 bars are known. vol20 is the
20-bar close-to-close return standard deviation (0.05 until known). The
constants are the ones the funding study priced the live window with
(research/notes/funding_tail_onset.md); on that book they came to ~7 bps per
unit notional, 87% of short notional sitting in names under 5M ADV.
"""
from __future__ import annotations

import math
from collections import deque

SLIPPAGE_MODELS = {None, "adv_tier"}
ADV_WINDOW = 30
ADV_MIN_BARS = 10
VOL_WINDOW = 20
VOL_DEFAULT = 0.05
IMPACT_COEF = 0.5
HALF_SPREAD_TIERS = ((5e7, 0.5), (1e7, 1.5), (5e6, 3.0), (1e6, 6.0))
HALF_SPREAD_FLOOR = 12.0
HALF_SPREAD_UNKNOWN = 6.0


class SlippageState:
    """Trailing quote-volume and close history for one symbol."""

    __slots__ = ("qv", "closes")

    def __init__(self) -> None:
        self.qv: deque[float] = deque(maxlen=ADV_WINDOW)
        self.closes: deque[float] = deque(maxlen=VOL_WINDOW + 1)

    def push(self, quote_volume: float, close: float) -> None:
        self.qv.append(float(quote_volume) if quote_volume else 0.0)
        self.closes.append(float(close))

    def adv(self) -> float | None:
        if len(self.qv) < ADV_MIN_BARS:
            return None
        xs = sorted(self.qv)
        n = len(xs)
        mid = n // 2
        return xs[mid] if n % 2 else 0.5 * (xs[mid - 1] + xs[mid])

    def vol(self) -> float:
        c = self.closes
        if len(c) < VOL_WINDOW + 1:
            return VOL_DEFAULT
        rets = [c[i] / c[i - 1] - 1.0 for i in range(1, len(c)) if c[i - 1] > 0]
        if len(rets) < 2:
            return VOL_DEFAULT
        m = sum(rets) / len(rets)
        return math.sqrt(sum((r - m) ** 2 for r in rets) / (len(rets) - 1))


def half_spread_bps(adv: float | None) -> float:
    if adv is None:
        return HALF_SPREAD_UNKNOWN
    for floor, bps in HALF_SPREAD_TIERS:
        if adv > floor:
            return bps
    return HALF_SPREAD_FLOOR


def slippage_bps(model: str | None, state: SlippageState | None, notional: float) -> float:
    """Total slippage in bps of notional for a trade of ``notional``."""
    if model is None:
        return 0.0
    if model != "adv_tier":
        raise ValueError(f"unknown slippage model {model!r}")
    adv = state.adv() if state is not None else None
    bps = half_spread_bps(adv)
    if adv and adv > 0 and notional > 0:
        vol = state.vol() if state is not None else VOL_DEFAULT
        bps += IMPACT_COEF * vol * math.sqrt(notional / adv) * 1e4
    return bps
