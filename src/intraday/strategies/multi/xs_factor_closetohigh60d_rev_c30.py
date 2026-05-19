"""xs_factor_closetohigh60d_rev_c30 — auto-generated XS factor.

Signal: close_to_high_60d  direction=rev  concentration=0.3
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
    "idea_family": "xs_factor_close_to_high_60d_rev_c30",
}
SOURCE_NOTES: list[str] = ["research/notes/xs_factor_zoo.md"]


class XsFactorClosetohigh60dRevC30(XsFactorBase):
    HISTORY_FIELDS = ('close',)
    HISTORY_LEN = 80

    def __init__(self, symbols: list[str], **kwargs: Any):
        kwargs.setdefault("concentration_pct", 0.3)
        kwargs.setdefault("reverse", True)
        super().__init__(symbols=symbols, **kwargs)

    def _compute_score(self, hist: dict[str, list[float]]) -> float | None:
        if len(hist['close']) < 60:
            return None
        try:
            return (hist['close'][-1] - min(hist['close'][-60:])) / (max(hist['close'][-60:]) - min(hist['close'][-60:]) or 1e-9)
        except Exception:
            return None
