"""xs_factor_sharpeproxy60d_fwd_c50 — auto-generated XS factor.

Signal: sharpe_proxy_60d  direction=fwd  concentration=0.5
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
    "idea_family": "xs_factor_sharpe_proxy_60d_fwd_c50",
}
SOURCE_NOTES: list[str] = ["research/notes/xs_factor_zoo.md"]


class XsFactorSharpeproxy60dFwdC50(XsFactorBase):
    HISTORY_FIELDS = ('close',)
    HISTORY_LEN = 80

    def __init__(self, symbols: list[str], **kwargs: Any):
        kwargs.setdefault("concentration_pct", 0.5)
        kwargs.setdefault("reverse", False)
        super().__init__(symbols=symbols, **kwargs)

    def _compute_score(self, hist: dict[str, list[float]]) -> float | None:
        if len(hist['close']) < 61:
            return None
        try:
            return (lambda r=[hist['close'][-i]/hist['close'][-i-1]-1.0 for i in range(1,61)]: (sum(r)/60) / ((sum((x - sum(r)/60)**2 for x in r)/59)**0.5 or 1e-9))()
        except Exception:
            return None
