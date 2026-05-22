"""xs_factor_buysharezscore20d_rev_c50 — auto-generated XS factor.

Signal: buy_share_zscore_20d  direction=rev  concentration=0.5
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
    "idea_family": "xs_factor_buy_share_zscore_20d_rev_c50",
}
SOURCE_NOTES: list[str] = ["research/notes/xs_factor_zoo.md"]


class XsFactorBuysharezscore20dRevC50(XsFactorBase):
    HISTORY_FIELDS = ('buy_volume', 'volume')
    HISTORY_LEN = 80

    def __init__(self, symbols: list[str], **kwargs: Any):
        kwargs.setdefault("concentration_pct", 0.5)
        kwargs.setdefault("reverse", True)
        super().__init__(symbols=symbols, **kwargs)

    def _compute_score(self, hist: dict[str, list[float]]) -> float | None:
        if len(hist['buy_volume']) < 21:
            return None
        try:
            return (hist['buy_volume'][-1]/(hist['volume'][-1] or 1e-9) - sum(hist['buy_volume'][-i]/(hist['volume'][-i] or 1e-9) for i in range(1,21))/20)
        except Exception:
            return None
