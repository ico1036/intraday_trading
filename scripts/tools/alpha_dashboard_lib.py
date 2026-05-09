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


def compute_trade_stats(trades_df: pd.DataFrame) -> dict:
    """Compute per-round-trip statistics from trades.parquet.

    Returns a dict of:
      n_round_trips, mean_bps, std_bps, per_trade_sharpe, t_stat,
      win_rate, avg_win_bps, avg_loss_bps, win_loss_ratio,
      profit_factor, largest_win_bps, largest_loss_bps,
      mean_bps_notional_weighted

    All values None when trades_df is empty or malformed. ``per_trade_sharpe``
    is mean/std (raw, not annualized). ``t_stat`` = per_trade_sharpe × sqrt(N).
    """
    import math
    empty = {
        "n_round_trips": 0,
        "mean_bps": None,
        "std_bps": None,
        "per_trade_sharpe": None,
        "t_stat": None,
        "win_rate": None,
        "avg_win_bps": None,
        "avg_loss_bps": None,
        "win_loss_ratio": None,
        "profit_factor": None,
        "largest_win_bps": None,
        "largest_loss_bps": None,
        "mean_bps_notional_weighted": None,
    }
    if trades_df is None or trades_df.empty or "action" not in trades_df.columns:
        return empty
    df = trades_df.sort_values(["symbol", "timestamp"]).reset_index(drop=True)
    opens = df[df["action"].astype(str).str.startswith("OPEN")].reset_index(drop=True)
    closes = df[df["action"].astype(str).str.startswith("CLOSE")].reset_index(drop=True)
    n = min(len(opens), len(closes))
    if n == 0:
        return empty
    opens = opens.iloc[:n]
    closes = closes.iloc[:n]
    if not (opens["symbol"].values == closes["symbol"].values).all():
        empty["n_round_trips"] = n
        return empty
    open_fee = opens["fee"].astype(float).values
    close_fee = closes["fee"].astype(float).values
    gross = closes["pnl"].astype(float).values
    net = gross - open_fee - close_fee
    notional = (opens["price"].astype(float) * opens["quantity"].astype(float)).values
    valid = notional > 0
    if not valid.any():
        empty["n_round_trips"] = n
        return empty
    bps = (net[valid] / notional[valid]) * 10000.0
    n_v = int(len(bps))
    mean_bps = float(bps.mean())
    std_bps = float(bps.std(ddof=1)) if n_v >= 2 else 0.0
    per_trade_sharpe = mean_bps / std_bps if std_bps > 0 else None
    t_stat = (per_trade_sharpe * math.sqrt(n_v)) if per_trade_sharpe is not None else None
    weighted = float((net[valid].sum() / notional[valid].sum()) * 10000.0)
    wins = bps[bps > 0]
    losses = bps[bps < 0]
    win_rate = float(len(wins) / n_v)
    avg_win = float(wins.mean()) if len(wins) else None
    avg_loss = float(losses.mean()) if len(losses) else None  # negative
    wl_ratio = (avg_win / abs(avg_loss)) if (avg_win is not None and avg_loss not in (None, 0)) else None
    sum_win = float(wins.sum()) if len(wins) else 0.0
    sum_loss = float(abs(losses.sum())) if len(losses) else 0.0
    profit_factor = (sum_win / sum_loss) if sum_loss > 0 else None
    largest_win = float(bps.max())
    largest_loss = float(bps.min())
    return {
        "n_round_trips": n_v,
        "mean_bps": mean_bps,
        "std_bps": std_bps,
        "per_trade_sharpe": per_trade_sharpe,
        "t_stat": t_stat,
        "win_rate": win_rate,
        "avg_win_bps": avg_win,
        "avg_loss_bps": avg_loss,
        "win_loss_ratio": wl_ratio,
        "profit_factor": profit_factor,
        "largest_win_bps": largest_win,
        "largest_loss_bps": largest_loss,
        "mean_bps_notional_weighted": weighted,
    }


def classify_alpha(is_m: dict | None, os_m: dict | None) -> tuple[str, str]:
    """Classify an alpha as SUBMITTABLE / NORMAL / REJECT / INCOMPLETE.

    Uses the user-defined post-OS criteria (see memory:
    alpha_acceptance_criteria.md). Reject rules R1-R4 fire on any one
    failure → REJECT. Submittable requires all S1-S7 to pass. Otherwise
    NORMAL.
    """
    if not is_m or not os_m:
        return ("INCOMPLETE", "missing IS or OS metrics")

    is_bps = is_m.get("pnl_bps_simple") or 0
    os_bps = os_m.get("pnl_bps_simple") or 0
    os_t = os_m.get("t_stat") or 0
    is_sh = is_m.get("sharpe") or 0
    os_sh = os_m.get("sharpe") or 0
    os_pf = os_m.get("profit_factor_trades") or 0
    os_dd_abs = abs(os_m.get("max_drawdown") or 0)
    is_n = int(is_m.get("total_trades") or 0)

    sh_degr = (os_sh / is_sh) if is_sh not in (None, 0) else 0
    bps_degr = (os_bps / is_bps) if is_bps not in (None, 0) else 0

    # Reject — any single rule trips
    if (is_bps is None or os_bps is None) or is_bps <= 0 or os_bps <= 0:
        return ("REJECT", "R1: bps ≤ 0")
    if os_t < 1.5:
        return ("REJECT", "R2: OS t-stat < 1.5")
    if sh_degr < 0.4:
        return ("REJECT", "R3: Sharpe degr < 0.4")
    if is_n < 100:
        return ("REJECT", "R4: IS trades < 100")

    # Submittable — all 7 conditions pass
    if (os_t > 2.5
        and os_bps > 2.0
        and sh_degr > 0.7
        and bps_degr > 0.6
        and os_dd_abs < 0.12
        and os_pf > 1.3
        and is_n > 500):
        return ("SUBMITTABLE", "S1-S7 ✓")

    return ("NORMAL", "between")


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
