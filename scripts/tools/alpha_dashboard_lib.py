"""Pure (NiceGUI/Plotly-free) helpers for the alpha dashboard.

Everything here is importable in tests without a UI runtime. Functions take
already-loaded inputs (pd.Series / pd.DataFrame / scalars) and return scalars
or simple containers; the dashboard module handles file I/O and caches around
these primitives.
"""
from __future__ import annotations

import json
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


def compute_ic(
    weights_df: pd.DataFrame,
    data_path: Path | str = Path("data/futures_klines_daily"),
    bar_size_sec: float = 86400.0,
    is_end: str | "pd.Timestamp" | None = None,
) -> dict:
    """Information Coefficient over the alpha's emit history.

    Cross-sectional ``spearman(target_weight_t, return_{t+1})`` for each
    rebalance timestamp ``t``, then time-averaged. Returns dict with:

      ic_mean       — mean of per-bar IC; the time-averaged signal-return rank corr
      ic_std        — std of per-bar IC; volatility of the edge
      ic_ir         — ic_mean / ic_std × sqrt(bars_per_year); the IC info ratio
      ic_hit_rate   — share of bars where sign(IC_t) == sign(ic_mean)
      ic_bars       — number of rebalance timestamps with ≥2 valid pairs

    When ``is_end`` is supplied, also returns IS/OS sub-blocks plus a
    Welch z-score testing whether the IS and OS IC means differ. A
    small |z| says the alpha's edge is stationary across the split,
    so |z| is the overfit detector (large |z| ⇒ IS≠OS ⇒ overfit
    suspect).

      ic_mean_is, ic_std_is, ic_bars_is
      ic_mean_os, ic_std_os, ic_bars_os
      ic_z          — (mean_IS - mean_OS) / sqrt(var_IS/n_IS + var_OS/n_OS)

    All values None when weights_df is empty / malformed / lacks
    variance, or when either side of the split has fewer than 2 bars.
    Sign of ic_mean is informative but irrelevant for SUBMITTABLE
    gates (a negative IC alpha can be deployed flipped).
    """
    import math
    empty = {
        "ic_mean": None, "ic_std": None, "ic_ir": None,
        "ic_hit_rate": None, "ic_bars": 0,
        "ic_mean_is": None, "ic_std_is": None, "ic_bars_is": 0,
        "ic_mean_os": None, "ic_std_os": None, "ic_bars_os": 0,
        "ic_z": None,
    }
    if weights_df is None or weights_df.empty:
        return empty
    needed = {"timestamp", "symbol", "target_weight"}
    if not needed.issubset(weights_df.columns):
        return empty

    data_root = Path(data_path)
    w = weights_df[["timestamp", "symbol", "target_weight"]].copy()
    w["timestamp"] = pd.to_datetime(w["timestamp"])
    symbols = sorted(w["symbol"].astype(str).str.upper().unique())
    if not symbols:
        return empty

    # Load each symbol's daily close once, build a wide close panel, then
    # compute next-bar return on the panel timestamps.
    close_by_sym: dict[str, pd.Series] = {}
    for sym in symbols:
        sym_dir = data_root / sym
        if not sym_dir.is_dir():
            continue
        parts = sorted(sym_dir.glob(f"{sym}-*.parquet"))
        if not parts:
            continue
        frames = []
        for p in parts:
            try:
                df = pd.read_parquet(p, columns=["timestamp", "close"])
                frames.append(df)
            except Exception:
                continue
        if not frames:
            continue
        df = pd.concat(frames, ignore_index=True)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = (df.dropna(subset=["timestamp", "close"])
                .drop_duplicates(subset=["timestamp"])
                .sort_values("timestamp")
                .set_index("timestamp"))
        if df.empty:
            continue
        close_by_sym[sym] = df["close"].astype(float)
    if not close_by_sym:
        return empty

    closes = pd.DataFrame(close_by_sym).sort_index()
    next_ret = closes.pct_change().shift(-1)  # ret_{t+1} aligned at t

    # Per-rebalance-timestamp Spearman + remember the timestamp it was
    # observed on, so we can split into IS / OS sub-blocks below.
    ic_records: list[tuple[pd.Timestamp, float]] = []
    for ts, grp in w.groupby("timestamp"):
        if ts not in next_ret.index:
            nearest = next_ret.index.asof(ts)
            if pd.isna(nearest):
                continue
            ts = nearest
        rets = next_ret.loc[ts]
        wt = (grp.set_index(grp["symbol"].astype(str).str.upper())["target_weight"]
                .astype(float))
        joined = pd.concat([wt.rename("w"), rets.rename("r")], axis=1).dropna()
        if len(joined) < 5:
            continue
        if joined["w"].nunique() < 2 or joined["r"].nunique() < 2:
            continue
        ic = joined["w"].rank().corr(joined["r"].rank())
        if pd.notna(ic):
            ic_records.append((ts, float(ic)))

    if not ic_records:
        return empty
    ic_series = pd.Series([v for _, v in ic_records],
                          index=pd.to_datetime([t for t, _ in ic_records]))
    mean = float(ic_series.mean())
    std = float(ic_series.std(ddof=1)) if len(ic_series) > 1 else 0.0
    bars_per_year = max(1.0, (365 * 86400) / max(bar_size_sec, 1.0))
    ic_ir = (mean / std * math.sqrt(bars_per_year)) if std > 0 else None
    sign = 1 if mean >= 0 else -1
    hit = float(((ic_series * sign) > 0).mean())

    out = {
        "ic_mean": mean,
        "ic_std": std,
        "ic_ir": ic_ir,
        "ic_hit_rate": hit,
        "ic_bars": int(len(ic_series)),
        "ic_mean_is": None, "ic_std_is": None, "ic_bars_is": 0,
        "ic_mean_os": None, "ic_std_os": None, "ic_bars_os": 0,
        "ic_z": None,
    }

    if is_end is not None:
        try:
            cutoff = pd.Timestamp(is_end)
        except Exception:
            return out
        is_ic = ic_series[ic_series.index <= cutoff]
        os_ic = ic_series[ic_series.index > cutoff]
        if len(is_ic) >= 2 and len(os_ic) >= 2:
            mu_is = float(is_ic.mean())
            mu_os = float(os_ic.mean())
            var_is = float(is_ic.var(ddof=1))
            var_os = float(os_ic.var(ddof=1))
            n_is = len(is_ic)
            n_os = len(os_ic)
            denom = math.sqrt(var_is / n_is + var_os / n_os) if (var_is + var_os) > 0 else 0.0
            z = (mu_is - mu_os) / denom if denom > 0 else None
            out.update({
                "ic_mean_is": mu_is,
                "ic_std_is": math.sqrt(var_is) if var_is > 0 else 0.0,
                "ic_bars_is": int(n_is),
                "ic_mean_os": mu_os,
                "ic_std_os": math.sqrt(var_os) if var_os > 0 else 0.0,
                "ic_bars_os": int(n_os),
                "ic_z": z,
            })
    return out


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
    """Classify SUBMITTABLE / NORMAL / INCOMPLETE on a single metric set.

    Forward = backtest re-run daily; IS / OS split is no longer the
    validation boundary, so this function gates on **one set of
    metrics covering the full available range**. The primary signal
    health measure is the Information Coefficient: cross-sectional
    spearman(target_weight, next-bar return) averaged across all emit
    bars. ``ic_mean`` (sign-agnostic via abs) tells us how much edge
    the signal carries; ``ic_ir`` tells us how stable that edge is
    over time. A noisy alpha with sporadic high |t-stat| will have
    low |ic_ir| and stay NORMAL.

    The legacy second argument ``os_m`` is accepted for back-compat;
    if ``is_m`` is missing IC and ``os_m`` has it, ``os_m`` wins.
    """
    m = is_m
    if (not m or m.get("ic_mean") is None) and os_m and os_m.get("ic_mean") is not None:
        m = os_m
    if not m:
        return ("INCOMPLETE", "missing metrics")

    ic_mean = m.get("ic_mean")
    ic_ir = m.get("ic_ir")
    n = int(m.get("total_trades") or 0)

    if ic_mean is None or ic_ir is None:
        return ("NORMAL", "IC not computed — re-run backtest to populate")

    abs_ic = abs(float(ic_mean))
    abs_ir = abs(float(ic_ir))

    # Sign-agnostic SUBMITTABLE gates:
    #   |IC|    > 0.03 — "weak but real" edge (≥0.05 is healthy)
    #   |IC_IR| > 1.5  — IC stable across bars (within-window stationarity)
    #   |IC_z|  < 2.0  — IS↔OS IC means agree (Welch test): overfit guard
    #   trades  > 500  — sample sufficiency
    #   |IS MDD|< 0.50 — IS-window max drawdown ≤ 50% (risk magnitude)
    z = m.get("ic_z")
    abs_z = abs(float(z)) if z is not None else None
    mdd = m.get("max_drawdown")
    abs_mdd = abs(float(mdd)) if mdd is not None else None
    parts = f"|IC|={abs_ic:.3f} |IR|={abs_ir:.2f} trades={n}"
    if abs_z is not None:
        parts += f" |z|={abs_z:.2f}"
    if abs_mdd is not None:
        parts += f" |MDD|={abs_mdd:.2%}"
    z_ok = (abs_z is None) or (abs_z < 2.0)
    mdd_ok = (abs_mdd is None) or (abs_mdd < 0.50)
    if abs_ic > 0.03 and abs_ir > 1.5 and n > 500 and z_ok and mdd_ok:
        return ("SUBMITTABLE", parts)
    return ("NORMAL", parts)


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


def _is_flat_layout(alpha_dir: Path) -> bool:
    """Flat (loader-gateway) layout: backtest ran once and wrote a single
    metrics.json + raw parquet at alpha_dir/, with IS/OS blocks inside
    metrics.json. Detected by the presence of the top-level metrics.json
    AND the absence of an is/ subdirectory (a legacy two-dir alpha
    always has an is/ subfolder)."""
    return (alpha_dir / "metrics.json").exists() and not (alpha_dir / "is").is_dir()


def _split_has_data(split_dir: Path) -> bool:
    """A split directory counts as "having data" if it contains either a
    ``metrics.json`` (backtest splits) or an ``equity_curve.parquet``
    (forward-style outputs that may not have a finalized metrics file yet)."""
    if not split_dir.is_dir():
        return False
    return (split_dir / "metrics.json").exists() or (split_dir / "equity_curve.parquet").exists()


def discover_splits(alpha_dir: Path) -> list[str]:
    """Return splits with data for ``alpha_dir`` in canonical order
    (``is`` → ``os`` → ``forward``). Supports both the legacy two-dir
    layout (is/, os/, forward/ subfolders) and the new flat layout
    (single metrics.json with is/os sub-blocks)."""
    alpha_dir = Path(alpha_dir)
    if _is_flat_layout(alpha_dir):
        try:
            payload = json.loads((alpha_dir / "metrics.json").read_text())
        except Exception:
            return []
        out: list[str] = []
        if payload.get("is"):
            out.append("is")
        if payload.get("os"):
            out.append("os")
        # Forward is always a subdir, even in flat layout.
        if _split_has_data(alpha_dir / "forward"):
            out.append("forward")
        return out
    return [s for s in SPLIT_ORDER if _split_has_data(alpha_dir / s)]


def read_metrics_for_split(alpha_dir: Path, split: str) -> dict | None:
    """Return metric dict for ``split`` ('is'|'os') in either layout.

    Legacy: ``alpha_dir/<split>/metrics.json``.
    Flat:   ``alpha_dir/metrics.json``[<split>].
    Returns ``None`` if the split is not present.

    Note: callers running under the seal_check hook will be blocked if
    they read flat metrics.json directly. Dashboards run with
    ``SEAL_OPEN=1`` set and use this helper. Agents must use
    ``scripts/tools/load_alpha.py`` from the shell instead.
    """
    alpha_dir = Path(alpha_dir)
    if _is_flat_layout(alpha_dir):
        try:
            payload = json.loads((alpha_dir / "metrics.json").read_text())
        except Exception:
            return None
        sub = payload.get(split) or {}
        if not isinstance(sub, dict):
            return None
        # Fall back to top-level fields for trade-level stats that
        # _compute_split_metrics doesn't carve out into the IS/OS
        # sub-blocks yet (t_stat, per_trade_sharpe, pnl_bps_*, calmar,
        # avg_win_bps, ...). Top-level is full-period rather than
        # split-specific but is better than rendering "-" everywhere.
        merged = dict(sub)
        for key, val in payload.items():
            if key in ("is", "os", "full"):
                continue
            merged.setdefault(key, val)
        return merged
    legacy = alpha_dir / split / "metrics.json"
    if not legacy.exists():
        return None
    try:
        return json.loads(legacy.read_text())
    except Exception:
        return None


def read_split_parquet(alpha_dir: Path, kind: str, split: str):
    """Return a DataFrame for ``kind`` ('equity_curve'|'trades'|'weights')
    on ``split`` ('is'|'os'). Returns ``None`` if the artifact is absent.

    Legacy: ``alpha_dir/<split>/<kind>.parquet``.
    Flat:   ``alpha_dir/<kind>.parquet`` sliced by metrics.json's
            ``is_end`` timestamp.
    """
    import pandas as pd  # local import — keep module import cheap

    alpha_dir = Path(alpha_dir)
    if _is_flat_layout(alpha_dir):
        p = alpha_dir / f"{kind}.parquet"
        if not p.exists():
            return None
        df = pd.read_parquet(p)
        try:
            payload = json.loads((alpha_dir / "metrics.json").read_text())
            is_end_str = payload.get("is_end")
        except Exception:
            is_end_str = None
        if is_end_str and "timestamp" in df.columns:
            df = df.copy()
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            cutoff = pd.Timestamp(is_end_str)
            if split == "is":
                df = df[df["timestamp"] <= cutoff]
            elif split == "os":
                df = df[df["timestamp"] > cutoff]
        return df
    legacy = alpha_dir / split / f"{kind}.parquet"
    if not legacy.exists():
        return None
    return pd.read_parquet(legacy)


def is_forward_live(forward_dir: Path) -> bool:
    """A forward split is "live" iff its most recent emit timestamp is
    within ~1.5× the candle period. Driven by cron + run_forward_tick.py
    these days — no long-running runner, no pid.txt. Legacy pid.txt
    still wins if present (back-compat for older alphas)."""
    forward_dir = Path(forward_dir)
    import datetime as _dt
    pid_path = forward_dir / "pid.txt"
    if pid_path.exists():
        try:
            pid = int(pid_path.read_text().strip())
            if pid > 0:
                os.kill(pid, 0)
                return True
        except (OSError, ProcessLookupError, ValueError):
            pass
    weights = forward_dir / "weights.parquet"
    if not weights.exists():
        return False
    try:
        import pandas as pd
        ts = pd.read_parquet(weights, columns=["timestamp"])["timestamp"]
        last = pd.to_datetime(ts).max()
        if pd.isna(last):
            return False
        last_dt = last.to_pydatetime()
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=_dt.timezone.utc)
        now = _dt.datetime.now(_dt.timezone.utc)
        # Infer candle period from the parquet timestamps (median spacing).
        # Daily candles → ~86400s window. 1-minute → ~60s window.
        ts_sorted = pd.to_datetime(ts).drop_duplicates().sort_values()
        if len(ts_sorted) < 2:
            return (now - last_dt).total_seconds() <= 86400 * 1.5
        diffs = ts_sorted.diff().dt.total_seconds().dropna()
        period = float(diffs.median()) if not diffs.empty else 86400.0
        return (now - last_dt).total_seconds() <= max(period * 1.5, 60.0)
    except Exception:
        return False


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

    # Cron-driven mode (no daemon, no pid.txt): liveness = weights.parquet
    # freshness. PID / uptime become "cron" / time-since-first-emit.
    if not result["live"]:
        if is_forward_live(forward_dir):
            result["live"] = True
            result["pid"] = "cron"
            weights = forward_dir / "weights.parquet"
            if weights.exists():
                try:
                    ts = pd.read_parquet(weights, columns=["timestamp"])["timestamp"]
                    started = pd.to_datetime(ts).min()
                    if pd.notna(started):
                        started_dt = started.to_pydatetime()
                        if started_dt.tzinfo is not None:
                            started_dt = started_dt.replace(tzinfo=None)
                        result["started_at"] = started_dt
                        result["uptime_seconds"] = max(
                            0.0, (datetime.now() - started_dt).total_seconds()
                        )
                except Exception:
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
