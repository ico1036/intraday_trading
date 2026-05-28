"""Ward hierarchical clustering on correlation distance (Murtagh & Legendre 2014;
Raffinot 2018 cluster-representative HRP variant): cov-free composition. Per-year
IS Sharpe stability + max-IS-DD<20% + correlation dedup at 0.85, then Ward into
K=6 clusters, top-IS-Sharpe representative per cluster, equal weight with sign
alignment and explicit gross-exposure scaling (sum|c|~3) to avoid the row-L1
starvation trap."""
from __future__ import annotations
import argparse
import math
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
    select_all_alphas,
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_073_ward_corrdist_k6_yearstable_dd20_dedup08"
COMPOSITION_NOTE = "ward_corrdist_k6_yearstable_dd20_dedup085_eq_grossx3"

RUN_ID = "run_2026_05_c"
K_CLUSTERS = 6
DD_MAX = 0.20
DD_MAX_RELAX = 0.35
DEDUP_RHO = 0.85
GROSS_SCALE = 3.0  # sum|c| target after L1-normalization


def _max_drawdown(returns: pd.Series) -> float:
    r = returns.fillna(0.0)
    eq = (1.0 + r).cumprod()
    peak = eq.cummax()
    dd = (eq / peak) - 1.0
    return float(-dd.min())


def _sharpe(r: pd.Series) -> float:
    r = r.dropna()
    if len(r) < 2:
        return 0.0
    s = r.std(ddof=0)
    if s <= 0 or not np.isfinite(s):
        return 0.0
    return float((r.mean() / s) * math.sqrt(252.0))


def _year_stable(returns: pd.Series) -> bool:
    r = returns.dropna()
    if len(r) < 60:
        return False
    if not isinstance(r.index, pd.DatetimeIndex):
        try:
            r = r.copy()
            r.index = pd.to_datetime(r.index)
        except Exception:
            return True
    years = r.index.year
    uniq = sorted(set(years.tolist()))
    if len(uniq) < 2:
        return True
    for y in uniq:
        seg = r[r.index.year == y]
        if len(seg) < 20:
            continue
        sd = seg.std(ddof=0)
        if sd <= 0 or not np.isfinite(sd):
            continue
        sh = (seg.mean() / (sd + 1e-12)) * math.sqrt(252.0)
        if sh <= 0:
            return False
    return True


def _candidate_pool() -> list[str]:
    try:
        ids = select_is_submittable(RUN_ID)
    except Exception:
        ids = []
    if not ids:
        try:
            ids = select_all_alphas(RUN_ID)
        except Exception:
            ids = []
    return list(ids)


def _filter_by_quality(R: pd.DataFrame, dd_max: float) -> tuple[list[str], dict[str, float]]:
    keep: list[str] = []
    metric: dict[str, float] = {}
    for col in R.columns:
        rcol = R[col].dropna()
        if len(rcol) < 60:
            continue
        if _max_drawdown(rcol) > dd_max:
            continue
        if not _year_stable(rcol):
            continue
        sh = _sharpe(rcol)
        if sh <= 0:
            continue
        keep.append(col)
        metric[col] = sh
    return keep, metric


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    candidates = _candidate_pool()
    if not candidates:
        # last-ditch fallback to alpha_index
        try:
            candidates = sorted(alpha_index["alpha_id"].astype(str).tolist())
        except Exception:
            candidates = []
    if len(candidates) < 2:
        return list(candidates)

    try:
        signs = member_signs_ic(RUN_ID, candidates)
    except Exception:
        signs = {a: 1 for a in candidates}
    signs = {a: int(signs.get(a, 1)) for a in candidates}

    try:
        R = load_member_is_returns(RUN_ID, candidates, signs=signs)
    except Exception:
        R = pd.DataFrame()
    if R is None or R.empty:
        return list(candidates[: max(2, K_CLUSTERS)])
    R = R.dropna(axis=1, how="all")
    if R.shape[1] < 2:
        return list(R.columns)
    if R.shape[1] <= K_CLUSTERS:
        return list(R.columns)

    keep, metric = _filter_by_quality(R, DD_MAX)
    if len(keep) < K_CLUSTERS + 1:
        keep, metric = _filter_by_quality(R, DD_MAX_RELAX)
    if len(keep) < K_CLUSTERS + 1:
        # final fallback: drop year-stability + DD, just sharpe>0
        keep, metric = [], {}
        for col in R.columns:
            rcol = R[col].dropna()
            if len(rcol) < 60:
                continue
            sh = _sharpe(rcol)
            if sh <= 0:
                continue
            keep.append(col)
            metric[col] = sh

    if len(keep) < 2:
        order = sorted(R.columns, key=lambda c: _sharpe(R[c]), reverse=True)
        return list(order[: max(2, K_CLUSTERS)])

    R_keep = R[keep].dropna(how="all")
    try:
        deduped = correlation_dedup(R_keep, threshold=DEDUP_RHO, keep_metric=metric)
    except Exception:
        deduped = keep
    if not deduped or len(deduped) < 2:
        deduped = keep

    if len(deduped) <= K_CLUSTERS:
        return list(deduped)

    R_dd = R[deduped].dropna(how="all").fillna(0.0)
    if R_dd.shape[1] <= K_CLUSTERS:
        return list(R_dd.columns)

    # Ward hierarchical clustering on correlation distance
    try:
        corr = R_dd.corr().fillna(0.0).clip(-1.0, 1.0).values.astype(float)
        np.fill_diagonal(corr, 1.0)
        dist_mat = np.sqrt(np.maximum(0.5 * (1.0 - corr), 0.0))
        dist_mat = 0.5 * (dist_mat + dist_mat.T)
        np.fill_diagonal(dist_mat, 0.0)
        condensed = ssd.squareform(dist_mat, checks=False)
        Z = sch.linkage(condensed, method="ward")
        labels = sch.fcluster(Z, t=K_CLUSTERS, criterion="maxclust")
    except Exception:
        # fallback: pure top-K by IS Sharpe
        order = sorted(R_dd.columns, key=lambda c: metric.get(c, _sharpe(R_dd[c])), reverse=True)
        return list(order[:K_CLUSTERS])

    cols = list(R_dd.columns)
    reps: list[str] = []
    for k in sorted(set(int(x) for x in labels)):
        members = [cols[i] for i, lab in enumerate(labels) if int(lab) == k]
        if not members:
            continue
        rep = max(members, key=lambda c: metric.get(c, _sharpe(R_dd[c])))
        reps.append(rep)

    if len(reps) < 2:
        order = sorted(R_dd.columns, key=lambda c: metric.get(c, _sharpe(R_dd[c])), reverse=True)
        return list(order[: max(2, K_CLUSTERS)])
    return reps


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    if not member_ids:
        return {}
    try:
        raw_signs = member_signs_ic(RUN_ID, member_ids)
    except Exception:
        raw_signs = {}
    signs = {a: int(raw_signs.get(a, 1)) for a in member_ids}

    base = {a: 1.0 for a in member_ids}
    try:
        aligned = apply_signs(base, signs)
    except Exception:
        aligned = {a: float(signs.get(a, 1)) for a in member_ids}
    # ensure every member present
    for a in member_ids:
        if a not in aligned or not np.isfinite(aligned[a]):
            aligned[a] = float(signs.get(a, 1))

    try:
        coef = normalize_coefficients(aligned, "l1")
    except Exception:
        denom = sum(abs(v) for v in aligned.values()) or 1.0
        coef = {k: float(v) / denom for k, v in aligned.items()}

    # Push sum|c| from 1 up to GROSS_SCALE so combined panel actually
    # exercises the row-L1 budget (avoids the row-L1<0.1 starvation mode).
    coef = {k: float(v) * GROSS_SCALE for k, v in coef.items()}
    # Safety: ensure all member ids present
    for a in member_ids:
        if a not in coef:
            coef[a] = 0.0
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