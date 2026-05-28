I'll pick the **Ward cluster-centroid + equal-weight** cov-free approach (Raffinot 2018 HERC-style cluster representatives) — flagged as never-attempted and explicitly user-suggested. It bypasses the 1/σ-weighting trap that has been the dominant blocker. Combined with per-year IS stability + max-DD ≤ 20% pre-filters and a final gross-exposure rescale to mean row L1 ≈ 0.70.

Mechanism:
1. `select_is_submittable` → IC-sign-flipped IS returns matrix
2. Filter: per-year Sharpe positive in every IS sub-year (regime robustness)
3. Filter: max IS drawdown ≤ 20% (tail-event discipline)
4. `correlation_dedup` at ρ = 0.85 (drop near-clones)
5. Ward hierarchical clustering on `sqrt(0.5(1-ρ))` distance, K=6
6. Pick highest-IS-Sharpe alpha per cluster (centroid representative)
7. Equal-weight, sign-aware, L1-normalize, scale by 0.70

Literature: Raffinot (2018, "Hierarchical Clustering-Based Asset Allocation") — cluster-representative equal-weighting; Lopez de Prado (2016) HRP for the correlation-distance + Ward backbone. No Σ⁻¹ anywhere, so native member leverage is preserved.

```python COMPOSITE_FILE
"""Ward cluster-centroid equal-weight composite with per-year IS stability
and max-DD<=20% pre-filters. Cov-free composition: Raffinot (2018) HERC
cluster-representative idea on Lopez de Prado (2016) HRP-style sqrt(0.5(1-rho))
Ward backbone. No covariance inversion -> bypasses the 1/sigma-weighting
trap of tangency/min-var optimizers and preserves native member leverage."""
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
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_094"
COMPOSITION_NOTE = "ward_centroid_yearstable_dd20_rho085_k6_eqw_gross070"

RUN_ID = "run_2026_05_c"
N_CLUSTERS = 6
DD_THRESHOLD = 0.20          # reject members whose IS max drawdown exceeds 20%
RHO_DEDUP = 0.85
TARGET_GROSS = 0.70          # post-normalization aggregate |c|_1 target
MIN_YEAR_OBS = 20            # minimum bars per sub-year to evaluate stability


def _year_stable(R: pd.DataFrame) -> list[str]:
    if R.empty:
        return []
    idx = pd.to_datetime(R.index)
    years = pd.Series(idx.year, index=R.index)
    uniq_years = years.unique()
    kept: list[str] = []
    for col in R.columns:
        s = R[col].dropna()
        if s.empty:
            continue
        ok = True
        evaluated = 0
        for y in uniq_years:
            mask = years == y
            sub = R.loc[mask, col].dropna()
            if len(sub) < MIN_YEAR_OBS:
                continue
            mu = float(sub.mean())
            sd = float(sub.std(ddof=1))
            if sd <= 0.0 or not np.isfinite(sd):
                ok = False
                break
            if mu / sd <= 0.0:
                ok = False
                break
            evaluated += 1
        if ok and evaluated >= 1:
            kept.append(col)
    return kept


def _max_drawdown(s: pd.Series) -> float:
    if s.empty:
        return 0.0
    eq = (1.0 + s.fillna(0.0)).cumprod()
    peak = eq.cummax()
    dd = (eq / peak) - 1.0
    return float(dd.min())


def _dd_discipline(R: pd.DataFrame, threshold: float) -> list[str]:
    kept: list[str] = []
    for col in R.columns:
        s = R[col].dropna()
        if s.empty:
            continue
        mdd = _max_drawdown(s)
        # mdd is non-positive; require shallower than -threshold
        if mdd > -threshold:
            kept.append(col)
    return kept


def _is_sharpe_map(R: pd.DataFrame) -> dict[str, float]:
    out: dict[str, float] = {}
    for col in R.columns:
        s = R[col].dropna()
        if len(s) < MIN_YEAR_OBS:
            out[col] = 0.0
            continue
        sd = float(s.std(ddof=1))
        if sd <= 0.0 or not np.isfinite(sd):
            out[col] = 0.0
            continue
        out[col] = float(s.mean() / sd * np.sqrt(252.0))
    return out


def _ward_cluster_centroids(
    R: pd.DataFrame, k: int, sharpe: dict[str, float]
) -> list[str]:
    cols = list(R.columns)
    n = len(cols)
    if n <= k:
        return cols
    corr = R.corr().fillna(0.0).values
    # HRP-style distance: sqrt(0.5 * (1 - rho)), clipped for numerical safety
    d = np.sqrt(np.clip(0.5 * (1.0 - corr), 0.0, 1.0))
    np.fill_diagonal(d, 0.0)
    d = 0.5 * (d + d.T)
    cond = ssd.squareform(d, checks=False)
    Z = sch.linkage(cond, method="ward")
    labels = sch.fcluster(Z, t=k, criterion="maxclust")
    centroids: list[str] = []
    for c in np.unique(labels):
        members = [cols[i] for i in range(n) if labels[i] == c]
        if not members:
            continue
        best = max(members, key=lambda a: sharpe.get(a, -np.inf))
        centroids.append(best)
    return centroids


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    ids = select_is_submittable(RUN_ID)
    if len(ids) < N_CLUSTERS:
        ids = select_all_alphas(RUN_ID)
    if len(ids) < 2:
        return list(alpha_index["alpha_id"].head(N_CLUSTERS))

    signs = member_signs_ic(RUN_ID, ids)
    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    if R is None or R.empty or R.shape[1] < 2:
        return list(alpha_index["alpha_id"].head(N_CLUSTERS))

    # Per-year IS stability (regime-conditional robustness)
    stable = _year_stable(R)
    if len(stable) >= N_CLUSTERS:
        R = R[stable]

    # Drawdown discipline (tail-event robustness)
    dd_ok = _dd_discipline(R, DD_THRESHOLD)
    if len(dd_ok) >= N_CLUSTERS:
        R = R[dd_ok]

    sharpe = _is_sharpe_map(R)

    # Correlation dedup (drop near-clones; keep highest-Sharpe per group)
    try:
        deduped = correlation_dedup(R, RHO_DEDUP, keep_metric=sharpe)
    except Exception:
        deduped = list(R.columns)
    if len(deduped) >= N_CLUSTERS:
        R = R[deduped]

    if R.shape[1] <= N_CLUSTERS:
        # Not enough members to cluster meaningfully; take what we have
        ranked = sorted(R.columns, key=lambda a: sharpe.get(a, -np.inf), reverse=True)
        return ranked[: max(N_CLUSTERS, 2)]

    centroids = _ward_cluster_centroids(R, N_CLUSTERS, sharpe)
    # Safety: dedupe and cap
    seen: set[str] = set()
    out: list[str] = []
    for a in centroids:
        if a not in seen:
            seen.add(a)
            out.append(a)
    if len(out) < 2:
        ranked = sorted(R.columns, key=lambda a: sharpe.get(a, -np.inf), reverse=True)
        return ranked[: max(N_CLUSTERS, 2)]
    return out


def member_weights(
    member_ids: list[str], alpha_index: pd.DataFrame
) -> dict[str, float]:
    if not member_ids:
        return {}
    # Sign-aware (flip IC<0 alphas to their deployable direction)
    signs = member_signs_ic(RUN_ID, member_ids)
    raw = {a: 1.0 for a in member_ids}  # equal-weight, cov-free
    raw = apply_signs(raw, signs)
    coef = normalize_coefficients(raw, "l1")  # sum |c| == 1
    # Scale aggregate gross to TARGET_GROSS (combat row-L1 underfill)
    coef = {k: float(v) * TARGET_GROSS for k, v in coef.items()}
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
```
