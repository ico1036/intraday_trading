"""xs_reg_mom_a10p0_t60_fwd_c30 — auto-generated ridge cross-sectional regression alpha.

Features: ['ret1d', 'ret5d', 'ret20d', 'ret60d']  ridge α=10.0  train window=60d
direction=fwd  concentration=0.3
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
    "idea_family": "xs_reg_mom_a10p0_t60_fwd_c30",
}
SOURCE_NOTES: list[str] = ["research/notes/xs_regression_zoo.md"]


class XsRegMomA10p0T60FwdC30(XsRegressionBase):
    HISTORY_FIELDS = ("close", "quote_volume")
    HISTORY_LEN = 130
    RIDGE_ALPHA = 10.0
    TRAIN_WINDOW = 60
    FEATURE_FNS = (
lambda hist: (hist['close'][-1]/hist['close'][-2]-1.0) if len(hist['close'])>=2 else None,
lambda hist: (hist['close'][-1]/hist['close'][-6]-1.0) if len(hist['close'])>=6 else None,
lambda hist: (hist['close'][-1]/hist['close'][-21]-1.0) if len(hist['close'])>=21 else None,
lambda hist: (hist['close'][-1]/hist['close'][-61]-1.0) if len(hist['close'])>=61 else None,
    )

    def __init__(self, symbols: list[str], **kwargs: Any):
        kwargs.setdefault("concentration_pct", 0.3)
        kwargs.setdefault("reverse", False)
        super().__init__(symbols=symbols, **kwargs)
