"""xs_factor_cci14d_rev_c30 — auto-generated XS factor.

Signal: cci_14d  direction=rev  concentration=0.3
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
    "idea_family": "xs_factor_cci_14d_rev_c30",
}
SOURCE_NOTES: list[str] = ["research/notes/xs_factor_zoo.md"]


class XsFactorCci14dRevC30(XsFactorBase):
    HISTORY_FIELDS = ('close',)
    HISTORY_LEN = 80

    def __init__(self, symbols: list[str], **kwargs: Any):
        kwargs.setdefault("concentration_pct", 0.3)
        kwargs.setdefault("reverse", True)
        super().__init__(symbols=symbols, **kwargs)

    def _compute_score(self, hist: dict[str, list[float]]) -> float | None:
        if len(hist['close']) < 14:
            return None
        try:
            return (lambda sma=sum(hist['close'][-14:])/14, mad=sum(abs(c - sum(hist['close'][-14:])/14) for c in hist['close'][-14:])/14: (hist['close'][-1] - sma) / (0.015 * (mad or 1e-9)))()
        except Exception:
            return None
