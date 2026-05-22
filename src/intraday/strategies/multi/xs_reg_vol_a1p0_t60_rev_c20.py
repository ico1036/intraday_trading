"""xs_reg_vol_a1p0_t60_rev_c20 — auto-generated ridge cross-sectional regression alpha.

Features: ['vol20d', 'logvol', 'absret20']  ridge α=1.0  train window=60d
direction=rev  concentration=0.2
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
    "idea_family": "xs_reg_vol_a1p0_t60_rev_c20",
}
SOURCE_NOTES: list[str] = ["research/notes/xs_regression_zoo.md"]


class XsRegVolA1p0T60RevC20(XsRegressionBase):
    HISTORY_FIELDS = ("close", "quote_volume")
    HISTORY_LEN = 130
    RIDGE_ALPHA = 1.0
    TRAIN_WINDOW = 60
    FEATURE_FNS = (
lambda hist: (((sum((hist['close'][-i]/hist['close'][-i-1]-1.0)**2 for i in range(1,21))/19)**0.5) if len(hist['close'])>=21 else None),
lambda hist: math.log(max(hist['quote_volume'][-1], 1e-12)) if hist['quote_volume'] else None,
lambda hist: (sum(abs(hist['close'][-i]/hist['close'][-i-1]-1.0) for i in range(1,21))/20 if len(hist['close'])>=21 else None),
    )

    def __init__(self, symbols: list[str], **kwargs: Any):
        kwargs.setdefault("concentration_pct", 0.2)
        kwargs.setdefault("reverse", True)
        super().__init__(symbols=symbols, **kwargs)
