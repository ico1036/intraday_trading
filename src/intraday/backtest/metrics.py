"""Sharpe ratio utilities for consistent backtest metrics.

Policy: prefer daily aggregation before annualization (sqrt(252)).
If timestamps are unavailable, fallback to period Sharpe with sqrt(252).
"""

from __future__ import annotations

from typing import Iterable, Sequence

import numpy as np
import pandas as pd


def sharpe_daily_annualized(
    equity_curve: Sequence[float],
    timestamps: Iterable | None = None,
) -> float:
    """Compute Sharpe ratio with daily aggregation then annualization.

    Args:
        equity_curve: equity values over time.
        timestamps: optional corresponding datetime-like points.

    Returns:
        Annualized Sharpe ratio. If no meaningful variance exists, returns 0.
    """
    if equity_curve is None:
        return 0.0

    eq = pd.Series(list(equity_curve), dtype=float)
    if len(eq) < 2:
        return 0.0

    eq = eq.replace([np.inf, -np.inf], np.nan).dropna()
    if len(eq) < 2:
        return 0.0

    ts = None
    if timestamps is not None:
        ts_series = pd.Index(timestamps)
        if len(ts_series) >= len(eq):
            ts_series = ts_series[: len(eq)]
            eq = eq.iloc[-len(ts_series):].reset_index(drop=True)
        else:
            # if timestamps are fewer than points, align by best effort
            eq = eq.iloc[-len(ts_series):].reset_index(drop=True)
        if len(ts_series) == len(eq):
            ts = pd.to_datetime(ts_series)

    if ts is not None:
        eq = pd.Series(eq.values, index=ts)
        eq = eq.sort_index()
        eq = eq[~eq.index.duplicated(keep='last')]
        daily = eq.resample("D").last().dropna().pct_change().dropna()
        if len(daily) >= 2:
            std = daily.std(ddof=1)
            if std == 0 or pd.isna(std):
                return 0.0
            return float(daily.mean() / std * np.sqrt(252))

    # Fallback: fallback to period Sharpe with annualization by business days assumption
    rets = eq.pct_change().dropna()
    if len(rets) < 2:
        return 0.0

    std = rets.std(ddof=1)
    if std == 0 or pd.isna(std):
        return 0.0
    return float(rets.mean() / std * np.sqrt(252))
