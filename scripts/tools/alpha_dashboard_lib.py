"""Pure (NiceGUI/Plotly-free) helpers for the alpha dashboard.

Everything here is importable in tests without a UI runtime. Functions take
already-loaded inputs (pd.Series / pd.DataFrame / scalars) and return scalars
or simple containers; the dashboard module handles file I/O and caches around
these primitives.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
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


def classify_alpha(is_m: dict | None, os_m: dict | None = None) -> tuple[str, str]:
    """Classify SUBMITTABLE / NORMAL / REJECT / INCOMPLETE.

    Two modes:
      - IS-only (os_m falsy): checks IS-side mirrors of the rule set. Used when
        OS validation is deferred to the user.
      - Full (both is_m and os_m): checks the original R1-R4 reject and S1-S7
        submittable rules using OS data + OS/IS degradations.
    """
    if not is_m:
        return ("INCOMPLETE", "missing IS metrics")

    is_bps = is_m.get("pnl_bps_simple") or 0
    is_t = is_m.get("t_stat") or 0
    is_pf = is_m.get("profit_factor_trades") or 0
    is_dd_abs = abs(is_m.get("max_drawdown") or 0)
    is_n = int(is_m.get("total_trades") or 0)
    is_sh = is_m.get("sharpe") or 0

    # ---------- IS-only path ----------
    if not os_m:
        if is_bps is None or is_bps <= 0:
            return ("REJECT", "R1-IS: IS bps ≤ 0")
        if is_t < 1.5:
            return ("REJECT", "R2-IS: IS t-stat < 1.5")
        if is_n < 100:
            return ("REJECT", "R4: IS trades < 100")
        if (is_t > 2.5
            and is_bps > 2.0
            and is_dd_abs < 0.12
            and is_pf > 1.3
            and is_n > 500):
            return ("SUBMITTABLE", "IS S1-S5/S7 ✓ (OS pending)")
        return ("NORMAL", "between (IS-only)")

    # ---------- Full IS + OS path ----------
    os_bps = os_m.get("pnl_bps_simple") or 0
    os_t = os_m.get("t_stat") or 0
    os_sh = os_m.get("sharpe") or 0
    os_pf = os_m.get("profit_factor_trades") or 0
    os_dd_abs = abs(os_m.get("max_drawdown") or 0)
    sh_degr = (os_sh / is_sh) if is_sh not in (None, 0) else 0
    bps_degr = (os_bps / is_bps) if is_bps not in (None, 0) else 0

    if (is_bps is None or os_bps is None) or is_bps <= 0 or os_bps <= 0:
        return ("REJECT", "R1: bps ≤ 0")
    if os_t < 1.5:
        return ("REJECT", "R2: OS t-stat < 1.5")
    if sh_degr < 0.4:
        return ("REJECT", "R3: Sharpe degr < 0.4")
    if is_n < 100:
        return ("REJECT", "R4: IS trades < 100")

    if (os_t > 2.5
        and os_bps > 2.0
        and sh_degr > 0.7
        and bps_degr > 0.6
        and os_dd_abs < 0.12
        and os_pf > 1.3
        and is_n > 500):
        return ("SUBMITTABLE", "S1-S7 ✓")

    return ("NORMAL", "between")


def is_ensemble_candidate(
    is_m: dict | None,
    os_m: dict | None,
    *,
    min_os_t: float = 1.0,
    min_sh_degr: float = 0.2,
    min_bps_degr: float = 0.2,
    max_os_dd: float = 0.20,
    min_os_pf: float = 1.05,
    min_is_n: int = 100,
    require_positive_signs: bool = True,
) -> tuple[bool, str]:
    """LOOSE filter for ensemble-grade alphas (looser than SUBMITTABLE).

    Goal: accept components that meaningfully contribute to a portfolio after
    correlation dedup. Per-alpha thresholds are intentionally lower than the
    standalone SUBMITTABLE criteria — diversification compensates.
    """
    if not is_m or not os_m:
        return (False, "missing IS or OS metrics")
    is_bps = is_m.get("pnl_bps_simple") or 0
    os_bps = os_m.get("pnl_bps_simple") or 0
    is_sh = is_m.get("sharpe") or 0
    os_sh = os_m.get("sharpe") or 0
    os_t = os_m.get("t_stat") or 0
    os_pf = os_m.get("profit_factor_trades") or 0
    os_dd_abs = abs(os_m.get("max_drawdown") or 0)
    is_n = int(is_m.get("total_trades") or 0)
    sh_degr = (os_sh / is_sh) if is_sh not in (None, 0) else 0
    bps_degr = (os_bps / is_bps) if is_bps not in (None, 0) else 0

    if is_bps <= 0 or os_bps <= 0:
        return (False, f"bps non-positive (IS={is_bps:.2f}, OS={os_bps:.2f})")
    if is_n < min_is_n:
        return (False, f"IS trades {is_n} < {min_is_n}")
    if os_t < min_os_t:
        return (False, f"OS t-stat {os_t:.2f} < {min_os_t}")
    if sh_degr < min_sh_degr:
        return (False, f"Sharpe degr {sh_degr:.2f} < {min_sh_degr}")
    if bps_degr < min_bps_degr:
        return (False, f"bps degr {bps_degr:.2f} < {min_bps_degr}")
    if os_dd_abs > max_os_dd:
        return (False, f"OS DD {os_dd_abs:.2%} > {max_os_dd:.0%}")
    if os_pf < min_os_pf:
        return (False, f"OS PF {os_pf:.2f} < {min_os_pf}")
    if require_positive_signs and (is_sh <= 0 or os_sh <= 0):
        return (False, "Sharpe sign not positive on both sides")
    return (True, "OK")


def max_corr_to_pool(
    candidate_returns: "pd.Series",
    pool_returns: "list[pd.Series]",
) -> float:
    """Return the maximum |Pearson correlation| between a candidate's OS daily
    returns and each member of an existing pool. 0.0 if pool is empty.
    """
    if not pool_returns:
        return 0.0
    cs = []
    for sel in pool_returns:
        joined = pd.concat([candidate_returns, sel], axis=1, join="inner").dropna()
        if len(joined) < 10:
            continue
        c = joined.iloc[:, 0].corr(joined.iloc[:, 1])
        if pd.notna(c):
            cs.append(abs(float(c)))
    return max(cs) if cs else 0.0


def apply_correlation_gate(
    candidates: list[tuple[str, dict]],
    return_panel: pd.DataFrame,
    tau: float = 0.95,
) -> list[str]:
    """Greedy correlation dedup for the SUBMITTABLE candidate pool.

    ``candidates`` is a list of (alpha_id, metrics) pairs *already* sorted
    descending by quality (e.g. IS sharpe). ``return_panel`` is a DataFrame
    with one column per alpha_id of daily return series (e.g. IS daily pct
    change of equity_curve). Returns the alpha_ids that survive: starting
    from the highest-quality candidate, each next one is kept only if its
    max |ρ| with the already-kept set is below ``tau``.

    Rationale: with two alphas at |ρ| > 0.95 a portfolio cannot meaningfully
    diversify between them. The legacy submittable gate accepts both; the
    correlation gate filters such clones at population level. ``tau = 0.95``
    is intentionally permissive — it removes only near-perfect clones; lower
    thresholds collapse the pool aggressively because crypto trend-followers
    are intrinsically correlated.

    Returns
    -------
    list[str]
        Alpha ids that pass both the per-alpha submittable gates *and* the
        population-level correlation dedup.
    """
    selected: list[str] = []
    for aid, _m in candidates:
        if aid not in return_panel.columns:
            continue
        if not selected:
            selected.append(aid)
            continue
        max_rho = float(return_panel[aid].corr(return_panel[selected].mean(axis=1)))
        # Use pairwise max instead of mean — more conservative and matches
        # the report's "max |ρ| with kept set" definition.
        max_pair = float(return_panel.loc[:, selected].corrwith(return_panel[aid]).abs().max())
        if max_pair < tau:
            selected.append(aid)
    return selected


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


# ---- forward split detection -----------------------------------------------


SPLIT_ORDER = ("is", "os", "forward")


def _split_has_data(split_dir: Path) -> bool:
    """A split directory counts as "having data" if it contains either a
    ``metrics.json`` (backtest splits) or an ``equity_curve.parquet``
    (forward-style outputs that may not have a finalized metrics file yet)."""
    if not split_dir.is_dir():
        return False
    return (split_dir / "metrics.json").exists() or (split_dir / "equity_curve.parquet").exists()


def discover_splits(alpha_dir: Path) -> list[str]:
    """Return splits with data for ``alpha_dir`` in canonical order
    (``is`` → ``os`` → ``forward``)."""
    alpha_dir = Path(alpha_dir)
    return [s for s in SPLIT_ORDER if _split_has_data(alpha_dir / s)]


def is_forward_live(forward_dir: Path) -> bool:
    """A forward split is "live" iff its ``pid.txt`` references a process
    that is currently running. Used to render a LIVE indicator on the
    dashboard. Stale or malformed pid files are treated as dead."""
    forward_dir = Path(forward_dir)
    pid_path = forward_dir / "pid.txt"
    if not pid_path.exists():
        return False
    try:
        pid = int(pid_path.read_text().strip())
    except (ValueError, OSError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)  # signal 0 = existence check, doesn't actually signal
    except (OSError, ProcessLookupError):
        return False
    return True


def cumret_segment_offsets(
    is_final_cumret: float | None,
    os_final_cumret: float | None,
) -> dict[str, float]:
    """Compute cumret offsets so IS / OS / Forward stitch as one curve.

    Each segment's chart cumret += this offset so the next segment starts
    where the previous one ended. ``None`` inputs treat that segment as
    absent — subsequent ones simply start at the most recent end.
    """
    offsets = {"is": 0.0, "os": 0.0, "forward": 0.0}
    if is_final_cumret is not None:
        offsets["os"] = float(is_final_cumret)
        offsets["forward"] = float(is_final_cumret)
    if os_final_cumret is not None:
        offsets["forward"] = offsets["os"] + float(os_final_cumret)
    return offsets


def format_uptime(seconds: float | None) -> str:
    """Human-readable uptime string."""
    if seconds is None:
        return "-"
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60}s"
    if s < 86400:
        return f"{s // 3600}h {(s % 3600) // 60}m"
    return f"{s // 86400}d {(s % 86400) // 3600}h"


def forward_status(forward_dir: Path) -> dict:
    """Aggregate live-status info for the forward split.

    Returns dict with keys: live, pid, started_at, uptime_seconds,
    nav_current, nav_start, today_pnl, last_decision,
    session_start, session_equity_start, session_pnl, session_return.

    "Session" = the post-OS live segment, i.e. the full forward equity
    curve (which by construction begins after OS ends). Session fields
    are populated only when the runner is currently ``live``; missing
    values are ``None``. Safe to call even when forward dir is absent.
    """
    forward_dir = Path(forward_dir)
    result = {
        "live": False,
        "pid": None,
        "started_at": None,
        "uptime_seconds": None,
        "nav_current": None,
        "nav_start": None,
        "today_pnl": None,
        "last_decision": None,
        "session_start": None,
        "session_equity_start": None,
        "session_pnl": None,
        "session_return": None,
    }
    if not forward_dir.exists():
        return result

    pid_path = forward_dir / "pid.txt"
    if pid_path.exists():
        try:
            pid = int(pid_path.read_text().strip())
            if pid > 0:
                try:
                    os.kill(pid, 0)
                    result["live"] = True
                    result["pid"] = pid
                    started = datetime.fromtimestamp(pid_path.stat().st_mtime)
                    result["started_at"] = started
                    result["uptime_seconds"] = max(
                        0.0, (datetime.now() - started).total_seconds()
                    )
                except (OSError, ProcessLookupError):
                    pass
        except (ValueError, OSError):
            pass

    eq_path = forward_dir / "equity_curve.parquet"
    if eq_path.exists():
        try:
            df = pd.read_parquet(eq_path, columns=["timestamp", "equity"])
            if len(df) > 0:
                df = df.sort_values("timestamp").reset_index(drop=True)
                result["nav_current"] = float(df["equity"].iloc[-1])
                result["nav_start"] = float(df["equity"].iloc[0])
                result["last_decision"] = pd.to_datetime(df["timestamp"].iloc[-1])
                if len(df) >= 2:
                    result["today_pnl"] = float(
                        df["equity"].iloc[-1] - df["equity"].iloc[-2]
                    )
                if result["live"]:
                    eq_start = float(df["equity"].iloc[0])
                    eq_cur = float(df["equity"].iloc[-1])
                    result["session_start"] = pd.to_datetime(df["timestamp"].iloc[0])
                    result["session_equity_start"] = eq_start
                    result["session_pnl"] = eq_cur - eq_start
                    result["session_return"] = (
                        (eq_cur / eq_start - 1.0) if eq_start else None
                    )
        except Exception:
            pass

    return result
