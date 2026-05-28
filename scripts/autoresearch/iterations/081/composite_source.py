"""HERC-style cluster-centroid composite (Raffinot 2018; Lopez de Prado HRP 2016).

Cov-FREE composition. Correlation distance d_ij = sqrt(0.5*(1 - rho_ij)) -> Ward
linkage -> K=6 flat clusters -> pick highest-IS-Sharpe representative per cluster
-> equal weight + IC-sign alignment -> L1 normalize -> scale x8 so the runner's
row-L1 clamp lands gross in a useful range. Regime discipline: per-year IS
Sharpe positivity + max-DD < 25% gates applied before clustering.
"""
from __future__ import annotations
import argparse
import numpy as np
import pandas as pd
import scipy.cluster.hierarchy as sch
import scipy.spatial.distance as ssd

from intraday.composites._runner import build_and_backtest
from intraday.composites._optim_helpers import (
    select_is_submittable,
    member_signs_ic,
    apply_signs,
    load_member_is_returns,
    normalize_coefficients,
    correlation_dedup,
)

COMPOSITE_ID = "auto_081_herc_clust_centroid_yearstable_dd25_k6_e"
COMPOSITION_NOTE = "herc_clust_centroid_yearstable_dd25_k6_eqw_x8"

RUN_ID = "run_2026_05_c"
N_CLUSTERS = 6
DD_MAX = 0.25
DEDUP_RHO = 0.92
SCALE = 8.0
ANN = float(np.sqrt(252.0))


def _ann_sharpe(r: pd.Series) -> float:
    r = r.dropna()
    if len(r) < 2:
        return 0.0
    s = r.std(ddof=1)
    if not np.isfinite(s) or s <= 1e-12:
        return 0.0
    return float(r.mean() / s * ANN)


def _max_dd(r: pd.Series) -> float:
    r = r.dropna()
    if r.empty:
        return 1.0
    eq = (1.0 + r).cumprod()
    peak = eq.cummax()
    dd = 1.0 - eq / peak
    return float(dd.max())


def _year_positive(r: pd.Series) -> bool:
    r = r.dropna()
    if len(r) < 60:
        return False
    if not isinstance(r.index, pd.DatetimeIndex):
        return False
    for _, g in r.groupby(r.index.year):
        if len(g) < 20:
            continue
        if _ann_sharpe(g) <= 0.0:
            return False
    return True


def _filter(R: pd.DataFrame, sh_floor: float, dd_cap: float, require_year: bool):
    keep: list[str] = []
    scores: dict[str, float] = {}
    for c in R.columns:
        sh = _ann_sharpe(R[c])
        if sh <= sh_floor:
            continue
        if _max_dd(R[c]) > dd_cap:
            continue
        if require_year and not _year_positive(R[c]):
            continue
        keep.append(c)
        scores[c] = sh
    return keep, scores


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    ids = select_is_submittable(RUN_ID)
    if not ids:
        return []
    signs = member_signs_ic(RUN_ID, ids)
    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    R = R.dropna(axis=1, how="all")
    if R.shape[1] < 2:
        return list(R.columns)

    keep, scores = _filter(R, sh_floor=0.30, dd_cap=DD_MAX, require_year=True)
    if len(keep) < N_CLUSTERS:
        keep, scores = _filter(R, sh_floor=0.20, dd_cap=0.35, require_year=False)
    if len(keep) < 2:
        all_scores = {c: _ann_sharpe(R[c]) for c in R.columns}
        keep = sorted(all_scores, key=lambda c: all_scores[c], reverse=True)[: max(N_CLUSTERS, 4)]
        scores = {c: all_scores[c] for c in keep}
    if len(keep) < 2:
        return keep

    Rk = R[keep]
    deduped = correlation_dedup(Rk, threshold=DEDUP_RHO, keep_metric=scores)
    if not deduped or len(deduped) < 2:
        deduped = keep

    if len(deduped) <= N_CLUSTERS:
        return list(deduped)

    Rd = R[deduped].dropna()
    if Rd.shape[0] < 30 or Rd.shape[1] < 2:
        return sorted(deduped, key=lambda c: scores.get(c, 0.0), reverse=True)[:N_CLUSTERS]

    corr = Rd.corr().fillna(0.0).clip(-1.0, 1.0).values.astype(float)
    np.fill_diagonal(corr, 1.0)
    dist = np.sqrt(np.clip(0.5 * (1.0 - corr), 0.0, 1.0))
    dist = (dist + dist.T) / 2.0
    np.fill_diagonal(dist, 0.0)
    try:
        cond = ssd.squareform(dist, checks=False)
        Z = sch.linkage(cond, method="ward")
        labels = sch.fcluster(Z, t=N_CLUSTERS, criterion="maxclust")
    except Exception:
        return sorted(deduped, key=lambda c: scores.get(c, 0.0), reverse=True)[:N_CLUSTERS]

    cols = list(Rd.columns)
    reps: list[str] = []
    for k in range(1, int(labels.max()) + 1):
        members = [cols[i] for i in range(len(cols)) if labels[i] == k]
        if not members:
            continue
        rep = max(members, key=lambda c: scores.get(c, 0.0))
        reps.append(rep)

    if len(reps) < 2:
        reps = sorted(deduped, key=lambda c: scores.get(c, 0.0), reverse=True)[:N_CLUSTERS]
    return reps


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    if not member_ids:
        return {}
    signs = member_signs_ic(RUN_ID, member_ids)
    coef = {a: 1.0 for a in member_ids}
    coef = apply_signs(coef, signs)
    coef = normalize_coefficients(coef, "l1")
    return {k: float(v) * SCALE for k, v in coef.items()}


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