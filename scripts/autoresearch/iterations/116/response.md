I'll build a **HERC-inspired cluster-centroid equal-weight** composite (Raffinot 2018) — cov-FREE territory the user explicitly flagged as never attempted. Hierarchical Ward clustering on IS-return correlation distance, cut at K=6, take highest-IS-Sharpe alpha per cluster as centroid representative, equal-weight. Pre-filter with year-stability (positive Sharpe in every IS sub-year) + drawdown discipline (max IS DD < 25%) for regime robustness. Apply IC-based sign alignment. Aggressively scale coefficients 10× post-L1-normalization to escape the gross-exposure ceiling that traps cov-based optimizers at mean row L1 ≈ 0.05.

This sits in the leaderboard's winning pattern (n=6, year-stable, DD-disciplined, dedup ρ=0.85) but uses a cov-free combiner so weights aren't suppressed by 1/σ shrinkage.

```python COMPOSITE_FILE
"""HERC-style cluster-centroid equal-weight, cov-free (Raffinot 2018).

Hierarchical Equal Risk Contribution variant: Ward linkage clustering on
correlation distance d_ij = sqrt(0.5*(1 - rho_ij)) over IS returns, cut at
K=6 clusters, pick the highest-IS-Sharpe alpha per cluster as the centroid
representative, equal-weight them. Pre-gated with regime-robustness
filters: positive IS Sharpe in EVERY sub-year (2022/2023/2024) and max IS
drawdown < 25%. IC-aligned signs via member_signs_ic. Coefficients are
aggressively rescaled post-L1-normalization to push mean row L1 into the
[0.3, 0.9] target band -- escapes the 1/sigma gross-exposure trap that
muted prior cov-based attempts.
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

COMPOSITE_ID = "auto_116"
COMPOSITION_NOTE = "herc_centroid_yearstable_dd25_top6_covfree_gross_x10"

RUN_ID = "run_2026_05_c"
K_CLUSTERS = 6
DD_MAX = 0.25
DD_RELAX = 0.40
CORR_DEDUP = 0.85
TOP_BEFORE_CLUSTER = 30
GROSS_SCALE = 10.0


def _is_sharpe_map(R: pd.DataFrame) -> dict[str, float]:
    out: dict[str, float] = {}
    for col in R.columns:
        r = R[col].dropna()
        if len(r) < 20:
            out[col] = float("-inf")
            continue
        sd = float(r.std())
        if not np.isfinite(sd) or sd <= 0:
            out[col] = float("-inf")
            continue
        out[col] = float(r.mean() / sd * math.sqrt(252.0))
    return out


def _year_stable_ids(R: pd.DataFrame) -> list[str]:
    if R.empty or not isinstance(R.index, pd.DatetimeIndex):
        return list(R.columns)
    keep: list[str] = []
    years = sorted(set(R.index.year))
    if len(years) < 2:
        return list(R.columns)
    for col in R.columns:
        ok = True
        observed = 0
        for y in years:
            ry = R[col].loc[R.index.year == y].dropna()
            if len(ry) < 20:
                continue
            observed += 1
            sd = float(ry.std())
            if not np.isfinite(sd) or sd <= 0:
                ok = False
                break
            sh = float(ry.mean() / sd * math.sqrt(252.0))
            if not np.isfinite(sh) or sh <= 0:
                ok = False
                break
        if ok and observed >= 2:
            keep.append(col)
    return keep


def _dd_disciplined_ids(R: pd.DataFrame, max_dd: float) -> list[str]:
    keep: list[str] = []
    for col in R.columns:
        r = R[col].dropna()
        if len(r) < 20:
            continue
        eq = (1.0 + r).cumprod()
        peak = eq.cummax()
        dd_series = eq / peak - 1.0
        if dd_series.empty:
            continue
        dd = float(dd_series.min())
        if np.isfinite(dd) and abs(dd) <= max_dd:
            keep.append(col)
    return keep


def _cluster_centroids(
    R: pd.DataFrame, k: int, sharpe_map: dict[str, float]
) -> list[str]:
    cols = list(R.columns)
    if len(cols) <= k:
        return cols
    corr = R.corr().fillna(0.0).values.astype(float)
    corr = 0.5 * (corr + corr.T)
    np.fill_diagonal(corr, 1.0)
    dist = np.sqrt(np.clip(0.5 * (1.0 - corr), 0.0, 1.0))
    np.fill_diagonal(dist, 0.0)
    condensed = ssd.squareform(dist, checks=False)
    Z = sch.linkage(condensed, method="ward")
    labels = sch.fcluster(Z, t=k, criterion="maxclust")
    centroids: list[str] = []
    for cl in sorted(set(int(x) for x in labels)):
        members = [cols[i] for i, lb in enumerate(labels) if int(lb) == cl]
        if not members:
            continue
        best = max(members, key=lambda c: sharpe_map.get(c, float("-inf")))
        centroids.append(best)
    return centroids


def _safe_correlation_dedup(
    R: pd.DataFrame, threshold: float, sharpe_map: dict[str, float]
) -> list[str]:
    try:
        kept = correlation_dedup(R, threshold=threshold, keep_metric=sharpe_map)
        kept = [c for c in kept if c in R.columns]
        if len(kept) >= 2:
            return kept
    except Exception:
        pass
    return list(R.columns)


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    ids_all = list(select_is_submittable(RUN_ID) or [])
    if len(ids_all) < 3:
        ids_all = list(select_all_alphas(RUN_ID) or [])
    if len(ids_all) < 2:
        return ids_all

    signs0 = member_signs_ic(RUN_ID, ids_all)
    R = load_member_is_returns(RUN_ID, ids_all, signs=signs0)
    if R is None or R.empty or R.shape[1] < 2:
        return list(R.columns) if (R is not None and not R.empty) else []

    # Year-stability filter (regime-conditional robustness).
    ys = _year_stable_ids(R)
    if len(ys) >= K_CLUSTERS:
        R = R[ys]

    # Drawdown discipline; relax if it strips us below cluster count.
    dd = _dd_disciplined_ids(R, DD_MAX)
    if len(dd) < K_CLUSTERS:
        dd = _dd_disciplined_ids(R, DD_RELAX)
    if len(dd) >= K_CLUSTERS:
        R = R[dd]

    sharpe_map = _is_sharpe_map(R)

    # Rank-truncate before clustering for tractability and quality.
    ranked = sorted(
        R.columns, key=lambda c: -sharpe_map.get(c, float("-inf"))
    )
    top = ranked[: min(TOP_BEFORE_CLUSTER, len(ranked))]
    R = R[top]
    if R.shape[1] < 2:
        return list(R.columns)

    # Correlation dedup at rho=0.85 keeping by IS Sharpe.
    kept = _safe_correlation_dedup(R, CORR_DEDUP, sharpe_map)
    R = R[[c for c in kept if c in R.columns]]
    if R.shape[1] < 2:
        return list(R.columns)

    # Ward clustering + per-cluster centroid (highest IS Sharpe).
    k_use = min(K_CLUSTERS, R.shape[1])
    try:
        centroids = _cluster_centroids(R, k_use, sharpe_map)
    except Exception:
        centroids = []

    if len(centroids) < 2:
        ranked2 = sorted(
            R.columns, key=lambda c: -sharpe_map.get(c, float("-inf"))
        )
        centroids = ranked2[: max(2, k_use)]

    # Dedup preserving order.
    seen: set[str] = set()
    out: list[str] = []
    for c in centroids:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def member_weights(
    member_ids: list[str], alpha_index: pd.DataFrame
) -> dict[str, float]:
    if not member_ids:
        return {}
    signs = member_signs_ic(RUN_ID, member_ids)
    base: dict[str, float] = {m: 1.0 for m in member_ids}
    base = apply_signs(base, signs)
    base = normalize_coefficients(base, "l1")
    # Aggressive constant scale: cov-free 1/N at K=6 implies |c|=1/6 each;
    # mean row L1 of the composite panel collapses to a few percent without
    # rescaling. 10x lifts the typical gross exposure into [0.3, 0.9] per
    # the user's empirical guidance, while the runner's row-L1 clamp at 1.0
    # still caps tail rows.
    return {m: float(base[m]) * GROSS_SCALE for m in member_ids}


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
```
