"""xs_factor_illiqamihud20d_rev_c05 — auto-generated XS factor.

Signal: illiq_amihud_20d  direction=rev  concentration=0.05
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
    "idea_family": "xs_factor_illiq_amihud_20d_rev_c05",
}
SOURCE_NOTES: list[str] = ["research/notes/xs_factor_zoo.md"]


class XsFactorIlliqamihud20dRevC05(XsFactorBase):
    HISTORY_FIELDS = ('close', 'quote_volume')
    HISTORY_LEN = 80

    def __init__(self, symbols: list[str], **kwargs: Any):
        kwargs.setdefault("concentration_pct", 0.05)
        kwargs.setdefault("reverse", True)
        super().__init__(symbols=symbols, **kwargs)

    def _compute_score(self, hist: dict[str, list[float]]) -> float | None:
        if len(hist['close']) < 21:
            return None
        try:
            return sum(abs(hist['close'][-i]/hist['close'][-i-1]-1.0) / (hist['quote_volume'][-i] or 1e-9) for i in range(1,21))/20
        except Exception:
            return None
