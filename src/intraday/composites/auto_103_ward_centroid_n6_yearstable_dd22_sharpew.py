"""Ward-linkage cluster-centroid composite (Lopez de Prado NCO-flavored, cov-free):
year-stable + DD-disciplined SUBMITTABLE pool → corr-dedup → Ward cluster (K=6) on
sqrt(0.5(1-rho)) distance → top-IS-Sharpe rep per cluster → IS-Sharpe-proportional
weights with IC-sign alignment, post-scaled to push mean row L1 toward the budget."""
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

COMPOSITE_ID = "auto_103_ward_centroid_n6_yearstable_dd22_sharpew"
COMPOSITION_NOTE = "ward_centroid_n6_yearstable_dd22_sharpewt_icsign_gross2x"

RUN_ID = "run_2026_05_c"
N_CLUSTERS = 6
DD_THRESHOLD = 0.22
DEDUP_RHO = 0.88
GROSS_SCALE = 2.0  # post-L1 multiplier to escape the inverse-vol contraction trap


def _annualized_sharpe(r: pd.Series) -> float:
    s = r.dropna()
    if len(s) < 5:
        return 0.0
    mu = float(s.mean())
    sd = float(s.std())
    if sd <= 0 or not np.isfinite(sd):
        return 0.0
    return mu / sd * math.sqrt(252.0)


def _max_drawdown(r: pd.Series) -> float:
    eq = (1.0 + r.fillna(0.0)).cumprod()
    peak = eq.cummax()
    dd = (eq / peak - 1.0).min()
    if not np.isfinite(dd):
        return 1.0
    return float(abs(dd))


def _per_year_stable(R: pd.DataFrame, min_years: int = 2) -> list[str]:
    if not isinstance(R.index, pd.DatetimeIndex):
        try:
            R.index = pd.to_datetime(R.index)
        except Exception:
            return list(R.columns)
    years = R.index.year
    unique_years = sorted(set(years.tolist()))
    if len(unique_years) < min_years:
        return list(R.columns)
    kept: list[str] = []
    for col in R.columns:
        all_pos = True
        for y in unique_years:
            sub = R[col][years == y]
            if len(sub) < 5:
                continue
            if _annualized_sharpe(sub) <= 0.0:
                all_pos = False
                break
        if all_pos:
            kept.append(col)
    return kept


def _fallback_topn(alpha_index: pd.DataFrame, n: int) -> list[str]:
    if "is_sharpe" not in alpha_index.columns:
        return alpha_index["alpha_id"].head(n).tolist()
    return (
        alpha_index.sort_values("is_sharpe", ascending=False)["alpha_id"]
        .head(n)
        .tolist()
    )


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    ids = select_is_submittable(RUN_ID)
    if not ids or len(ids) < N_CLUSTERS:
        ids = select_all_alphas(RUN_ID)
    if not ids:
        return _fallback_topn(alpha_index, N_CLUSTERS)

    signs = member_signs_ic(RUN_ID, ids)
    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    if R is None or R.shape[1] < N_CLUSTERS:
        return _fallback_topn(alpha_index, N_CLUSTERS)

    # Filter 1: regime robustness — positive Sharpe in every IS sub-year.
    stable = _per_year_stable(R, min_years=2)
    if len(stable) >= N_CLUSTERS:
        R = R[stable]

    # Filter 2: drawdown discipline — exclude lucky-tail equity curves.
    dd_ok = [c for c in R.columns if _max_drawdown(R[c]) < DD_THRESHOLD]
    if len(dd_ok) >= N_CLUSTERS:
        R = R[dd_ok]

    # IS-Sharpe map (reused for dedup ranking and within-cluster representative pick).
    sharpe_map = {c: _annualized_sharpe(R[c]) for c in R.columns}

    # Filter 3: correlation dedup against near-clones.
    if R.shape[1] > N_CLUSTERS * 2:
        try:
            kept = correlation_dedup(R, threshold=DEDUP_RHO, keep_metric=sharpe_map)
            if len(kept) >= N_CLUSTERS:
                R = R[kept]
        except Exception:
            pass

    if R.shape[1] < N_CLUSTERS:
        # Not enough survivors — degrade gracefully to top-IS-Sharpe of what remains.
        ordered = sorted(R.columns, key=lambda c: sharpe_map.get(c, 0.0), reverse=True)
        if len(ordered) >= 2:
            return ordered
        return _fallback_topn(alpha_index, N_CLUSTERS)

    # Ward hierarchical clustering on correlation distance d = sqrt(0.5(1 - rho)).
    cols = list(R.columns)
    corr = R.corr().reindex(index=cols, columns=cols).fillna(0.0).clip(-1.0, 1.0)
    dist = np.sqrt(np.clip(0.5 * (1.0 - corr.values), 0.0, 1.0))
    dist = 0.5 * (dist + dist.T)
    np.fill_diagonal(dist, 0.0)

    try:
        condensed = ssd.squareform(dist, checks=False)
        Z = sch.linkage(condensed, method="ward")
        K = min(N_CLUSTERS, len(cols))
        labels = sch.fcluster(Z, t=K, criterion="maxclust")
    except Exception:
        return sorted(cols, key=lambda c: sharpe_map.get(c, 0.0), reverse=True)[:N_CLUSTERS]

    # Within each cluster, keep the single highest-IS-Sharpe representative (centroid pick).
    cluster_members: dict[int, list[str]] = {}
    for col, lab in zip(cols, labels):
        cluster_members.setdefault(int(lab), []).append(col)

    reps: list[str] = []
    for members in cluster_members.values():
        best = max(members, key=lambda c: sharpe_map.get(c, 0.0))
        reps.append(best)

    # Order representatives by IS Sharpe (deterministic).
    reps.sort(key=lambda c: sharpe_map.get(c, 0.0), reverse=True)
    if len(reps) < 2:
        return _fallback_topn(alpha_index, N_CLUSTERS)
    return reps


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    signs = member_signs_ic(RUN_ID, member_ids)
    R = load_member_is_returns(RUN_ID, member_ids, signs=signs)

    if R is None or R.shape[1] == 0:
        coef = {a: 1.0 for a in member_ids}
        coef = normalize_coefficients(coef, "l1")
        coef = {k: v * GROSS_SCALE for k, v in coef.items()}
        return apply_signs(coef, signs)

    # IS-Sharpe-proportional weighting (not min-var → preserves native gross).
    raw: dict[str, float] = {}
    for a in member_ids:
        if a in R.columns:
            raw[a] = max(_annualized_sharpe(R[a]), 0.05)
        else:
            raw[a] = 0.05

    # L1-normalize so Σ|c|=1, then push to escape the inverse-vol contraction trap.
    coef = normalize_coefficients(raw, "l1")
    coef = {k: v * GROSS_SCALE for k, v in coef.items()}

    # IC-sign alignment so each member contributes its deployable sign.
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