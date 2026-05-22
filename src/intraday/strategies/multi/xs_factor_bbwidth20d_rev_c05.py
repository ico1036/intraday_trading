"""xs_factor_bbwidth20d_rev_c05 — auto-generated XS factor.

Signal: bb_width_20d  direction=rev  concentration=0.05
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
    "idea_family": "xs_factor_bb_width_20d_rev_c05",
}
SOURCE_NOTES: list[str] = ["research/notes/xs_factor_zoo.md"]


class XsFactorBbwidth20dRevC05(XsFactorBase):
    HISTORY_FIELDS = ('close',)
    HISTORY_LEN = 80

    def __init__(self, symbols: list[str], **kwargs: Any):
        kwargs.setdefault("concentration_pct", 0.05)
        kwargs.setdefault("reverse", True)
        super().__init__(symbols=symbols, **kwargs)

    def _compute_score(self, hist: dict[str, list[float]]) -> float | None:
        if len(hist['close']) < 20:
            return None
        try:
            return ((sum((c - sum(hist['close'][-20:])/20)**2 for c in hist['close'][-20:])/19)**0.5) / (sum(hist['close'][-20:])/20 or 1e-9)
        except Exception:
            return None
