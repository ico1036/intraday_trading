"""xs_factor_macd1226_rev_c40 — auto-generated XS factor.

Signal: macd_12_26  direction=rev  concentration=0.4
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
    "idea_family": "xs_factor_macd_12_26_rev_c40",
}
SOURCE_NOTES: list[str] = ["research/notes/xs_factor_zoo.md"]


class XsFactorMacd1226RevC40(XsFactorBase):
    HISTORY_FIELDS = ('close',)
    HISTORY_LEN = 80

    def __init__(self, symbols: list[str], **kwargs: Any):
        kwargs.setdefault("concentration_pct", 0.4)
        kwargs.setdefault("reverse", True)
        super().__init__(symbols=symbols, **kwargs)

    def _compute_score(self, hist: dict[str, list[float]]) -> float | None:
        if len(hist['close']) < 27:
            return None
        try:
            return (lambda a12=2/13, a26=2/27, e12=hist['close'][-1] * (2/13) + sum(hist['close'][-i] * (2/13)*(1-2/13)**i for i in range(1,12))*0.5, e26=hist['close'][-1] * (2/27) + sum(hist['close'][-i] * (2/27)*(1-2/27)**i for i in range(1,26))*0.5: e12 - e26)()
        except Exception:
            return None
