"""xs_factor_buyshare5d_fwd_c40 — auto-generated XS factor.

Signal: buy_share_5d  direction=fwd  concentration=0.4
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
    "idea_family": "xs_factor_buy_share_5d_fwd_c40",
}
SOURCE_NOTES: list[str] = ["research/notes/xs_factor_zoo.md"]


class XsFactorBuyshare5dFwdC40(XsFactorBase):
    HISTORY_FIELDS = ('buy_volume', 'volume')
    HISTORY_LEN = 80

    def __init__(self, symbols: list[str], **kwargs: Any):
        kwargs.setdefault("concentration_pct", 0.4)
        kwargs.setdefault("reverse", False)
        super().__init__(symbols=symbols, **kwargs)

    def _compute_score(self, hist: dict[str, list[float]]) -> float | None:
        if len(hist['buy_volume']) < 5:
            return None
        try:
            return sum(hist['buy_volume'][-5:]) / (sum(hist['volume'][-5:]) or 1e-9)
        except Exception:
            return None
