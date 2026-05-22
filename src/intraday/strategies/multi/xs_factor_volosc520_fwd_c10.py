"""xs_factor_volosc520_fwd_c10 — auto-generated XS factor.

Signal: vol_osc_5_20  direction=fwd  concentration=0.1
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
    "idea_family": "xs_factor_vol_osc_5_20_fwd_c10",
}
SOURCE_NOTES: list[str] = ["research/notes/xs_factor_zoo.md"]


class XsFactorVolosc520FwdC10(XsFactorBase):
    HISTORY_FIELDS = ('quote_volume',)
    HISTORY_LEN = 80

    def __init__(self, symbols: list[str], **kwargs: Any):
        kwargs.setdefault("concentration_pct", 0.1)
        kwargs.setdefault("reverse", False)
        super().__init__(symbols=symbols, **kwargs)

    def _compute_score(self, hist: dict[str, list[float]]) -> float | None:
        if len(hist['quote_volume']) < 20:
            return None
        try:
            return sum(hist['quote_volume'][-5:])/5 - sum(hist['quote_volume'][-20:])/20
        except Exception:
            return None
