"""Cluster-centroid composite: Ward-linkage hierarchical clustering on
correlation distance d=sqrt(0.5*(1-rho)) (Raffinot 2017), pick the
top-IS-Sharpe alpha per cluster as representative, then equal native-
leverage weighting (c_a = +/- 1.0) instead of inverse-variance — this
deliberately avoids the Sigma^{-1} . mu 1/sigma collapse that pinned
prior cov-based attempts to mean row_l1 ~ 0.05. Pre-filters: per-year
IS Sharpe >= 0 in >= 2 years, max IS drawdown <= 25%, corr dedup rho=0.85."""
from __future__ import annotations
import argparse
import numpy as np
import pandas as pd
import scipy.cluster.hierarchy as sch
import scipy.spatial.distance as ssd

from intraday.composites._runner import build_and_backtest
from intraday.composites._optim_helpers import (
    correlation_dedup,
    member_signs_ic,
    apply_signs,
    select_is_submittable,
    load_member_is_returns,
)

COMPOSITE_ID = "auto_105_cluster_centroid_ward_k6_yearstable_dd25"
COMPOSITION_NOTE = "cluster_centroid_ward_k6_yearstable_dd25_unitcoef"

RUN_ID = "run_2026_05_c"
N_CLUSTERS = 6
DEDUP_RHO = 0.85
MAX_DD_THRESHOLD = 0.25
MIN_YEARS_POSITIVE = 2


def _safe_sharpe_map(R: pd.DataFrame) -> dict[str, float]:
    out: dict[str, float] = {}
    for col in R.columns:
        s = R[col].dropna()
        if len(s) >= 20 and float(s.std()) > 0:
            out[col] = float(s.mean() / s.std() * np.sqrt(252.0))
        else:
            out[col] = 0.0
    return out


def _max_drawdown(r: pd.Series) -> float:
    r = r.fillna(0.0)
    if len(r) == 0:
        return 0.0
    cum = (1.0 + r).cumprod()
    peak = cum.cummax()
    dd = (cum / peak) - 1.0
    val = dd.min()
    return float(-val) if pd.notna(val) else 0.0


def _year_stable_cols(R: pd.DataFrame, min_pos_years: int) -> list[str]:
    idx = R.index
    if not isinstance(idx, pd.DatetimeIndex):
        try:
            idx = pd.to_datetime(idx)
        except Exception:
            return list(R.columns)
    years = sorted(set(idx.year))
    if len(years) < 2:
        return list(R.columns)
    keep: list[str] = []
    for col in R.columns:
        positive = 0
        for y in years:
            mask = idx.year == y
            sub = R[col][mask].dropna()
            if len(sub) < 15 or float(sub.std()) <= 0:
                continue
            if float(sub.mean()) >= 0.0:
                positive += 1
        if positive >= min_pos_years:
            keep.append(col)
    return keep


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    candidates = list(select_is_submittable(RUN_ID))
    if len(candidates) < 4:
        try:
            candidates = list(alpha_index["alpha_id"].astype(str).unique())
        except Exception:
            candidates = []
    if len(candidates) < 2:
        raise RuntimeError("no candidate alphas available")

    signs = member_signs_ic(RUN_ID, candidates)
    R = load_member_is_returns(RUN_ID, candidates, signs=signs)
    if R.shape[1] < 4:
        cols = list(R.columns)
        return cols[: max(2, len(cols))]

    sh_map = _safe_sharpe_map(R)

    stable = _year_stable_cols(R, MIN_YEARS_POSITIVE)
    if len(stable) >= 8:
        R = R[stable]

    dd_ok = [c for c in R.columns if _max_drawdown(R[c]) <= MAX_DD_THRESHOLD]
    if len(dd_ok) >= 8:
        R = R[dd_ok]

    sh_map = {k: v for k, v in sh_map.items() if k in R.columns}

    try:
        kept = correlation_dedup(R, threshold=DEDUP_RHO, keep_metric=sh_map)
        if len(kept) >= 4:
            R = R[kept]
    except Exception:
        pass

    sh_map = {k: v for k, v in sh_map.items() if k in R.columns}

    k = min(N_CLUSTERS, max(2, R.shape[1] // 2))
    cols = list(R.columns)

    if len(cols) <= k:
        ranked = sorted(cols, key=lambda a: -sh_map.get(a, 0.0))
        return ranked[: max(2, min(k, len(ranked)))]

    corr_df = R.corr().fillna(0.0)
    corr = np.clip(corr_df.values, -0.999, 0.999)
    np.fill_diagonal(corr, 1.0)
    dist = np.sqrt(np.clip(0.5 * (1.0 - corr), 0.0, 1.0))
    dist = 0.5 * (dist + dist.T)
    np.fill_diagonal(dist, 0.0)

    try:
        cond = ssd.squareform(dist, checks=False)
        Z = sch.linkage(cond, method="ward")
        labels = sch.fcluster(Z, t=k, criterion="maxclust")
    except Exception:
        ranked = sorted(cols, key=lambda a: -sh_map.get(a, 0.0))
        return ranked[: max(2, k)]

    reps: list[str] = []
    for cid in sorted(set(labels)):
        in_cluster = [cols[i] for i, lab in enumerate(labels) if lab == cid]
        if not in_cluster:
            continue
        best = max(in_cluster, key=lambda a: sh_map.get(a, 0.0))
        reps.append(best)

    if len(reps) < 2:
        ranked = sorted(cols, key=lambda a: -sh_map.get(a, 0.0))
        reps = ranked[: max(2, k)]

    seen: set[str] = set()
    out: list[str] = []
    for a in reps:
        if a not in seen:
            seen.add(a)
            out.append(a)
    return out


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    signs = member_signs_ic(RUN_ID, member_ids)
    coef: dict[str, float] = {a: 1.0 for a in member_ids}
    coef = apply_signs(coef, signs)
    return coef


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--no-os", action="store_true")
    args = parser.parse_args()
    build_and_backtest(
        composite_id=COMPOSITE_ID,
        run_id=args.run_id,
        select_members=select_members,
        member_weights=member_weights,
        composition_note=COMPOSITION_NOTE,
        include_os=not args.no_os,
    )


if __name__ == "__main__":
    main()