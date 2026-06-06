#!/usr/bin/env python3
"""Build an IS-only selected composite from archived alpha weights.

The optimizer uses only IS daily returns to choose signs and members. The
resulting fixed coefficients are then applied to each selected alpha's full
``weights.parquet`` and replayed through the normal backtest CLI with
``PrecomputedWeightsStrategy``.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform
from sklearn.cluster import AffinityPropagation


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
from intraday.composites._optim_helpers import family_dedup  # noqa: E402

ARCHIVE = REPO / "archive"
BACKTEST = REPO / "scripts" / "tools" / "backtest.py"
DATA_ROOT = REPO / "data" / "futures_klines_daily"
ANNUAL_BARS = 252
GROSS_EPS = 1e-12


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _daily_returns(
    alpha_dir: Path,
    *,
    start: str | None = None,
    end: str | None = None,
) -> pd.Series | None:
    path = alpha_dir / "equity_curve.parquet"
    if not path.exists():
        return None
    df = pd.read_parquet(path, columns=["timestamp", "equity"])
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    if start:
        df = df[df["timestamp"] >= pd.Timestamp(start)]
    if end:
        df = df[df["timestamp"] <= pd.Timestamp(end)]
    if df.empty:
        return None
    eod = (
        # Match oracle_ceiling_eda.py exactly. The equity curve contains
        # multiple rows per daily timestamp; the historical EDA ground truth
        # sorts by timestamp and takes the last row inside the split file.
        # Filtering to IS/OS before this step is the important lookahead guard.
        df.sort_values("timestamp")
        .assign(date=df["timestamp"].dt.normalize())
        .groupby("date")["equity"]
        .last()
    )
    if len(eod) < 2:
        return None
    ret = eod.pct_change().dropna()
    return ret if not ret.empty else None


def _sharpe(ret: pd.Series) -> float:
    sd = ret.std(ddof=1)
    if not sd or not math.isfinite(float(sd)):
        return 0.0
    return float(ret.mean() / sd * math.sqrt(ANNUAL_BARS))


def _select_hierarchical(
    returns_is: pd.DataFrame,
    *,
    corr_threshold: float,
    max_abs_daily: float,
) -> tuple[list[str], dict[str, int], dict[str, float], dict[str, float]]:
    max_abs = returns_is.abs().max(axis=0)
    keep_cols = max_abs[max_abs <= max_abs_daily].index.tolist()
    R = returns_is[keep_cols].copy()
    raw_sharpes = {c: _sharpe(R[c]) for c in R.columns}
    signs = {c: (-1 if raw_sharpes[c] < 0 else 1) for c in R.columns}
    signed = R.mul(pd.Series(signs), axis=1)
    sharpes = {c: _sharpe(signed[c]) for c in signed.columns}

    corr = signed.corr().fillna(0.0).clip(-1.0, 1.0)
    rho = corr.values
    D = np.sqrt(0.5 * (1.0 - rho))
    np.fill_diagonal(D, 0.0)
    D = 0.5 * (D + D.T)
    Z = linkage(squareform(D, checks=False), method="ward")
    cut_distance = math.sqrt(0.5 * (1.0 - corr_threshold))
    clusters = fcluster(Z, t=cut_distance, criterion="distance")

    names = list(corr.columns)
    rep: dict[int, str] = {}
    cluster_for: dict[str, int] = {}
    for aid, cluster_id in zip(names, clusters):
        cid = int(cluster_id)
        cluster_for[aid] = cid
        if cid not in rep or sharpes[aid] > sharpes[rep[cid]]:
            rep[cid] = aid
    selected = sorted(rep.values())
    return selected, cluster_for, signs, sharpes


def _greedy_drop(corr: pd.DataFrame, sharpes: dict[str, float], threshold: float) -> list[str]:
    ranked = sorted(corr.columns, key=lambda a: sharpes.get(a, 0.0), reverse=True)
    kept: list[str] = []
    for aid in ranked:
        if all(corr.at[aid, k] < threshold for k in kept):
            kept.append(aid)
    return kept


def _hierarchical_pruning(
    corr: pd.DataFrame,
    sharpes: dict[str, float],
    threshold: float,
) -> tuple[list[str], dict[str, int]]:
    if len(corr.columns) <= 1:
        return list(corr.columns), {str(c): 1 for c in corr.columns}
    rho = corr.clip(-1.0, 1.0).values
    D = np.sqrt(0.5 * (1.0 - rho))
    np.fill_diagonal(D, 0.0)
    D = 0.5 * (D + D.T)
    Z = linkage(squareform(D, checks=False), method="ward")
    cut_distance = math.sqrt(0.5 * (1.0 - threshold))
    clusters = fcluster(Z, t=cut_distance, criterion="distance")
    names = list(corr.columns)
    rep: dict[int, str] = {}
    cluster_for: dict[str, int] = {}
    for aid, cluster_id in zip(names, clusters):
        cid = int(cluster_id)
        cluster_for[aid] = cid
        if cid not in rep or sharpes[aid] > sharpes[rep[cid]]:
            rep[cid] = aid
    return list(rep.values()), cluster_for


def _ap_then_greedy(
    corr: pd.DataFrame,
    sharpes: dict[str, float],
    threshold: float,
) -> list[str]:
    if len(corr.columns) <= 1:
        return list(corr.columns)
    sim = corr.values.astype(float)
    sim = 0.5 * (sim + sim.T)
    np.fill_diagonal(sim, np.nan)
    median_off_diag = float(np.nanmedian(sim))
    np.fill_diagonal(sim, median_off_diag)
    ap = AffinityPropagation(
        affinity="precomputed",
        damping=0.9,
        preference=median_off_diag,
        max_iter=500,
        convergence_iter=25,
        random_state=0,
    )
    labels = ap.fit_predict(sim)
    names = list(corr.columns)
    rep: dict[int, str] = {}
    for aid, cluster_id in zip(names, labels):
        cid = int(cluster_id)
        if cid not in rep or sharpes[aid] > sharpes[rep[cid]]:
            rep[cid] = aid
    exemplars = list(rep.values())
    return _greedy_drop(corr.loc[exemplars, exemplars], sharpes, threshold)


def _fit_eda_pipelines(
    R_is: pd.DataFrame,
    R_os: pd.DataFrame,
    *,
    corr_threshold: float,
    max_abs_daily: float,
) -> tuple[dict[str, list[str]], dict[str, int], dict[str, int | None], dict[str, float]]:
    if max_abs_daily and max_abs_daily > 0:
        keep_mask = R_is.abs().max() <= max_abs_daily
        R_is = R_is.loc[:, keep_mask]
    common = [c for c in R_is.columns if c in R_os.columns]
    R_is = R_is[common]

    raw_sharpes = {c: _sharpe(R_is[c]) for c in R_is.columns}
    signs = {c: (-1 if raw_sharpes[c] < 0 else 1) for c in R_is.columns}
    signed = R_is.mul(pd.Series(signs), axis=1)
    sharpes = {c: _sharpe(signed[c]) for c in signed.columns}
    corr = signed.corr()

    hier, clusters = _hierarchical_pruning(corr, sharpes, corr_threshold)
    pipelines = {
        "Baseline (EQW all)": list(R_is.columns),
        "Greedy Drop": _greedy_drop(corr, sharpes, corr_threshold),
        "Hierarchical Pruning": hier,
        "AP + Greedy": _ap_then_greedy(corr, sharpes, corr_threshold),
    }
    return pipelines, signs, clusters, sharpes


def _load_weight_events(alpha_dir: Path, universe: list[str]) -> pd.DataFrame:
    path = alpha_dir / "weights.parquet"
    if not path.exists():
        return pd.DataFrame(columns=["timestamp", "symbol", "target_weight"])
    df = pd.read_parquet(path, columns=["timestamp", "symbol", "target_weight"])
    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["symbol"] = df["symbol"].astype(str).str.upper()
    df = df[df["symbol"].isin(universe)]
    df = (
        df.sort_values("timestamp")
        .groupby(["timestamp", "symbol"], as_index=False, sort=False)
        .agg(target_weight=("target_weight", "last"))
    )
    return df


def _events_to_panel(events: pd.DataFrame, universe: list[str]) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame(columns=universe)
    return (
        events.pivot_table(
            index="timestamp",
            columns="symbol",
            values="target_weight",
            aggfunc="last",
        )
        .reindex(columns=universe)
        .sort_index()
    )


def _combine_weights(
    panels: dict[str, pd.DataFrame],
    coefficients: dict[str, float],
    universe: list[str],
    *,
    target_gross: float | None = None,
    max_gross: float = 1.0,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    combined, stats = _combine_weight_panel(
        panels,
        coefficients,
        universe,
        target_gross=target_gross,
        max_gross=max_gross,
    )

    long_df = _panel_to_rebalance_rows(combined, universe)
    stats["n_change_events"] = int(len(long_df))
    return long_df, stats


def _panel_to_rebalance_rows(panel: pd.DataFrame, universe: list[str]) -> pd.DataFrame:
    rows: list[tuple[pd.Timestamp, str, float]] = []
    prev = pd.DataFrame(index=panel.index, columns=universe, dtype=float)
    if not panel.empty:
        prev = panel[universe].shift().fillna(0.0)
    for ts in panel.index:
        cur = panel.loc[ts, universe]
        was = prev.loc[ts, universe]
        active_or_closing = (cur.abs() > GROSS_EPS) | (was.abs() > GROSS_EPS)
        for symbol in cur.index[active_or_closing]:
            rows.append((ts, symbol, float(cur.loc[symbol])))
    return (
        pd.DataFrame(rows, columns=["timestamp", "symbol", "target_weight"])
        .sort_values(["timestamp", "symbol"])
        .reset_index(drop=True)
    )


def _combine_weight_panel(
    panels: dict[str, pd.DataFrame],
    coefficients: dict[str, float],
    universe: list[str],
    *,
    target_gross: float | None = None,
    max_gross: float = 1.0,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    usable = {aid: p for aid, p in panels.items() if not p.empty}
    all_ts = sorted(set().union(*[p.index for p in usable.values()]))
    idx = pd.DatetimeIndex(all_ts)
    combined = pd.DataFrame(0.0, index=idx, columns=universe)
    for aid, panel in usable.items():
        aligned = panel.reindex(idx).ffill().fillna(0.0)
        combined = combined.add(aligned * float(coefficients[aid]), fill_value=0.0)
    combined = combined[universe]

    raw_l1 = combined.abs().sum(axis=1)
    base_scale = pd.Series(1.0, index=idx)
    if target_gross is not None:
        target = min(float(target_gross), float(max_gross))
        base_scale = pd.Series(target, index=idx) / raw_l1.replace(0.0, np.nan)
        base_scale = base_scale.replace([np.inf, -np.inf], np.nan).fillna(1.0)
    target_l1 = raw_l1 * base_scale
    n_clipped = int((target_l1 > float(max_gross) + GROSS_EPS).sum())
    cap_scale = pd.Series(1.0, index=idx).where(
        target_l1 <= float(max_gross),
        float(max_gross) / target_l1.replace(0.0, 1.0),
    )
    scale = base_scale * cap_scale
    combined = combined.mul(scale, axis=0)
    final_l1 = combined.abs().sum(axis=1)
    stats = {
        "max_row_l1": float(final_l1.max()) if len(final_l1) else 0.0,
        "mean_row_l1": float(final_l1.mean()) if len(final_l1) else 0.0,
        "raw_max_row_l1": float(raw_l1.max()) if len(raw_l1) else 0.0,
        "raw_mean_row_l1": float(raw_l1.mean()) if len(raw_l1) else 0.0,
        "n_rows_clipped": n_clipped,
        "target_gross": target_gross,
        "max_gross": float(max_gross),
    }
    return combined, stats


def _load_price_returns(universe: list[str], *, start: str, end: str) -> pd.DataFrame:
    series: dict[str, pd.Series] = {}
    start_ts = pd.Timestamp(start).normalize()
    end_ts = pd.Timestamp(end).normalize()
    for symbol in universe:
        files = sorted((DATA_ROOT / symbol).glob("*.parquet"))
        if not files:
            continue
        chunks = [
            pd.read_parquet(path, columns=["timestamp", "close"])
            for path in files
        ]
        df = pd.concat(chunks, ignore_index=True)
        df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.normalize()
        df = df[(df["timestamp"] >= start_ts) & (df["timestamp"] <= end_ts)]
        if df.empty:
            continue
        close = df.sort_values("timestamp").drop_duplicates("timestamp", keep="last").set_index("timestamp")["close"]
        ret = close.pct_change()
        series[symbol] = ret
    return pd.DataFrame(series).sort_index().fillna(0.0)


def _portfolio_proxy_returns(
    panels: dict[str, pd.DataFrame],
    coefficients: dict[str, float],
    universe: list[str],
    price_returns: pd.DataFrame,
    *,
    target_gross: float | None = None,
    max_gross: float = 1.0,
) -> pd.Series:
    combined, _ = _combine_weight_panel(
        panels,
        coefficients,
        universe,
        target_gross=target_gross,
        max_gross=max_gross,
    )
    if combined.empty or price_returns.empty:
        return pd.Series(dtype=float)
    daily_weights = (
        combined.sort_index()
        .assign(date=combined.index.normalize())
        .groupby("date")
        .last()
        .reindex(price_returns.index)
        .ffill()
        .fillna(0.0)
    )
    aligned_returns = price_returns.reindex(columns=universe).fillna(0.0)
    # Use yesterday's target for today's close-to-close return. This keeps the
    # proxy causal and conservative for IS-only member selection.
    return (daily_weights.shift().fillna(0.0) * aligned_returns).sum(axis=1)


def _proxy_score(ret: pd.Series, objective: str) -> float:
    ret = ret.dropna()
    if ret.empty:
        return -float("inf")
    if objective == "sharpe":
        return _sharpe(ret)
    if objective == "return":
        return float(ret.sum())
    raise ValueError(f"unknown netted greedy objective: {objective}")


def _netted_greedy_drop(
    selected: list[str],
    panels: dict[str, pd.DataFrame],
    signs: dict[str, int],
    universe: list[str],
    price_returns_is: pd.DataFrame,
    *,
    min_members: int,
    objective: str,
    min_improvement: float,
    target_gross: float | None = None,
    max_gross: float = 1.0,
) -> tuple[list[str], dict[str, Any]]:
    kept = list(selected)

    def coeffs(names: list[str]) -> dict[str, float]:
        return {aid: float(signs[aid]) / len(names) for aid in names}

    current_ret = _portfolio_proxy_returns(
        {aid: panels[aid] for aid in kept},
        coeffs(kept),
        universe,
        price_returns_is,
        target_gross=target_gross,
        max_gross=max_gross,
    )
    current_score = _proxy_score(current_ret, objective)
    drops: list[dict[str, Any]] = []
    while len(kept) > min_members:
        best_drop: str | None = None
        best_score = current_score
        for aid in kept:
            trial = [x for x in kept if x != aid]
            ret = _portfolio_proxy_returns(
                {x: panels[x] for x in trial},
                coeffs(trial),
                universe,
                price_returns_is,
                target_gross=target_gross,
                max_gross=max_gross,
            )
            score = _proxy_score(ret, objective)
            if score > best_score + min_improvement:
                best_score = score
                best_drop = aid
        if best_drop is None:
            break
        kept.remove(best_drop)
        drops.append(
            {
                "dropped": best_drop,
                "score_before": current_score,
                "score_after": best_score,
                "n_members_after": len(kept),
            }
        )
        current_score = best_score

    return kept, {
        "netted_greedy_objective": objective,
        "netted_greedy_initial_members": len(selected),
        "netted_greedy_final_members": len(kept),
        "netted_greedy_initial_score": float(_proxy_score(current_ret, objective)),
        "netted_greedy_final_score": float(current_score),
        "netted_greedy_drops": drops,
    }


def _rolling_hierarchical_schedule(
    R_full: pd.DataFrame,
    *,
    lookback_days: int,
    rebalance_freq: str,
    corr_threshold: float,
    max_abs_daily: float,
) -> tuple[list[dict[str, Any]], dict[str, int], dict[str, float], dict[str, int | None], dict[str, float]]:
    all_dates = R_full.index.sort_values()
    if len(all_dates) <= lookback_days:
        raise RuntimeError(f"not enough bars for rolling lookback: {len(all_dates)} <= {lookback_days}")
    eligible = all_dates[lookback_days:]
    rebal_dates = [d for d in pd.date_range(eligible[0], eligible[-1], freq=rebalance_freq) if d in all_dates]
    if rebal_dates and rebal_dates[0] != eligible[0]:
        rebal_dates = [eligible[0]] + rebal_dates
    rebal_dates = sorted(set(pd.Timestamp(d) for d in rebal_dates))
    if not rebal_dates:
        raise RuntimeError("no rebalance dates available")

    schedule: list[dict[str, Any]] = []
    all_signs: dict[str, int] = {}
    all_sharpes: dict[str, float] = {}
    cluster_last: dict[str, int | None] = {}
    for i, rebal_date in enumerate(rebal_dates):
        lb_mask = (all_dates < rebal_date) & (all_dates >= rebal_date - pd.Timedelta(days=lookback_days * 1.5))
        lookback_idx = all_dates[lb_mask]
        if len(lookback_idx) < lookback_days // 2:
            continue
        lookback_idx = lookback_idx[-lookback_days:]
        R_lb = R_full.loc[lookback_idx]
        if max_abs_daily and max_abs_daily > 0:
            R_lb = R_lb.loc[:, R_lb.abs().max() <= max_abs_daily]
        active_cols = R_lb.columns[R_lb.std() > 0].tolist()
        if len(active_cols) < 4:
            continue
        R_lb = R_lb[active_cols]
        raw_sharpes = {c: _sharpe(R_lb[c]) for c in R_lb.columns}
        signs = {c: (-1 if raw_sharpes[c] < 0 else 1) for c in R_lb.columns}
        signed = R_lb.mul(pd.Series(signs), axis=1)
        sharpes = {c: _sharpe(signed[c]) for c in signed.columns}
        corr = signed.corr().fillna(0.0)
        selected, clusters = _hierarchical_pruning(corr, sharpes, corr_threshold)
        selected = sorted(selected)
        if not selected:
            continue
        for aid, sign in signs.items():
            all_signs[aid] = sign
        all_sharpes.update(sharpes)
        cluster_last.update(clusters)
        fwd_end = rebal_dates[i + 1] if i + 1 < len(rebal_dates) else all_dates[-1] + pd.Timedelta(days=1)
        schedule.append(
            {
                "rebal_date": rebal_date,
                "end_date": pd.Timestamp(fwd_end),
                "selected": selected,
                "signs": {aid: signs[aid] for aid in selected},
                "coefficients": {aid: float(signs[aid]) / len(selected) for aid in selected},
                "n_selected": len(selected),
                "n_flipped": int(sum(1 for aid in selected if signs[aid] < 0)),
            }
        )
    if not schedule:
        raise RuntimeError("rolling hierarchical schedule is empty")
    return schedule, all_signs, cluster_last, all_sharpes, {"n_rebalance_dates": len(schedule)}


def _combine_rolling_weights(
    panels: dict[str, pd.DataFrame],
    schedule: list[dict[str, Any]],
    universe: list[str],
    *,
    target_gross: float | None = None,
    max_gross: float = 1.0,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    frames: list[pd.DataFrame] = []
    for item in schedule:
        start = pd.Timestamp(item["rebal_date"])
        end = pd.Timestamp(item["end_date"])
        selected = list(item["selected"])
        interval_ts: set[pd.Timestamp] = {start}
        for aid in selected:
            panel = panels[aid]
            interval_ts.update(ts for ts in panel.index if start <= ts < end)
        idx = pd.DatetimeIndex(sorted(interval_ts))
        combined = pd.DataFrame(0.0, index=idx, columns=universe)
        for aid in selected:
            panel = panels[aid]
            aligned_idx = panel.index.union(idx)
            aligned = panel.reindex(aligned_idx).sort_index().ffill().reindex(idx).fillna(0.0)
            combined = combined.add(aligned * float(item["coefficients"][aid]), fill_value=0.0)
        combined = combined[universe]
        raw_l1 = combined.abs().sum(axis=1)
        base_scale = pd.Series(1.0, index=idx)
        if target_gross is not None:
            target = min(float(target_gross), float(max_gross))
            base_scale = pd.Series(target, index=idx) / raw_l1.replace(0.0, np.nan)
            base_scale = base_scale.replace([np.inf, -np.inf], np.nan).fillna(1.0)
        target_l1 = raw_l1 * base_scale
        cap_scale = pd.Series(1.0, index=idx).where(
            target_l1 <= float(max_gross),
            float(max_gross) / target_l1.replace(0.0, 1.0),
        )
        frames.append(combined.mul(base_scale * cap_scale, axis=0))
    panel = pd.concat(frames).sort_index()
    panel = panel[~panel.index.duplicated(keep="last")]
    raw_l1 = panel.abs().sum(axis=1)
    long_df = _panel_to_rebalance_rows(panel, universe)
    stats = {
        "n_change_events": int(len(long_df)),
        "max_row_l1": float(raw_l1.max()) if len(raw_l1) else 0.0,
        "mean_row_l1": float(raw_l1.mean()) if len(raw_l1) else 0.0,
        "raw_max_row_l1": float(raw_l1.max()) if len(raw_l1) else 0.0,
        "raw_mean_row_l1": float(raw_l1.mean()) if len(raw_l1) else 0.0,
        "n_rows_clipped": 0,
        "target_gross": target_gross,
        "max_gross": float(max_gross),
    }
    return long_df, stats


def _run_backtest(
    *,
    output_dir: Path,
    weights_path: Path,
    symbols: list[str],
    splits: dict[str, Any],
    alpha_id: str,
    max_portfolio_weight: float = 1.0,
) -> int:
    cmd = [
        sys.executable,
        str(BACKTEST),
        "--strategy",
        "PrecomputedWeightsStrategy",
        "--symbols",
        *symbols,
        "--data-type",
        "bars",
        "--data-path",
        "data/futures_klines_daily",
        "--bar-type",
        "TIME",
        "--bar-size",
        "86400",
        "--start",
        splits["is"]["start"],
        "--end",
        splits["os"]["end"],
        "--is-end",
        splits["is"]["end"],
        "--initial-capital",
        "10000",
        "--fixed-aum-sizing",
        "--max-portfolio-weight",
        str(max_portfolio_weight),
        "--maker-fee-rate",
        "0.0002",
        "--taker-fee-rate",
        "0.0005",
        "--strategy-params",
        json.dumps({"weights_path": str(weights_path), "alpha_id": alpha_id}),
        "--output-dir",
        str(output_dir),
        "--no-enforce-quality",
        "--no-enforce-governance",
        "--json",
    ]
    proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, check=False)
    if proc.returncode not in (0, 2):
        print(proc.stdout[-4000:], file=sys.stderr)
        print(proc.stderr[-4000:], file=sys.stderr)
    if not (output_dir / "metrics.json").exists():
        print(proc.stdout[-4000:], file=sys.stderr)
        print(proc.stderr[-4000:], file=sys.stderr)
        raise RuntimeError(f"backtest failed rc={proc.returncode}; no metrics.json")
    return int(proc.returncode)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default="run_2026_05_full531_rerun_backtests")
    parser.add_argument("--composite-id", default="static_hierarchical_pruning_weight_composite_v1")
    parser.add_argument(
        "--selection-metrics",
        help="Optional validation target. Selection is still recomputed from returns.",
    )
    parser.add_argument(
        "--pipeline",
        action="append",
        default=[],
        help="Pipeline name from selection metrics. Repeatable. Use 'all' for every pipeline.",
    )
    parser.add_argument(
        "--selected-alpha",
        action="append",
        default=[],
        help="Explicit alpha member. Repeat for a fixed IS-defined family ensemble.",
    )
    parser.add_argument("--corr-threshold", type=float, default=0.3)
    parser.add_argument("--max-abs-daily", type=float, default=1.0)
    parser.add_argument("--min-is-sharpe", type=float, default=None)
    parser.add_argument("--family-dedup", action="store_true")
    parser.add_argument("--family-level", default="signal_dir")
    parser.add_argument("--target-gross", type=float, default=None)
    parser.add_argument("--max-gross", type=float, default=1.0)
    parser.add_argument("--rolling", action="store_true")
    parser.add_argument("--rolling-lookback-days", type=int, default=756)
    parser.add_argument("--rolling-rebalance-freq", default="MS")
    parser.add_argument("--netted-greedy", action="store_true")
    parser.add_argument("--netted-greedy-min-members", type=int, default=8)
    parser.add_argument(
        "--netted-greedy-objective",
        choices=["return", "sharpe"],
        default="return",
    )
    parser.add_argument("--netted-greedy-min-improvement", type=float, default=1e-5)
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args(argv)

    run_dir = ARCHIVE / args.run_id
    splits = _read_json(run_dir / "splits.json")
    requested_universe = [s.upper() for s in splits["universe"]]
    missing_symbols = [s for s in requested_universe if not (DATA_ROOT / s).exists()]
    universe = [s for s in requested_universe if s not in set(missing_symbols)]

    alpha_dirs = sorted(p for p in (run_dir / "alphas").iterdir() if p.is_dir())
    returns_is: dict[str, pd.Series] = {}
    returns_os: dict[str, pd.Series] = {}
    for alpha_dir in alpha_dirs:
        ret_is = _daily_returns(
            alpha_dir,
            start=splits["is"]["start"],
            end=splits["is"]["end"],
        )
        ret_os = _daily_returns(
            alpha_dir,
            start=splits["os"]["start"],
            end=splits["os"]["end"],
        )
        if ret_is is not None and len(ret_is) >= 60:
            returns_is[alpha_dir.name] = ret_is
        if ret_os is not None and len(ret_os) >= 60:
            returns_os[alpha_dir.name] = ret_os
    R_is = pd.DataFrame(returns_is).sort_index().fillna(0.0)
    R_os = pd.DataFrame(returns_os).sort_index().fillna(0.0)
    if R_is.empty or R_os.empty:
        raise RuntimeError("no IS/OS returns available")
    if args.min_is_sharpe is not None:
        keep = [
            col for col in R_is.columns
            if _sharpe(R_is[col]) >= float(args.min_is_sharpe)
        ]
        R_is = R_is[keep]
        R_os = R_os[[col for col in keep if col in R_os.columns]]
        if R_is.empty or R_os.empty:
            raise RuntimeError(f"no alphas passed --min-is-sharpe {args.min_is_sharpe}")
    if args.family_dedup:
        keep_metric = {col: _sharpe(R_is[col]) for col in R_is.columns}
        keep = family_dedup(list(R_is.columns), keep_metric, level=str(args.family_level))
        R_is = R_is[keep]
        R_os = R_os[[col for col in keep if col in R_os.columns]]
        if R_is.empty or R_os.empty:
            raise RuntimeError("no alphas remained after --family-dedup")

    pipelines, signs, clusters, sharpes = _fit_eda_pipelines(
        R_is,
        R_os,
        corr_threshold=float(args.corr_threshold),
        max_abs_daily=float(args.max_abs_daily),
    )
    if args.selected_alpha:
        selected_explicit = [str(a) for a in args.selected_alpha]
        missing = [a for a in selected_explicit if a not in R_is.columns]
        if missing:
            raise KeyError(f"--selected-alpha missing from candidate returns: {missing}")
        pipelines = {"Explicit Selection": selected_explicit}
        signs = {a: (-1 if _sharpe(R_is[a]) < 0 else 1) for a in selected_explicit}
        sharpes = {a: _sharpe(R_is[a] * signs[a]) for a in selected_explicit}
        clusters = {a: i + 1 for i, a in enumerate(selected_explicit)}

    requested = args.pipeline or (["Explicit Selection"] if args.selected_alpha else ["Hierarchical Pruning"])
    if requested == ["all"] or "all" in requested:
        requested = list(pipelines)

    validation: dict[str, Any] = {}
    if args.selection_metrics:
        target = _read_json(Path(args.selection_metrics))
        for pipeline_name, selected in pipelines.items():
            expected = set((target.get(pipeline_name) or {}).get("kept_alphas", []))
            actual = set(selected)
            validation[pipeline_name] = {
                "expected_n": len(expected),
                "actual_n": len(actual),
                "matches": expected == actual,
                "missing": sorted(expected - actual),
                "extra": sorted(actual - expected),
            }

    outputs = []
    for pipeline_name in requested:
        if pipeline_name not in pipelines:
            raise KeyError(f"pipeline not available: {pipeline_name}")
        if args.rolling and pipeline_name != "Hierarchical Pruning":
            raise ValueError("--rolling currently implements the Hierarchical Pruning pipeline only")
        selected = pipelines[pipeline_name]
        extra_manifest: dict[str, Any] = {}
        panels_for_pipeline = {
            aid: _events_to_panel(_load_weight_events(run_dir / "alphas" / aid, universe), universe)
            for aid in selected
        }
        rolling_schedule: list[dict[str, Any]] | None = None
        if args.rolling:
            common = [c for c in R_is.columns if c in R_os.columns]
            R_full = pd.concat([R_is[common], R_os[common]]).sort_index()
            R_full = R_full[~R_full.index.duplicated(keep="first")].fillna(0.0)
            rolling_schedule, signs_roll, clusters_roll, sharpes_roll, roll_meta = _rolling_hierarchical_schedule(
                R_full,
                lookback_days=int(args.rolling_lookback_days),
                rebalance_freq=str(args.rolling_rebalance_freq),
                corr_threshold=float(args.corr_threshold),
                max_abs_daily=float(args.max_abs_daily),
            )
            selected = sorted({aid for item in rolling_schedule for aid in item["selected"]})
            signs = {**signs, **signs_roll}
            clusters = {**clusters, **clusters_roll}
            sharpes = {**sharpes, **sharpes_roll}
            panels_for_pipeline = {
                aid: _events_to_panel(_load_weight_events(run_dir / "alphas" / aid, universe), universe)
                for aid in selected
            }
            extra_manifest.update(
                {
                    "rolling": True,
                    "rolling_lookback_days": int(args.rolling_lookback_days),
                    "rolling_rebalance_freq": str(args.rolling_rebalance_freq),
                    "rolling_selection_log": [
                        {
                            "rebal_date": str(item["rebal_date"]),
                            "end_date": str(item["end_date"]),
                            "n_selected": item["n_selected"],
                            "n_flipped": item["n_flipped"],
                            "members": item["selected"],
                        }
                        for item in rolling_schedule
                    ],
                    **roll_meta,
                }
            )
        if args.netted_greedy:
            price_returns_is = _load_price_returns(
                universe,
                start=splits["is"]["start"],
                end=splits["is"]["end"],
            )
            selected, extra_manifest = _netted_greedy_drop(
                selected,
                panels_for_pipeline,
                signs,
                universe,
                price_returns_is,
                min_members=int(args.netted_greedy_min_members),
                objective=str(args.netted_greedy_objective),
                min_improvement=float(args.netted_greedy_min_improvement),
                target_gross=args.target_gross,
                max_gross=float(args.max_gross),
            )
        coef = {aid: float(signs[aid]) / len(selected) for aid in selected}
        slug = re.sub(r"[^a-z0-9]+", "_", pipeline_name.lower()).strip("_")
        args.composite_id = (
            args.composite_id
            if len(requested) == 1
            else f"static_{slug}_weight_composite_v1"
        )
        outputs.append(
            _build_one(
                args=args,
                run_dir=run_dir,
                splits=splits,
                requested_universe=requested_universe,
                universe=universe,
                missing_symbols=missing_symbols,
                selected=selected,
                signs=signs,
                sharpes=sharpes,
                clusters=clusters,
                coef=coef,
                preloaded_panels=panels_for_pipeline,
                rolling_schedule=rolling_schedule,
                target_gross=args.target_gross,
                max_gross=float(args.max_gross),
                method=(
                    f"recomputed_{slug}"
                    f"{'_rolling' if args.rolling else ''}"
                    f"{'_netted_greedy' if args.netted_greedy else ''}"
                    f"{'_gross' + str(args.target_gross).replace('.', '') if args.target_gross is not None else ''}"
                    "_equal_weight_sign_aligned"
                ),
                source_note=(
                    "Selection is recomputed from each rebalance date's prior returns only; no future bars are used."
                    if args.rolling
                    else "Selection recomputed from flat backtest IS returns; OS only used for candidate availability, not tuning."
                ),
                extra_manifest={
                    **extra_manifest,
                    "min_is_sharpe": args.min_is_sharpe,
                    "family_dedup": bool(args.family_dedup),
                    "family_level": args.family_level if args.family_dedup else None,
                    "explicit_selection": bool(args.selected_alpha),
                },
            )
        )
    print(json.dumps({"ok": True, "selection_validation": validation, "outputs": outputs}, indent=2, default=str))
    return 0


def _build_one(
    *,
    args: argparse.Namespace,
    run_dir: Path,
    splits: dict[str, Any],
    requested_universe: list[str],
    universe: list[str],
    missing_symbols: list[str],
    selected: list[str],
    signs: dict[str, int],
    sharpes: dict[str, float | None],
    clusters: dict[str, int | None],
    coef: dict[str, float],
    preloaded_panels: dict[str, pd.DataFrame] | None,
    rolling_schedule: list[dict[str, Any]] | None,
    target_gross: float | None,
    max_gross: float,
    method: str,
    source_note: str,
    extra_manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:

    missing_alphas = [aid for aid in selected if not (run_dir / "alphas" / aid / "weights.parquet").exists()]
    if missing_alphas:
        raise FileNotFoundError(f"selected alphas missing weights.parquet: {missing_alphas}")

    comp_dir = run_dir / "composites" / args.composite_id
    if args.clean and comp_dir.exists():
        import shutil

        shutil.rmtree(comp_dir)
    comp_dir.mkdir(parents=True, exist_ok=True)

    if preloaded_panels is None:
        panels = {
            aid: _events_to_panel(_load_weight_events(run_dir / "alphas" / aid, universe), universe)
            for aid in selected
        }
    else:
        panels = {aid: preloaded_panels[aid] for aid in selected}
    if rolling_schedule is not None:
        weights_long, stats = _combine_rolling_weights(
            panels,
            rolling_schedule,
            universe,
            target_gross=target_gross,
            max_gross=max_gross,
        )
    else:
        weights_long, stats = _combine_weights(
            panels,
            coef,
            universe,
            target_gross=target_gross,
            max_gross=max_gross,
        )
    weights_path = comp_dir / "composite_input_weights.parquet"
    weights_long.to_parquet(weights_path, index=False)

    members = pd.DataFrame(
        [
            {
                "alpha_id": aid,
                "run": args.run_id,
                "coefficient": coef[aid],
                "flipped": signs[aid] < 0,
                "is_sharpe_signed": sharpes[aid],
                "cluster": clusters.get(aid),
            }
            for aid in selected
        ]
    )
    members.to_csv(comp_dir / "members.csv", index=False)

    rc = _run_backtest(
        output_dir=comp_dir,
        weights_path=weights_path,
        symbols=universe,
        splits=splits,
        alpha_id=args.composite_id,
        max_portfolio_weight=max_gross,
    )

    metrics_path = comp_dir / "metrics.json"
    metrics = _read_json(metrics_path)
    manifest = {
        "composite_id": args.composite_id,
        "method": method,
        "source_run": args.run_id,
        "selection_source": source_note,
        "n_members": len(selected),
        "corr_threshold": float(args.corr_threshold),
        "max_abs_daily": float(args.max_abs_daily),
        "is_window": splits["is"],
        "os_window": splits["os"],
        "universe_requested": len(requested_universe),
        "universe_used": len(universe),
        "missing_symbols": missing_symbols,
        "backtest_returncode": rc,
        "lookahead_guard": (
            "Members, signs, clusters, and coefficients are fit only on daily "
            "returns with timestamp <= IS end. OS returns are not read by the "
            "optimizer. The frozen coefficients are replayed through the "
            "standard PrecomputedWeightsStrategy backtest over IS+OS."
        ),
        **stats,
        **(extra_manifest or {}),
    }
    (comp_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str))
    metrics.update(
        {
            "composite_id": args.composite_id,
            "method": manifest["method"],
            "n_members": len(selected),
            "is_window": splits["is"],
            "os_window": splits["os"],
            **stats,
        }
    )
    metrics_path.write_text(json.dumps(metrics, indent=2, default=str))
    return {"composite_dir": str(comp_dir), **manifest}


if __name__ == "__main__":
    raise SystemExit(main())
