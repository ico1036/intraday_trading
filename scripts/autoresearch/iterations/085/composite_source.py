"""Ward hierarchical clustering on sqrt(0.5*(1-corr)) distance with per-cluster IS-Sharpe centroid, year-stability + DD discipline, no covariance inversion (Lopez de Prado quasi-diag metric, Raffinot 2018 HERC tradition) — pure cov-free composition with native-gross rescaling to escape the 1/sigma-weighting trap."""
from __future__ import annotations
import argparse
import numpy as np
import pandas as pd
import scipy.cluster.hierarchy as sch
import scipy.spatial.distance as ssd

from intraday.composites._runner import build_and_backtest
from intraday.composites._optim_helpers import (
    select_is_submittable,
    select_all_alphas,
    member_signs_ic,
    apply_signs,
    load_member_is_returns,
    normalize_coefficients,
    member_is_sharpe,
    correlation_dedup,
)

COMPOSITE_ID = "auto_085_ward_centroid_yearstable_dd20_k6_covfree"
COMPOSITION_NOTE = "ward_centroid_yearstable_dd20_k6_covfree_gross_x8"

RUN_ID = "run_2026_05_c"
N_CLUSTERS = 6
DD_THRESHOLD = 0.20
MIN_IS_SHARPE = 0.40
DEDUP_RHO = 0.92
GROSS_MULT = 8.0


def _year_stable(returns: pd.Series) -> bool:
    s = returns.dropna()
    if len(s) < 60:
        return False
    try:
        years = s.index.year
    except AttributeError:
        try:
            years = pd.to_datetime(s.index).year
        except Exception:
            return False
    by_year = s.groupby(years)
    valid = 0
    for _, grp in by_year:
        if len(grp) < 20:
            continue
        sd = float(grp.std())
        if sd <= 0:
            continue
        sh = float(grp.mean()) / (sd + 1e-12) * np.sqrt(252.0)
        if sh <= 0.0:
            return False
        valid += 1
    return valid >= 2


def _max_drawdown(returns: pd.Series) -> float:
    r = returns.fillna(0.0)
    eq = (1.0 + r).cumprod()
    peak = eq.cummax()
    dd = (eq / peak - 1.0).min()
    return float(abs(dd)) if np.isfinite(dd) else 1.0


def _filter_stability(R: pd.DataFrame) -> list[str]:
    keep: list[str] = []
    for col in R.columns:
        r = R[col].dropna()
        if r.empty:
            continue
        try:
            if not _year_stable(r):
                continue
            if _max_drawdown(r) > DD_THRESHOLD:
                continue
        except Exception:
            continue
        keep.append(col)
    return keep


def _topk_fallback(sh_map: dict, k: int) -> list[str]:
    ranked = sorted(sh_map.items(), key=lambda kv: kv[1], reverse=True)
    return [a for a, _ in ranked[:k]]


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    ids = select_is_submittable(RUN_ID)
    if ids is None or len(ids) < N_CLUSTERS:
        ids = select_all_alphas(RUN_ID)

    signs = member_signs_ic(RUN_ID, ids)
    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    if R is None or R.shape[1] < N_CLUSTERS:
        sh_map = member_is_sharpe(RUN_ID, ids)
        return _topk_fallback(sh_map, N_CLUSTERS)

    sh_all = member_is_sharpe(RUN_ID, list(R.columns))
    cols = [c for c in R.columns if sh_all.get(c, -np.inf) >= MIN_IS_SHARPE]
    if len(cols) < N_CLUSTERS:
        return _topk_fallback(sh_all, N_CLUSTERS)
    R = R[cols]

    stable = _filter_stability(R)
    if len(stable) >= N_CLUSTERS:
        R = R[stable]

    # Light dedup on near-clones to avoid one cluster swallowing all variants
    try:
        kept = correlation_dedup(R, DEDUP_RHO, keep_metric=sh_all)
        if kept and len(kept) >= N_CLUSTERS:
            R = R[[c for c in kept if c in R.columns]]
    except Exception:
        pass

    if R.shape[1] < N_CLUSTERS:
        return _topk_fallback(sh_all, N_CLUSTERS)

    corr = R.corr().fillna(0.0).clip(-1.0, 1.0)
    dist = np.sqrt(np.clip(0.5 * (1.0 - corr.values), 0.0, 1.0))
    np.fill_diagonal(dist, 0.0)
    # symmetrize numerically
    dist = 0.5 * (dist + dist.T)
    try:
        condensed = ssd.squareform(dist, checks=False)
        Z = sch.linkage(condensed, method="ward")
        labels = sch.fcluster(Z, t=N_CLUSTERS, criterion="maxclust")
    except Exception:
        return _topk_fallback(sh_all, N_CLUSTERS)

    chosen: list[str] = []
    for c in sorted(set(labels.tolist())):
        members = [R.columns[i] for i in range(len(labels)) if labels[i] == c]
        if not members:
            continue
        members.sort(key=lambda a: sh_all.get(a, -np.inf), reverse=True)
        chosen.append(members[0])

    if len(chosen) < 2:
        return _topk_fallback(sh_all, N_CLUSTERS)
    return chosen


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    signs = member_signs_ic(RUN_ID, member_ids)
    coef = {a: 1.0 for a in member_ids}
    coef = apply_signs(coef, signs)
    coef = normalize_coefficients(coef, "l1")
    # Cov-free composers preserve native member leverage; the row-L1 runner clamp
    # is far from saturated when |c_i| ~ 1/K. Push aggregate |c| up so mean row L1
    # lands in [0.5, 0.9] instead of the 0.05 dead zone seen in cov-based attempts.
    coef = {k: float(v) * GROSS_MULT for k, v in coef.items()}
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