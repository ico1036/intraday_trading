"""xs_reg_revert_a10p0_t60_fwd_c20 — auto-generated ridge cross-sectional regression alpha.

Features: ['rev_ma20', 'dist_hi20', 'ret1d']  ridge α=10.0  train window=60d
direction=fwd  concentration=0.2
"""
from __future__ import annotations

import math
from typing import Any

from intraday.strategies._xs_regression_base import XsRegressionBase


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "ewma_residual",
    "horizon": "multi_day",
    "universe": "basket_full",
    "exit": "signal_flip",
    "idea_family": "xs_reg_revert_a10p0_t60_fwd_c20",
}
SOURCE_NOTES: list[str] = ["research/notes/xs_regression_zoo.md"]


class XsRegRevertA10p0T60FwdC20(XsRegressionBase):
    HISTORY_FIELDS = ("close", "quote_volume")
    HISTORY_LEN = 130
    RIDGE_ALPHA = 10.0
    TRAIN_WINDOW = 60
    FEATURE_FNS = (
lambda hist: (hist['close'][-1]/(sum(hist['close'][-20:])/20)-1.0) if len(hist['close'])>=20 else None,
lambda hist: (hist['close'][-1]/max(hist['close'][-20:])-1.0) if len(hist['close'])>=20 else None,
lambda hist: (hist['close'][-1]/hist['close'][-2]-1.0) if len(hist['close'])>=2 else None,
    )

    def __init__(self, symbols: list[str], **kwargs: Any):
        kwargs.setdefault("concentration_pct", 0.2)
        kwargs.setdefault("reverse", False)
        super().__init__(symbols=symbols, **kwargs)
