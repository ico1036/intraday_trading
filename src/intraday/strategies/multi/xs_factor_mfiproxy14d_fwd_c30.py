"""xs_factor_mfiproxy14d_fwd_c30 — auto-generated XS factor.

Signal: mfi_proxy_14d  direction=fwd  concentration=0.3
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
    "idea_family": "xs_factor_mfi_proxy_14d_fwd_c30",
}
SOURCE_NOTES: list[str] = ["research/notes/xs_factor_zoo.md"]


class XsFactorMfiproxy14dFwdC30(XsFactorBase):
    HISTORY_FIELDS = ('close', 'quote_volume')
    HISTORY_LEN = 80

    def __init__(self, symbols: list[str], **kwargs: Any):
        kwargs.setdefault("concentration_pct", 0.3)
        kwargs.setdefault("reverse", False)
        super().__init__(symbols=symbols, **kwargs)

    def _compute_score(self, hist: dict[str, list[float]]) -> float | None:
        if len(hist['close']) < 15:
            return None
        try:
            return (lambda pos=sum(hist['close'][-i] * hist['quote_volume'][-i] for i in range(1,15) if hist['close'][-i] > hist['close'][-i-1]), neg=sum(hist['close'][-i] * hist['quote_volume'][-i] for i in range(1,15) if hist['close'][-i] < hist['close'][-i-1]): pos / ((pos + neg) or 1e-9))()
        except Exception:
            return None
