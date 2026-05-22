"""xs_factor_marefficiency252d_rev_c05 — auto-generated XS factor.

Signal: mar_efficiency_252d  direction=rev  concentration=0.05
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
    "idea_family": "xs_factor_mar_efficiency_252d_rev_c05",
}
SOURCE_NOTES: list[str] = ["research/notes/xs_factor_zoo.md"]


class XsFactorMarefficiency252dRevC05(XsFactorBase):
    HISTORY_FIELDS = ('close',)
    HISTORY_LEN = 254

    def __init__(self, symbols: list[str], **kwargs: Any):
        kwargs.setdefault("concentration_pct", 0.05)
        kwargs.setdefault("reverse", True)
        super().__init__(symbols=symbols, **kwargs)

    def _compute_score(self, hist: dict[str, list[float]]) -> float | None:
        if len(hist['close']) < 253:
            return None
        try:
            return abs(hist['close'][-1]/hist['close'][-253]-1.0) / (sum(abs(hist['close'][-i]/hist['close'][-i-1]-1.0) for i in range(1,253)) or 1e-9)
        except Exception:
            return None
