"""xs_factor_wq006negcorropenvolume10d_fwd_c10 — auto-generated XS factor.

Signal: wq_006_neg_corr_open_volume_10d  direction=fwd  concentration=0.1
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
    "idea_family": "xs_factor_wq_006_neg_corr_open_volume_10d_fwd_c10",
}
SOURCE_NOTES: list[str] = ["research/notes/xs_factor_zoo.md"]


class XsFactorWq006negcorropenvolume10dFwdC10(XsFactorBase):
    HISTORY_FIELDS = ('open', 'volume')
    HISTORY_LEN = 80

    def __init__(self, symbols: list[str], **kwargs: Any):
        kwargs.setdefault("concentration_pct", 0.1)
        kwargs.setdefault("reverse", False)
        super().__init__(symbols=symbols, **kwargs)

    def _compute_score(self, hist: dict[str, list[float]]) -> float | None:
        if len(hist['open']) < 10:
            return None
        try:
            return -(lambda o=hist['open'][-10:], v=hist['volume'][-10:]: (sum((o[i]-sum(o)/10)*(v[i]-sum(v)/10) for i in range(10))/9) / (((sum((o[i]-sum(o)/10)**2 for i in range(10))/9)**0.5 * (sum((v[i]-sum(v)/10)**2 for i in range(10))/9)**0.5) or 1e-9))()
        except Exception:
            return None
