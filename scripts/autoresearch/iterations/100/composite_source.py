"""Ward-linkage cluster-centroid composite (cov-free) on IS-return correlation distance with year-stability + drawdown discipline and IC sign alignment — Lopez de Prado (2016) HRP clustering, Raffinot (2018) HERC selection spirit, but cov-free centroid extraction to avoid 1/sigma dilution."""
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
    select_all_alphas,
    member_is_sharpe,
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_100_ward_cluster_centroid_eqw_yearstable_dd2"
COMPOSITION_NOTE = "ward_cluster_centroid_eqw_yearstable_dd25_k6_gross075"

RUN_ID = "run_2026_05_c"
N_CLUSTERS = 6
DD_THRESHOLD = 0.25
CORR_DEDUP = 0.88
TARGET_GROSS = 0.75


def _max_drawdown(returns: pd.Series) -> float:
    rets = returns.dropna()
    if rets.empty:
        return 1.0
    eq = (1.0 + rets).cumprod()
    peak = eq.cummax()
    dd = (eq / peak) - 1.0
    return float(-dd.min()) if dd.size else 1.0


def _year_stable(returns: pd.Series) -> bool:
    rets = returns.dropna()
    if rets.empty or rets.size < 30:
        return False
    if not isinstance(rets.index, pd.DatetimeIndex):
        return True
    for _, sub in rets.groupby(rets.index.year):
        if sub.size < 5:
            continue
        std = float(sub.std())
        if std == 0.0 or not np.isfinite(std):
            continue
        sh = float(sub.mean()) / std
        if sh <= 0.0:
            return False
    return True


def _ward_centroids(R: pd.DataFrame, keep_metric: dict, k: int) -> list:
    R_d = R.dropna(how="all").fillna(0.0)
    if R_d.shape[1] <= k:
        return list(R_d.columns)
    corr = R_d.corr().fillna(0.0).values
    np.fill_diagonal(corr, 1.0)
    dist = np.sqrt(np.clip(0.5 * (1.0 - corr), 0.0, 1.0))
    np.fill_diagonal(dist, 0.0)
    dist = 0.5 * (dist + dist.T)
    condensed = ssd.squareform(dist, checks=False)
    Z = sch.linkage(condensed, method="ward")
    labels = sch.fcluster(Z, t=k, criterion="maxclust")
    cols = list(R_d.columns)
    centroids: list = []
    for cluster_id in np.unique(labels):
        members_in = [cols[i] for i, lab in enumerate(labels) if lab == cluster_id]
        best = max(members_in, key=lambda c: float(keep_metric.get(c, -1e9)))
        centroids.append(best)
    return centroids


def select_members(alpha_index: pd.DataFrame) -> list:
    ids = select_is_submittable(RUN_ID)
    if len(ids) < 6:
        ids = select_all_alphas(RUN_ID)
    if len(ids) < 2:
        return list(ids)

    signs = member_signs_ic(RUN_ID, ids, dead_band=0.005)
    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    if R.shape[1] < 4:
        return list(R.columns)

    is_sh = member_is_sharpe(RUN_ID, list(R.columns))

    kept = []
    for col in R.columns:
        rets = R[col].dropna()
        if rets.empty:
            continue
        if _max_drawdown(rets) > DD_THRESHOLD:
            continue
        if not _year_stable(rets):
            continue
        kept.append(col)

    if len(kept) < 6:
        kept = [c for c in R.columns if _year_stable(R[c])]
    if len(kept) < 6:
        kept = sorted(
            R.columns,
            key=lambda c: float(is_sh.get(c, -1.0)),
            reverse=True,
        )[:30]
    if len(kept) < 2:
        kept = list(R.columns[: max(2, min(8, R.shape[1]))])

    R_kept = R[kept]
    keep_metric = {c: float(is_sh.get(c, 0.0)) for c in kept}
    deduped = correlation_dedup(R_kept, CORR_DEDUP, keep_metric=keep_metric)
    if len(deduped) < 4:
        deduped = kept

    k = max(2, min(N_CLUSTERS, len(deduped)))
    centroids = _ward_centroids(R[deduped], keep_metric, k)
    if len(centroids) < 2:
        centroids = sorted(
            deduped, key=lambda c: keep_metric.get(c, 0.0), reverse=True
        )[: max(2, k)]
    return centroids


def member_weights(member_ids: list, alpha_index: pd.DataFrame) -> dict:
    if not member_ids:
        return {}
    signs = member_signs_ic(RUN_ID, member_ids, dead_band=0.005)
    coef = {a: 1.0 for a in member_ids}
    coef = apply_signs(coef, signs)
    coef = normalize_coefficients(coef, "l1")

    R = load_member_is_returns(RUN_ID, member_ids, signs=signs)
    if not R.empty and R.shape[1] > 0:
        sigma = R.std().fillna(0.0).to_dict()
        est = sum(
            abs(float(coef.get(k, 0.0))) * float(sigma.get(k, 0.0))
            for k in member_ids
        )
        if est > 1e-9:
            scale = TARGET_GROSS / max(est, 1e-9)
            coef = {k: float(v) * scale for k, v in coef.items()}
        else:
            coef = {k: float(v) * 12.0 for k, v in coef.items()}
    else:
        coef = {k: float(v) * 12.0 for k, v in coef.items()}
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