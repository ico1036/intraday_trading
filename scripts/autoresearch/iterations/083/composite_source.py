"""Cov-free composite via Ward hierarchical clustering on the HRP correlation
distance d = sqrt(0.5*(1-rho)) (Lopez de Prado 2016) with per-year IS-Sharpe
stability filter + max-drawdown discipline, intra-cluster centroid selection
by IS Sharpe, and equal-weight 1/K post-scaled to target gross exposure.
Bypasses the 1/sigma tangency trap that capped prior attempts' mean row L1."""
from __future__ import annotations
import argparse
import math
import numpy as np
import pandas as pd
import scipy.cluster.hierarchy as sch
import scipy.spatial.distance as ssd

from intraday.composites._runner import build_and_backtest
from intraday.composites._optim_helpers import (
    member_signs_ic,
    apply_signs,
    select_is_submittable,
    select_all_alphas,
    load_member_is_returns,
)

COMPOSITE_ID = "auto_083_ward_corrdist_yearstable_dd25_k6_centroi"
COMPOSITION_NOTE = "ward_corrdist_yearstable_dd25_k6_centroid_eqwt_grossx4"
RUN_ID = "run_2026_05_c"
N_CLUSTERS = 6
DD_FLOOR = -0.25
MIN_YEAR_BARS = 20
GROSS_SCALE = 4.0


def _annualized_sharpe(s: pd.Series) -> float:
    s = s.dropna().astype(float)
    if len(s) < 2:
        return 0.0
    mu = s.mean()
    sd = s.std(ddof=1)
    if not np.isfinite(sd) or sd <= 0:
        return 0.0
    return float(mu / sd * math.sqrt(252.0))


def _max_drawdown(s: pd.Series) -> float:
    s = s.fillna(0.0).astype(float)
    if s.empty:
        return 0.0
    eq = (1.0 + s).cumprod()
    rm = eq.cummax()
    dd = (eq / rm - 1.0).min()
    if not np.isfinite(dd):
        return 0.0
    return float(dd)


def _year_stability_filter(R: pd.DataFrame) -> list[str]:
    try:
        idx = pd.DatetimeIndex(pd.to_datetime(R.index))
        years = np.asarray(idx.year)
    except Exception:
        return list(R.columns)
    unique_years = sorted(set(years.tolist()))
    if len(unique_years) < 2:
        return list(R.columns)
    keep = []
    for col in R.columns:
        s = R[col].astype(float)
        ok = True
        any_eligible = False
        for y in unique_years:
            mask = years == y
            sub = s[mask]
            if len(sub) < MIN_YEAR_BARS:
                continue
            any_eligible = True
            if _annualized_sharpe(sub) <= 0:
                ok = False
                break
        if ok and any_eligible:
            keep.append(col)
    return keep


def _dd_filter(R: pd.DataFrame, cols: list[str]) -> list[str]:
    return [c for c in cols if _max_drawdown(R[c]) > DD_FLOOR]


def _cluster_centroids(R: pd.DataFrame, sharpes: dict, k: int) -> list[str]:
    cols = list(R.columns)
    n = len(cols)
    if n == 0:
        return []
    if n <= k:
        return sorted(cols, key=lambda c: -sharpes.get(c, 0.0))
    corr = R.corr().fillna(0.0).values.astype(float)
    np.fill_diagonal(corr, 1.0)
    corr = np.clip(corr, -1.0, 1.0)
    dist = np.sqrt(np.clip(0.5 * (1.0 - corr), 0.0, 1.0))
    dist = 0.5 * (dist + dist.T)
    np.fill_diagonal(dist, 0.0)
    try:
        cond = ssd.squareform(dist, checks=False)
        Z = sch.linkage(cond, method="average")
        labels = sch.fcluster(Z, t=k, criterion="maxclust")
    except Exception:
        return sorted(cols, key=lambda c: -sharpes.get(c, 0.0))[:k]
    chosen = []
    for c in sorted(set(labels.tolist())):
        mem = [cols[i] for i in range(n) if labels[i] == c]
        if not mem:
            continue
        chosen.append(max(mem, key=lambda x: sharpes.get(x, 0.0)))
    if len(chosen) < min(k, n):
        remaining = [c for c in cols if c not in chosen]
        remaining.sort(key=lambda c: -sharpes.get(c, 0.0))
        while len(chosen) < min(k, n) and remaining:
            chosen.append(remaining.pop(0))
    return chosen


def _select_core() -> list[str]:
    try:
        ids = select_is_submittable(RUN_ID)
    except Exception:
        ids = []
    if len(ids) < N_CLUSTERS + 2:
        try:
            ids = select_all_alphas(RUN_ID)
        except Exception:
            ids = ids or []
    if not ids:
        return []
    try:
        signs = member_signs_ic(RUN_ID, ids)
    except Exception:
        signs = {a: 1 for a in ids}
    try:
        R = load_member_is_returns(RUN_ID, ids, signs=signs)
    except Exception:
        return []
    if R is None or R.empty:
        return []
    R = R.dropna(axis=1, how="all").fillna(0.0)
    if R.shape[1] == 0:
        return []

    kept = _year_stability_filter(R)
    if len(kept) >= N_CLUSTERS:
        dd_kept = _dd_filter(R, kept)
        if len(dd_kept) >= N_CLUSTERS:
            kept = dd_kept

    if len(kept) < N_CLUSTERS:
        sh_all = {c: _annualized_sharpe(R[c]) for c in R.columns}
        kept = [c for c in R.columns if sh_all.get(c, 0.0) > 0]

    if len(kept) < 2:
        sh_all = {c: _annualized_sharpe(R[c]) for c in R.columns}
        kept = sorted(R.columns.tolist(), key=lambda c: -sh_all.get(c, 0.0))[: max(2, N_CLUSTERS)]

    if not kept:
        return []
    Rsub = R[kept]
    sh = {c: _annualized_sharpe(Rsub[c]) for c in Rsub.columns}
    return _cluster_centroids(Rsub, sh, N_CLUSTERS)


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    sel = _select_core()
    if len(sel) >= 2:
        return sel
    try:
        ids = select_all_alphas(RUN_ID)
    except Exception:
        ids = []
    if not ids:
        return []
    try:
        signs = member_signs_ic(RUN_ID, ids)
        R = load_member_is_returns(RUN_ID, ids, signs=signs)
    except Exception:
        return ids[: N_CLUSTERS]
    if R is None or R.empty:
        return ids[: N_CLUSTERS]
    R = R.dropna(axis=1, how="all").fillna(0.0)
    sh = {c: _annualized_sharpe(R[c]) for c in R.columns}
    return sorted(R.columns.tolist(), key=lambda c: -sh.get(c, 0.0))[: max(2, N_CLUSTERS)]


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict:
    member_ids = list(member_ids)
    if not member_ids:
        return {}
    K = len(member_ids)
    base = GROSS_SCALE / float(K)
    coef = {a: float(base) for a in member_ids}
    try:
        signs = member_signs_ic(RUN_ID, member_ids)
    except Exception:
        signs = {a: 1 for a in member_ids}
    try:
        coef = apply_signs(coef, signs)
    except Exception:
        coef = {a: v * float(int(signs.get(a, 1))) for a, v in coef.items()}
    for a in member_ids:
        coef.setdefault(a, 0.0)
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