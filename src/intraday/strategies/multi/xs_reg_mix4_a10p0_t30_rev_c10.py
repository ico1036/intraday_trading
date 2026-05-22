"""xs_reg_mix4_a10p0_t30_rev_c10 — auto-generated ridge cross-sectional regression alpha.

Features: ['ret5d', 'vol20d', 'rev_ma20', 'logvol']  ridge α=10.0  train window=30d
direction=rev  concentration=0.1
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
    "idea_family": "xs_reg_mix4_a10p0_t30_rev_c10",
}
SOURCE_NOTES: list[str] = ["research/notes/xs_regression_zoo.md"]


class XsRegMix4A10p0T30RevC10(XsRegressionBase):
    HISTORY_FIELDS = ("close", "quote_volume")
    HISTORY_LEN = 130
    RIDGE_ALPHA = 10.0
    TRAIN_WINDOW = 30
    FEATURE_FNS = (
lambda hist: (hist['close'][-1]/hist['close'][-6]-1.0) if len(hist['close'])>=6 else None,
lambda hist: (((sum((hist['close'][-i]/hist['close'][-i-1]-1.0)**2 for i in range(1,21))/19)**0.5) if len(hist['close'])>=21 else None),
lambda hist: (hist['close'][-1]/(sum(hist['close'][-20:])/20)-1.0) if len(hist['close'])>=20 else None,
lambda hist: math.log(max(hist['quote_volume'][-1], 1e-12)) if hist['quote_volume'] else None,
    )

    def __init__(self, symbols: list[str], **kwargs: Any):
        kwargs.setdefault("concentration_pct", 0.1)
        kwargs.setdefault("reverse", True)
        super().__init__(symbols=symbols, **kwargs)
