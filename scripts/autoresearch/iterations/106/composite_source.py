"""Ward-centroid cov-FREE composite with year-stability and drawdown discipline.

Method: Lopez de Prado 2016 correlation-distance d_ij = sqrt(0.5*(1 - rho_ij))
fed into Ward hierarchical clustering (scipy.cluster.hierarchy). After
sign-alignment (member_signs_ic) and pre-filters (per-calendar-year IS Sharpe
positivity for regime robustness, max IS drawdown < 25% for tail discipline,
correlation_dedup at rho=0.85), the submittable alpha pool is cut into K=6
clusters. Each cluster is represented by its single highest-IS-Sharpe alpha
(centroid). Members are equal-weighted with apply_signs and then L1-normalized;
coefficients are finally multiplied by GROSS_MULT=10 to escape the empirically
documented 1/sigma underweighting that crushed every prior cov-based attempt
to mean_row_l1 ~ 0.05. No matrix inversion anywhere -- cov-FREE composition.
"""
from __future__ import annotations

import argparse
import math

import numpy as np
import pandas as pd
import scipy.cluster.hierarchy as sch
import scipy.spatial.distance as ssd

from intraday.composites._runner import build_and_backtest
from intraday.composites._optim_helpers import (
    apply_signs,
    correlation_dedup,
    load_member_is_returns,
    member_signs_ic,
    normalize_coefficients,
    select_all_alphas,
    select_is_submittable,
)

COMPOSITE_ID = "auto_106_ward_centroid_k6_yearstable_dd25_dedup08"
COMPOSITION_NOTE = "ward_centroid_k6_yearstable_dd25_dedup085_covfree_grossx10"

RUN_ID = "run_2026_05_c"
K_CLUSTERS = 6
DD_MAX = 0.25
DEDUP_RHO = 0.85
GROSS_MULT = 10.0
MIN_DAYS_PER_YEAR = 20


def _is_sharpe_map(R: pd.DataFrame) -> dict[str, float]:
    mu = R.mean()
    sd = R.std().replace(0.0, np.nan)
    sh = (mu / sd) * math.sqrt(252.0)
    return sh.fillna(-1e9).to_dict()


def _year_stable_cols(R: pd.DataFrame) -> list[str]:
    try:
        idx = pd.to_datetime(R.index)
    except Exception:
        return list(R.columns)
    years = sorted(set(idx.year.tolist()))
    if len(years) < 2:
        return list(R.columns)
    R2 = R.copy()
    R2.index = idx
    keep: list[str] = []
    for col in R2.columns:
        s = R2[col].dropna()
        if s.empty:
            continue
        ok = True
        for y in years:
            seg = s[s.index.year == y]
            if len(seg) < MIN_DAYS_PER_YEAR:
                continue
            sd = float(seg.std())
            mu = float(seg.mean())
            if sd <= 0.0 or mu <= 0.0:
                ok = False
                break
        if ok:
            keep.append(col)
    return keep


def _max_drawdown(returns: pd.Series) -> float:
    r = returns.fillna(0.0).astype(float).values
    if r.size == 0:
        return 1.0
    eq = np.cumprod(1.0 + r)
    peak = np.maximum.accumulate(eq)
    dd = eq / np.where(peak > 0, peak, 1.0) - 1.0
    return float(-dd.min())


def _dd_filter_cols(R: pd.DataFrame, dd_max: float) -> list[str]:
    return [c for c in R.columns if _max_drawdown(R[c]) < dd_max]


def _load_pool(run_id: str) -> tuple[pd.DataFrame, dict[str, int]]:
    ids = select_is_submittable(run_id)
    if len(ids) < K_CLUSTERS * 3:
        ids = select_all_alphas(run_id)
    signs = member_signs_ic(run_id, ids)
    R = load_member_is_returns(run_id, ids, signs=signs)
    R = R.dropna(axis=1, how="all")
    return R, signs


def _ward_centroids(R: pd.DataFrame, k: int) -> list[str]:
    cols = list(R.columns)
    if len(cols) <= k:
        return cols
    corr = R.corr().fillna(0.0).values
    np.fill_diagonal(corr, 1.0)
    corr = np.clip(corr, -1.0, 1.0)
    dist = np.sqrt(np.clip(0.5 * (1.0 - corr), 0.0, 1.0))
    np.fill_diagonal(dist, 0.0)
    dist = 0.5 * (dist + dist.T)
    cond = ssd.squareform(dist, checks=False)
    Z = sch.linkage(cond, method="ward")
    labels = sch.fcluster(Z, t=k, criterion="maxclust")
    sharpe = _is_sharpe_map(R)
    chosen: list[str] = []
    for lab in sorted(set(labels.tolist())):
        members = [cols[i] for i in range(len(cols)) if labels[i] == lab]
        members.sort(key=lambda c: -sharpe.get(c, -1e9))
        if members:
            chosen.append(members[0])
    return chosen


def _select_core(R: pd.DataFrame) -> list[str]:
    # Year-stability filter
    ys = _year_stable_cols(R)
    if len(ys) >= K_CLUSTERS * 2:
        R = R[ys]
    # Drawdown discipline
    dd_ok = _dd_filter_cols(R, DD_MAX)
    if len(dd_ok) >= K_CLUSTERS * 2:
        R = R[dd_ok]
    # Correlation dedup -- keep by IS Sharpe
    sharpe = _is_sharpe_map(R)
    try:
        kept = correlation_dedup(R, threshold=DEDUP_RHO, keep_metric=sharpe)
    except Exception:
        kept = list(R.columns)
    if not kept:
        kept = list(R.columns)
    if len(kept) < K_CLUSTERS:
        ranked = sorted(R.columns, key=lambda c: -sharpe.get(c, -1e9))
        out = ranked[: max(K_CLUSTERS, 4)]
        return out if len(out) >= 2 else ranked[:2]
    R2 = R[kept]
    centroids = _ward_centroids(R2, K_CLUSTERS)
    if len(centroids) < 2:
        ranked = sorted(R2.columns, key=lambda c: -sharpe.get(c, -1e9))
        centroids = ranked[: max(K_CLUSTERS, 4)]
    return centroids


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    R, _ = _load_pool(RUN_ID)
    if R.shape[1] < 2:
        return list(R.columns)
    return _select_core(R)


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    ids = list(member_ids)
    if not ids:
        return {}
    signs = member_signs_ic(RUN_ID, ids)
    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    loaded = [c for c in ids if c in R.columns]
    if not loaded:
        return {a: 0.0 for a in ids}
    # Equal-weight |c|=1/K, then sign-align via apply_signs, then L1-normalize.
    base = {a: 1.0 for a in loaded}
    signed = apply_signs(base, {a: int(signs.get(a, 1)) for a in loaded})
    coef = normalize_coefficients(signed, "l1")
    # Escape the 1/sigma underweighting trap: scale up to populate gross budget.
    coef = {a: float(coef.get(a, 0.0)) * GROSS_MULT for a in loaded}
    out = {a: float(coef.get(a, 0.0)) for a in ids}
    return out


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