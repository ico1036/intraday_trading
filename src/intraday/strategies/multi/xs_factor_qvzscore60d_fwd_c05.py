"""xs_factor_qvzscore60d_fwd_c05 — auto-generated XS factor.

Signal: qv_zscore_60d  direction=fwd  concentration=0.05
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
    "idea_family": "xs_factor_qv_zscore_60d_fwd_c05",
}
SOURCE_NOTES: list[str] = ["research/notes/xs_factor_zoo.md"]


class XsFactorQvzscore60dFwdC05(XsFactorBase):
    HISTORY_FIELDS = ('quote_volume',)
    HISTORY_LEN = 80

    def __init__(self, symbols: list[str], **kwargs: Any):
        kwargs.setdefault("concentration_pct", 0.05)
        kwargs.setdefault("reverse", False)
        super().__init__(symbols=symbols, **kwargs)

    def _compute_score(self, hist: dict[str, list[float]]) -> float | None:
        if len(hist['quote_volume']) < 60:
            return None
        try:
            return (hist['quote_volume'][-1] - sum(hist['quote_volume'][-60:])/60) / (((sum((v - sum(hist['quote_volume'][-60:])/60)**2 for v in hist['quote_volume'][-60:]))/59)**0.5 or 1e-9)
        except Exception:
            return None
