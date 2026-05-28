I'll skip cov-based optimization entirely this iteration. The user's diagnostic is clear: tangency/min-var produces 1/σ-weighted vectors that the row-L1 clamp never scales up, so the composite leaves 95% of the risk budget on the table. The "Cluster centroid then equal-weight" cov-free recipe is explicitly recommended and not yet attempted.

**Plan (Ward-cluster centroid 1/N + regime filters):**

1. Load all IS-submittable alphas for `run_2026_05_c`, sign-align via `member_signs_ic` (IC<0 alphas flipped).
2. Compute per-member IS Sharpe on signed returns.
3. **Regime-robustness filter (year-stability):** drop any alpha whose signed daily Sharpe is non-positive in any calendar year of the IS window — this directly attacks the IS/OS regime-shift failure mode that has dominated prior attempts.
4. **Drawdown discipline:** drop alphas with max IS DD > 20% (less likely to be lucky tail-event survivors).
5. **Correlation dedup at ρ > 0.90** to thin near-clones, ranked by IS Sharpe.
6. **Ward hierarchical clustering** on `√(½(1−ρ))` correlation distance → cut at K=6 clusters (Lopez de Prado 2016 distance metric, but used cov-free here, à la Raffinot's HERC pre-step).
7. Within each cluster, take the single highest-IS-Sharpe alpha as centroid representative.
8. **Pure 1/K equal-weight** over the 6 centroids (no Σ⁻¹·μ), then apply signs.
9. **Gross-exposure fix:** after `normalize_coefficients(c, "l1")` (Σ|c|=1, i.e. each = 1/6), multiply by 10× so the runner's row-L1 ≤ 1 clamp actually engages — empirically prior attempts at Σ|c|=1 produced mean row L1 ≈ 0.05; a 10× scale-up should land mean row L1 in the [0.4, 0.8] target band.

Citation: Ward (1963) minimum-variance hierarchical clustering on Lopez de Prado (2016) correlation distance `d_ij = √(½(1−ρ_ij))`, with cluster-centroid 1/N pooling (an HRP-distance / HERC-style preprocessing without recursive bisection or σ-weighting).

Idea family is fresh: no prior auto_NNN file used pure cluster-centroid equal-weighting; the cov-free angle is exactly what the user flagged as the underexplored direction.

```python COMPOSITE_FILE
"""Cov-free composite: Ward hierarchical clustering on Lopez-de-Prado correlation
distance d_ij = sqrt(0.5*(1-rho_ij)) (Ward 1963; LdP 2016), then equal-weight the
per-cluster highest-IS-Sharpe centroid. Year-stability + max-DD filters address
the dominant IS/OS regime-shift failure mode. No covariance inversion — bypasses
the 1/sigma-weighting trap that has starved prior composites of gross exposure."""
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
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_097"
COMPOSITION_NOTE = "ward_centroid_eqw_yearstable_dd20_dedup090_k6_scale10x"

RUN_ID = "run_2026_05_c"
N_CLUSTERS = 6
DD_THRESHOLD = 0.20
DEDUP_RHO = 0.90
GROSS_SCALE = 10.0  # after L1-normalize: each coef ~1/K; scale up so row-L1 clamp engages


def _is_sharpe(series: pd.Series) -> float:
    s = series.dropna()
    if len(s) < 5:
        return 0.0
    sd = float(s.std())
    if sd <= 0.0:
        return 0.0
    return float(s.mean() / sd)


def _year_stable(R: pd.DataFrame) -> list[str]:
    """Keep alphas with strictly positive Sharpe in every calendar year of IS."""
    idx = R.index
    if not isinstance(idx, pd.DatetimeIndex):
        try:
            idx = pd.to_datetime(idx)
        except Exception:
            return list(R.columns)
    years = sorted(set(int(y) for y in idx.year))
    if len(years) < 2:
        return list(R.columns)
    keep: list[str] = []
    for col in R.columns:
        ok = True
        col_series = R[col]
        for y in years:
            mask = idx.year == y
            sub = col_series[mask].dropna()
            if len(sub) < 10:
                # too few obs to judge — give benefit of the doubt
                continue
            sd = float(sub.std())
            if sd <= 0.0 or (float(sub.mean()) / sd) <= 0.0:
                ok = False
                break
        if ok:
            keep.append(col)
    return keep


def _max_drawdown(series: pd.Series) -> float:
    r = series.fillna(0.0).astype(float).values
    if r.size == 0:
        return 0.0
    eq = np.cumprod(1.0 + r)
    peak = np.maximum.accumulate(eq)
    dd = (eq - peak) / np.where(peak > 0, peak, 1.0)
    return float(-dd.min())


def _dd_filter(R: pd.DataFrame, threshold: float) -> list[str]:
    return [c for c in R.columns if _max_drawdown(R[c]) < threshold]


def _ward_cluster_centroids(
    R: pd.DataFrame, sharpe_map: dict, k: int
) -> list[str]:
    cols = list(R.columns)
    n = len(cols)
    if n <= k:
        return cols
    corr = R.corr().fillna(0.0).to_numpy(copy=True)
    np.fill_diagonal(corr, 1.0)
    corr = np.clip(corr, -1.0, 1.0)
    dist = np.sqrt(np.clip(0.5 * (1.0 - corr), 0.0, 1.0))
    np.fill_diagonal(dist, 0.0)
    # enforce symmetry
    dist = 0.5 * (dist + dist.T)
    cond = ssd.squareform(dist, checks=False)
    Z = sch.linkage(cond, method="ward")
    labels = sch.fcluster(Z, t=k, criterion="maxclust")
    chosen: list[str] = []
    for cl in np.unique(labels):
        idxs = [i for i in range(n) if labels[i] == cl]
        if not idxs:
            continue
        best = max(idxs, key=lambda i: sharpe_map.get(cols[i], 0.0))
        chosen.append(cols[best])
    return chosen


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    ids = select_is_submittable(RUN_ID)
    if not ids and "alpha_id" in alpha_index.columns:
        ids = list(alpha_index["alpha_id"])
    if not ids:
        return []
    signs = member_signs_ic(RUN_ID, ids)
    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    R = R.dropna(axis=1, how="all")
    if R.shape[1] < 2:
        return list(R.columns)

    sharpe = {c: _is_sharpe(R[c]) for c in R.columns}

    # Stage 1: regime + drawdown filters
    year_keep = set(_year_stable(R))
    dd_keep = set(_dd_filter(R, DD_THRESHOLD))
    filtered = [
        c for c in R.columns
        if c in year_keep and c in dd_keep and sharpe.get(c, 0.0) > 0.0
    ]
    # Cascading fallbacks if filters are too aggressive
    if len(filtered) < N_CLUSTERS:
        filtered = [c for c in R.columns if c in year_keep and sharpe.get(c, 0.0) > 0.0]
    if len(filtered) < N_CLUSTERS:
        filtered = [c for c in R.columns if sharpe.get(c, 0.0) > 0.0]
    if len(filtered) < N_CLUSTERS:
        filtered = sorted(R.columns, key=lambda c: -sharpe.get(c, 0.0))[: max(N_CLUSTERS * 3, 12)]

    R_f = R[filtered]

    # Stage 2: dedup near-clones, ranked by IS Sharpe
    try:
        deduped = correlation_dedup(
            R_f,
            threshold=DEDUP_RHO,
            keep_metric={c: sharpe.get(c, 0.0) for c in filtered},
        )
    except Exception:
        deduped = filtered
    if len(deduped) < N_CLUSTERS:
        deduped = filtered

    R_d = R[deduped]

    # Stage 3: Ward cluster -> per-cluster centroid (highest IS Sharpe)
    try:
        chosen = _ward_cluster_centroids(R_d, sharpe, N_CLUSTERS)
    except Exception:
        chosen = sorted(deduped, key=lambda c: -sharpe.get(c, 0.0))[:N_CLUSTERS]

    # Deterministic order
    chosen = sorted(set(chosen), key=lambda c: -sharpe.get(c, 0.0))
    if len(chosen) < 2:
        chosen = sorted(R.columns, key=lambda c: -sharpe.get(c, 0.0))[: max(N_CLUSTERS, 4)]
    return list(chosen)


def member_weights(
    member_ids: list[str], alpha_index: pd.DataFrame
) -> dict[str, float]:
    if not member_ids:
        return {}
    signs = member_signs_ic(RUN_ID, member_ids)

    # Equal weight across kept centroids (cov-free)
    coef = {a: 1.0 for a in member_ids}
    coef = normalize_coefficients(coef, "l1")  # sum |c| = 1, each = 1/K

    # Sign alignment for deployable direction (IC<0 -> negative coef)
    coef = apply_signs(coef, signs)

    # Critical: scale up so the runner row-L1 clamp engages and mean
    # gross exposure lands in the productive band (not 5% of budget).
    coef = {a: float(v) * GROSS_SCALE for a, v in coef.items()}
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
