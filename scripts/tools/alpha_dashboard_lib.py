"""Pure (NiceGUI/Plotly-free) helpers for the alpha dashboard.

Everything here is importable in tests without a UI runtime. Functions take
already-loaded inputs (pd.Series / pd.DataFrame / scalars) and return scalars
or simple containers; the dashboard module handles file I/O and caches around
these primitives.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd


# ---- formatters ----


def _missing(value: Any) -> bool:
    try:
        return bool(pd.isna(value))
    except Exception:
        return value is None


def _fmt_pct(value: Any) -> str:
    try:
        if _missing(value):
            return "-"
        return f"{float(value) * 100:.2f}%"
    except Exception:
        return "-"


def _fmt_num(value: Any) -> str:
    try:
        if _missing(value):
            return "-"
        return f"{float(value):.3f}"
    except Exception:
        return "-"


def _fmt_int(value: Any) -> str:
    try:
        if _missing(value):
            return "-"
        return f"{int(float(value)):,}"
    except Exception:
        return "-"


def _fmt_turnover(value: Any) -> str:
    try:
        if _missing(value):
            return "-"
        return f"{float(value):.2f}x"
    except Exception:
        return "-"


def _fmt_bps(value: Any) -> str:
    try:
        if _missing(value):
            return "-"
        return f"{float(value):+.2f} bps"
    except Exception:
        return "-"


def _fmt_duration_days(value: Any) -> str:
    try:
        if _missing(value):
            return "-"
        d = float(value)
    except Exception:
        return "-"
    if d < 1:
        return f"{d * 24:.1f}h"
    return f"{d:.1f}d"


def _fmt_days(days: float | None) -> str:
    if days is None:
        return "-"
    if days < 1:
        return f"{days * 24:.1f}h"
    if days < 10:
        return f"{days:.1f}d"
    return f"{days:.0f}d"


def _duration_days(start: Any, end: Any) -> float | None:
    try:
        start_dt = datetime.fromisoformat(str(start))
        end_dt = datetime.fromisoformat(str(end))
    except Exception:
        return None
    return (end_dt - start_dt).total_seconds() / 86400.0 + 1 / 1440.0


# ---- gates ----


def _is_pass_eligible(
    sharpe: Any,
    trades: Any,
    turnover: Any,
    *,
    sharpe_threshold: float,
    min_trades: float,
    min_turnover: float,
) -> bool:
    try:
        sh = float(sharpe) if sharpe is not None else None
        tr = float(trades) if trades is not None else None
        to = float(turnover) if turnover is not None else None
    except (TypeError, ValueError):
        return False
    if sh is None or tr is None or to is None:
        return False
    return sh >= sharpe_threshold and tr >= min_trades and to >= min_turnover


# ---- core 4 metric primitives ----


def compute_drawdown_metrics(
    equity: pd.Series,
) -> tuple[float | None, float | None, str | None, str | None]:
    """Compute (max_dd, duration_days, peak_ts, recovery_ts) on a datetime-indexed equity series.

    ``duration_days`` is peak → recovery measured in days. If equity never
    recovers to the prior peak by series end, the duration is peak → end.
    """
    if equity is None or len(equity) < 2:
        return (None, None, None, None)
    eq = equity.dropna()
    if len(eq) < 2:
        return (None, None, None, None)
    cummax = eq.cummax()
    dd = eq / cummax - 1.0
    bottom_ts = dd.idxmin()
    if pd.isna(bottom_ts):
        return (None, None, None, None)
    max_dd = float(dd.loc[bottom_ts])
    peak_value = float(cummax.loc[bottom_ts])
    pre = eq.loc[:bottom_ts]
    peak_mask = pre >= peak_value - 1e-9
    peak_ts = peak_mask[peak_mask].index[-1] if peak_mask.any() else eq.index[0]
    post = eq.loc[bottom_ts:]
    recovery_mask = post >= peak_value - 1e-9
    if recovery_mask.any():
        recovery_ts = recovery_mask[recovery_mask].index[0]
    else:
        recovery_ts = eq.index[-1]
    duration_days = (
        pd.Timestamp(recovery_ts) - pd.Timestamp(peak_ts)
    ).total_seconds() / 86400.0
    return (max_dd, float(duration_days), str(peak_ts), str(recovery_ts))


def compute_net_pnl_bps(
    trades_df: pd.DataFrame,
) -> tuple[float | None, float | None, int]:
    """Compute (avg_bps_simple, avg_bps_notional_weighted, n_round_trips).

    The engine writes ``pnl`` as GROSS — sum(pnl) − sum(fee) reproduces
    total return. Net per-round-trip PnL is reconstructed by pairing each OPEN
    row with its matching CLOSE row in the same symbol and subtracting both
    legs' fees. Notional uses the OPEN leg's price × quantity.
    """
    if trades_df is None or trades_df.empty or "action" not in trades_df.columns:
        return (None, None, 0)
    df = trades_df.sort_values(["symbol", "timestamp"]).reset_index(drop=True)
    opens = df[df["action"].astype(str).str.startswith("OPEN")].reset_index(drop=True)
    closes = df[df["action"].astype(str).str.startswith("CLOSE")].reset_index(drop=True)
    n = min(len(opens), len(closes))
    if n == 0:
        return (None, None, 0)
    opens = opens.iloc[:n]
    closes = closes.iloc[:n]
    if not (opens["symbol"].values == closes["symbol"].values).all():
        return (None, None, n)
    open_fee = opens["fee"].astype(float).values
    close_fee = closes["fee"].astype(float).values
    gross = closes["pnl"].astype(float).values
    net = gross - open_fee - close_fee
    notional = (opens["price"].astype(float) * opens["quantity"].astype(float)).values
    valid = notional > 0
    if not valid.any():
        return (None, None, n)
    bps_each = (net[valid] / notional[valid]) * 10000.0
    simple = float(bps_each.mean())
    weighted = float((net[valid].sum() / notional[valid].sum()) * 10000.0)
    return (simple, weighted, n)


def compute_turnover(pivot: pd.DataFrame) -> float | None:
    """Sum of |Δw| across all rebalances; first row's |w| counts vs. an implicit zero start."""
    if pivot is None or pivot.empty:
        return None
    zero = pd.DataFrame([[0.0] * len(pivot.columns)], columns=pivot.columns)
    aligned = pd.concat([zero, pivot.reset_index(drop=True)], ignore_index=True)
    return float(aligned.diff().abs().sum(axis=1).sum())


# ---- downsampling utilities ----


def _series_downsample(s: pd.Series, max_points: int) -> pd.Series:
    if len(s) <= max_points:
        return s
    step = max(1, len(s) // max_points)
    return s.iloc[::step]


def _downsample_frame(df: pd.DataFrame, max_points: int) -> pd.DataFrame:
    if len(df) <= max_points:
        return df
    step = max(1, len(df) // max_points)
    sampled = df.iloc[::step].copy()
    if sampled.index[-1] != df.index[-1]:
        sampled = pd.concat([sampled, df.iloc[[-1]]])
    return sampled
