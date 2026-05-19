"""xs_factor_retskew20d_rev_c10 — auto-generated XS factor.

Signal: ret_skew_20d  direction=rev  concentration=0.1
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
    "idea_family": "xs_factor_ret_skew_20d_rev_c10",
}
SOURCE_NOTES: list[str] = ["research/notes/xs_factor_zoo.md"]


class XsFactorRetskew20dRevC10(XsFactorBase):
    HISTORY_FIELDS = ('close',)
    HISTORY_LEN = 80

    def __init__(self, symbols: list[str], **kwargs: Any):
        kwargs.setdefault("concentration_pct", 0.1)
        kwargs.setdefault("reverse", True)
        super().__init__(symbols=symbols, **kwargs)

    def _compute_score(self, hist: dict[str, list[float]]) -> float | None:
        if len(hist['close']) < 21:
            return None
        try:
            return (lambda r=[hist['close'][-i]/hist['close'][-i-1]-1.0 for i in range(1,21)]: (sum((x - sum(r)/20)**3 for x in r)/20) / ((sum((x - sum(r)/20)**2 for x in r)/20)**1.5 or 1e-9))()
        except Exception:
            return None
