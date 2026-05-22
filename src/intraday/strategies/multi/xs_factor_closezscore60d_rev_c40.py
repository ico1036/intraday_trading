"""xs_factor_closezscore60d_rev_c40 — auto-generated XS factor.

Signal: close_zscore_60d  direction=rev  concentration=0.4
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
    "idea_family": "xs_factor_close_zscore_60d_rev_c40",
}
SOURCE_NOTES: list[str] = ["research/notes/xs_factor_zoo.md"]


class XsFactorClosezscore60dRevC40(XsFactorBase):
    HISTORY_FIELDS = ('close',)
    HISTORY_LEN = 80

    def __init__(self, symbols: list[str], **kwargs: Any):
        kwargs.setdefault("concentration_pct", 0.4)
        kwargs.setdefault("reverse", True)
        super().__init__(symbols=symbols, **kwargs)

    def _compute_score(self, hist: dict[str, list[float]]) -> float | None:
        if len(hist['close']) < 60:
            return None
        try:
            return (hist['close'][-1] - sum(hist['close'][-60:])/60) / (((sum((c - sum(hist['close'][-60:])/60)**2 for c in hist['close'][-60:]))/59)**0.5 or 1e-9)
        except Exception:
            return None
