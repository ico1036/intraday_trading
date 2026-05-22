"""xs_factor_tradecountgrowth5d_fwd_c30 — auto-generated XS factor.

Signal: trade_count_growth_5d  direction=fwd  concentration=0.3
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
    "idea_family": "xs_factor_trade_count_growth_5d_fwd_c30",
}
SOURCE_NOTES: list[str] = ["research/notes/xs_factor_zoo.md"]


class XsFactorTradecountgrowth5dFwdC30(XsFactorBase):
    HISTORY_FIELDS = ('trade_count',)
    HISTORY_LEN = 80

    def __init__(self, symbols: list[str], **kwargs: Any):
        kwargs.setdefault("concentration_pct", 0.3)
        kwargs.setdefault("reverse", False)
        super().__init__(symbols=symbols, **kwargs)

    def _compute_score(self, hist: dict[str, list[float]]) -> float | None:
        if len(hist['trade_count']) < 6:
            return None
        try:
            return hist['trade_count'][-1] / (sum(hist['trade_count'][-6:-1])/5 or 1e-9) - 1.0
        except Exception:
            return None
