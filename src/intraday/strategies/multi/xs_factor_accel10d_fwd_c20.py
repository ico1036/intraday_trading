"""xs_factor_accel10d_fwd_c20 — auto-generated XS factor.

Signal: accel_10d  direction=fwd  concentration=0.2
Cross-sectional rank of ``_compute_score`` over the eligible
universe each emit bar, top/bottom concentration_pct legs.
"""
from __future__ import annotations

import math
from typing import Any

from intraday.strategies._xs_factor_base import XsFactorBase


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "rolling_rank",
    "horizon": "multi_day",
    "universe": "basket_full",
    "exit": "signal_flip",
    "idea_family": "xs_factor_accel_10d_fwd_c20",
}
SOURCE_NOTES: list[str] = ["research/notes/xs_factor_zoo.md"]


class XsFactorAccel10dFwdC20(XsFactorBase):
    HISTORY_FIELDS = ('close',)
    HISTORY_LEN = 80

    def __init__(self, symbols: list[str], **kwargs: Any):
        kwargs.setdefault("concentration_pct", 0.2)
        kwargs.setdefault("reverse", False)
        super().__init__(symbols=symbols, **kwargs)

    def _compute_score(self, hist: dict[str, list[float]]) -> float | None:
        if len(hist['close']) < 11:
            return None
        try:
            return (hist['close'][-1] - 2*hist['close'][-6] + hist['close'][-11]) / (hist['close'][-6] or 1e-9)
        except Exception:
            return None
