"""Cov-free composite: Ward cluster centroids + IC-sign alignment + native gross
amplification. Cites Raffinot 2018 HERC clustering and Feng-Giglio-Xiu 2020
(Taming the Factor Zoo) for per-cluster representative selection. No Σ inversion
anywhere — avoids the 1/σ under-weighting trap that capped prior composites at
mean row-L1 ≈ 0.05."""
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
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_064_ward_cluster_centroid_k6_yearstable_dd25"
COMPOSITION_NOTE = "ward_cluster_centroid_k6_yearstable_dd25_signaligned_native"

RUN_ID = "run_2026_05_c"
K_CLUSTERS = 6
MAX_IS_DD = 0.25
DEDUP_RHO = 0.88
MIN_DAYS_PER_YEAR = 20
# Total |c| budget. Each centroid alpha typically has small row-L1, so we need
# to amplify before the runner's row-L1 clamp can engage. Empirically prior
# composites sat at mean row-L1 ≈ 0.05 with Σ|c|=1; aim for Σ|c|≈8 so the
# clamp pushes typical gross into [0.5, 0.9].
TARGET_TOTAL_ABS_COEF = 8.0


def _annual_sharpe(returns: pd.Series) -> float:
    s = returns.dropna()
    if len(s) < MIN_DAYS_PER_YEAR:
        return 0.0
    sd = float(s.std())
    if sd <= 0.0 or not math.isfinite(sd):
        return 0.0
    return float(s.mean() / sd * math.sqrt(252.0))


def _max_drawdown(returns: pd.Series) -> float:
    s = returns.fillna(0.0)
    if len(s) == 0:
        return 1.0
    eq = (1.0 + s).cumprod()
    peak = eq.cummax()
    dd = eq / peak - 1.0
    return float(-dd.min())


def _year_stable_columns(R: pd.DataFrame) -> list[str]:
    """Keep columns with strictly positive Sharpe in every calendar year of R."""
    if R.empty:
        return []
    years = sorted({d.year for d in R.index})
    if len(years) < 2:
        return list(R.columns)
    keep: list[str] = []
    for col in R.columns:
        ok = True
        for y in years:
            mask = [d for d in R.index if d.year == y]
            if len(mask) < MIN_DAYS_PER_YEAR:
                continue
            sh = _annual_sharpe(R[col].loc[mask])
            if sh <= 0.0:
                ok = False
                break
        if ok:
            keep.append(col)
    return keep


def _ward_cluster_labels(R: pd.DataFrame, k: int) -> np.ndarray:
    corr = R.corr().fillna(0.0).clip(-0.999, 0.999).values
    dist = np.sqrt(np.maximum(0.5 * (1.0 - corr), 0.0))
    np.fill_diagonal(dist, 0.0)
    condensed = ssd.squareform(dist, checks=False)
    Z = sch.linkage(condensed, method="ward")
    return sch.fcluster(Z, t=k, criterion="maxclust")


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    ids = select_is_submittable(RUN_ID)
    if len(ids) < 2 and "alpha_id" in getattr(alpha_index, "columns", []):
        ids = list(alpha_index["alpha_id"])
    if len(ids) < 2:
        return ids

    signs = member_signs_ic(RUN_ID, ids)
    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    if R.empty or len(R.columns) < 2:
        return list(R.columns)

    # 1) year-stability filter (regime-aware)
    stable = _year_stable_columns(R)
    if len(stable) < K_CLUSTERS * 2:
        # relax — take whatever's available
        stable = list(R.columns)
    R = R[stable]

    # 2) drawdown discipline
    dd_pairs = [(c, _max_drawdown(R[c])) for c in R.columns]
    keep_dd = [c for c, d in dd_pairs if d < MAX_IS_DD]
    if len(keep_dd) < K_CLUSTERS * 2:
        dd_pairs.sort(key=lambda kv: kv[1])
        keep_dd = [c for c, _ in dd_pairs[: max(K_CLUSTERS * 3, 18)]]
    R = R[keep_dd]

    # 3) correlation dedup at ρ=0.88, ranked by IS Sharpe
    sharpe = {c: _annual_sharpe(R[c]) for c in R.columns}
    kept = correlation_dedup(R, DEDUP_RHO, keep_metric=sharpe)
    if len(kept) < 2:
        kept = list(R.columns)
    R = R[kept]

    if len(kept) <= K_CLUSTERS:
        return kept

    # 4) Ward clustering on correlation distance → one centroid per cluster
    labels = _ward_cluster_labels(R, K_CLUSTERS)
    chosen: list[str] = []
    for lab in sorted(set(labels.tolist())):
        members = [kept[i] for i in range(len(kept)) if labels[i] == lab]
        if not members:
            continue
        members.sort(key=lambda c: sharpe.get(c, 0.0), reverse=True)
        chosen.append(members[0])

    chosen.sort(key=lambda c: sharpe.get(c, 0.0), reverse=True)
    chosen = chosen[:K_CLUSTERS]
    if len(chosen) < 2:
        # last-resort: top-K by IS Sharpe outright
        ranked = sorted(sharpe.items(), key=lambda kv: kv[1], reverse=True)
        chosen = [c for c, _ in ranked[:K_CLUSTERS]]
    return chosen


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    if not member_ids:
        return {}
    signs = member_signs_ic(RUN_ID, member_ids)

    # Equal-weight across selected centroids (cov-free; no 1/σ under-weighting).
    base_raw: dict[str, float] = {a: 1.0 for a in member_ids}
    base = normalize_coefficients(base_raw, "l1")  # Σ|c| = 1, all positive

    # Flip alphas whose IC is negative so they contribute their deployable sign.
    signed = apply_signs(base, signs)

    # Amplify Σ|c| past 1 so the runner's row-L1 clamp engages and the typical
    # gross exposure lands in [0.5, 0.9] rather than ≈0.05 with a tangency
    # vector. The clamp will cap any row that would exceed 1.
    coef = {k: float(v) * TARGET_TOTAL_ABS_COEF for k, v in signed.items()}
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