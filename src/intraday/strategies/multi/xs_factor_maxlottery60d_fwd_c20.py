"""xs_factor_maxlottery60d_fwd_c20 — auto-generated XS factor.

Signal: max_lottery_60d  direction=fwd  concentration=0.2
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
    "idea_family": "xs_factor_max_lottery_60d_fwd_c20",
}
SOURCE_NOTES: list[str] = ["research/notes/xs_factor_zoo.md"]


class XsFactorMaxlottery60dFwdC20(XsFactorBase):
    HISTORY_FIELDS = ('close',)
    HISTORY_LEN = 80

    def __init__(self, symbols: list[str], **kwargs: Any):
        kwargs.setdefault("concentration_pct", 0.2)
        kwargs.setdefault("reverse", False)
        super().__init__(symbols=symbols, **kwargs)

    def _compute_score(self, hist: dict[str, list[float]]) -> float | None:
        if len(hist['close']) < 61:
            return None
        try:
            return max(hist['close'][-i]/hist['close'][-i-1]-1.0 for i in range(1,61))
        except Exception:
            return None
