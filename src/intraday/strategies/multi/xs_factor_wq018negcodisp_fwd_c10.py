"""xs_factor_wq018negcodisp_fwd_c10 — auto-generated XS factor.

Signal: wq_018_neg_co_disp  direction=fwd  concentration=0.1
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
    "idea_family": "xs_factor_wq_018_neg_co_disp_fwd_c10",
}
SOURCE_NOTES: list[str] = ["research/notes/xs_factor_zoo.md"]


class XsFactorWq018negcodispFwdC10(XsFactorBase):
    HISTORY_FIELDS = ('open', 'close')
    HISTORY_LEN = 80

    def __init__(self, symbols: list[str], **kwargs: Any):
        kwargs.setdefault("concentration_pct", 0.1)
        kwargs.setdefault("reverse", False)
        super().__init__(symbols=symbols, **kwargs)

    def _compute_score(self, hist: dict[str, list[float]]) -> float | None:
        if len(hist['open']) < 10:
            return None
        try:
            return -(((sum((abs(hist['close'][-i]-hist['open'][-i]) - sum(abs(hist['close'][-j]-hist['open'][-j]) for j in range(1,6))/5)**2 for i in range(1,6))/4)**0.5) + (hist['close'][-1]-hist['open'][-1]))
        except Exception:
            return None
