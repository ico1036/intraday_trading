"""xs_factor_wq053negdcloseposition_fwd_c10 — auto-generated XS factor.

Signal: wq_053_neg_d_close_position  direction=fwd  concentration=0.1
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
    "idea_family": "xs_factor_wq_053_neg_d_close_position_fwd_c10",
}
SOURCE_NOTES: list[str] = ["research/notes/xs_factor_zoo.md"]


class XsFactorWq053negdclosepositionFwdC10(XsFactorBase):
    HISTORY_FIELDS = ('close', 'high', 'low')
    HISTORY_LEN = 80

    def __init__(self, symbols: list[str], **kwargs: Any):
        kwargs.setdefault("concentration_pct", 0.1)
        kwargs.setdefault("reverse", False)
        super().__init__(symbols=symbols, **kwargs)

    def _compute_score(self, hist: dict[str, list[float]]) -> float | None:
        if len(hist['close']) < 10:
            return None
        try:
            return -((((hist['close'][-1]-hist['low'][-1]) - (hist['high'][-1]-hist['close'][-1])) / ((hist['close'][-1]-hist['low'][-1]) or 1e-9)) - (((hist['close'][-10]-hist['low'][-10]) - (hist['high'][-10]-hist['close'][-10])) / ((hist['close'][-10]-hist['low'][-10]) or 1e-9)))
        except Exception:
            return None
