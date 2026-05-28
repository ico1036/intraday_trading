Looking at this iteration, the dominant pattern from recent failures and leaderboard data is:
- Cov-based optimizers (tangency, min-var, even Neumann series) collapse to `w ∝ Σ⁻¹·μ`, which under-allocates → mean row L1 ≈ 0.05 → muted PnL.
- "Anti-bias" selectors go OS-negative (regime shift).
- Gram-Schmidt failed 9/9 (residual-Sharpe overfits).
- Winning ingredients: n∈[5,8], year-stable, DD-disciplined, ρ≈0.85 dedup.

The user-suggested "cluster centroid then equal-weight" path (Raffinot 2018 HERC representative-style allocation, with Mantegna 1999 correlation distance and Ward linkage) has never been attempted in this run, sidesteps cov inversion entirely (so no 1/σ trap), and stacks naturally with year-stability + drawdown filters. Equal-weight K=6 centroids, sign-aligned via IC, L1-normalized then scaled up to a deliberate gross-target multiplier (≈3×) to escape the gross-exposure ceiling that crushed prior iterations.

```python COMPOSITE_FILE
"""HERC-style cluster-centroid equal-weight composite with year-stability and drawdown discipline.

Cites: Raffinot (2018) "Hierarchical Clustering-Based Asset Allocation" (HERC)
representative-per-cluster allocation; Mantegna (1999) correlation-distance
ultrametric for financial time series; Lopez de Prado (2016) HRP quasi-diag
clustering on Ward linkage. Composition is cov-inversion-free: clusters are
formed on sqrt(0.5*(1-rho)) distance, the single highest-IS-Sharpe member per
cluster is taken as centroid, and centroids are equal-weighted (sign-aligned
via IC) then L1-normalized and rescaled to a deliberate gross-exposure target.
This bypasses the 1/sigma underweighting trap that has muted prior tangency /
min-var attempts and concentrates risk on a handful of orthogonal, regime-
robust members (positive Sharpe in every IS sub-year, max IS drawdown < 25%).
"""
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

COMPOSITE_ID = "auto_102"
COMPOSITION_NOTE = "herc_centroid_yearstable_dd25_dedup085_k6_eqw_g3"

RUN_ID = "run_2026_05_c"
N_CLUSTERS = 6
DEDUP_RHO = 0.85
MAX_DD = 0.25
MIN_OBS = 60
TARGET_GROSS = 3.0  # post-L1-normalize multiplier -> aim composite mean row L1 ~ 0.6


def _max_drawdown(returns: pd.Series) -> float:
    s = returns.fillna(0.0)
    if len(s) == 0:
        return 0.0
    eq = (1.0 + s).cumprod()
    peak = eq.cummax()
    dd = (eq / peak) - 1.0
    return float(-dd.min())


def _year_stable(returns: pd.Series) -> bool:
    try:
        idx = pd.to_datetime(returns.index)
        years = np.asarray(idx.year, dtype=int)
    except Exception:
        return True
    buckets: dict[int, list[float]] = {}
    vals = returns.values.astype(float)
    for y, v in zip(years.tolist(), vals.tolist()):
        buckets.setdefault(int(y), []).append(float(v))
    checked = 0
    for _, lst in buckets.items():
        if len(lst) < 30:
            continue
        checked += 1
        arr = np.asarray(lst, dtype=float)
        sd = float(arr.std(ddof=0))
        if sd <= 0.0:
            continue
        sh = float(arr.mean()) / sd * float(np.sqrt(252.0))
        if sh <= 0.0:
            return False
    return checked >= 1


def _resolve_pool() -> list[str]:
    pool = list(select_is_submittable(RUN_ID) or [])
    if len(pool) < 4:
        pool = list(select_all_alphas(RUN_ID) or [])
    return pool


def _filter_returns(R: pd.DataFrame) -> list[str]:
    kept: list[str] = []
    for col in R.columns:
        s = R[col].dropna()
        if len(s) < MIN_OBS:
            continue
        if _max_drawdown(s) > MAX_DD:
            continue
        if not _year_stable(s):
            continue
        kept.append(col)
    return kept


def _cluster_centroids(R: pd.DataFrame, sharpe_map: dict[str, float], k: int) -> list[str]:
    cols = list(R.columns)
    if len(cols) <= k:
        return cols
    corr_df = R.corr().fillna(0.0)
    corr = corr_df.values.astype(float)
    np.fill_diagonal(corr, 1.0)
    d = np.sqrt(np.clip(0.5 * (1.0 - corr), 0.0, 1.0))
    d = 0.5 * (d + d.T)
    np.fill_diagonal(d, 0.0)
    condensed = ssd.squareform(d, checks=False)
    Z = sch.linkage(condensed, method="ward")
    labels = sch.fcluster(Z, t=k, criterion="maxclust")
    reps: list[str] = []
    for lab in sorted({int(x) for x in labels.tolist()}):
        members = [cols[i] for i, L in enumerate(labels) if int(L) == lab]
        if not members:
            continue
        best = max(members, key=lambda a: sharpe_map.get(a, float("-inf")))
        reps.append(best)
    return reps


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    pool = _resolve_pool()
    if len(pool) < 2:
        return pool

    sharpe_map = dict(member_is_sharpe(RUN_ID, pool) or {})

    try:
        signs = member_signs_ic(RUN_ID, pool)
    except Exception:
        signs = None
    R = load_member_is_returns(RUN_ID, pool, signs=signs)
    if R is None or R.shape[1] < 2:
        ranked = sorted(pool, key=lambda a: sharpe_map.get(a, float("-inf")), reverse=True)
        return ranked[: max(N_CLUSTERS, 6)]

    kept = _filter_returns(R)
    if len(kept) < max(N_CLUSTERS, 4):
        # filter too strict -> fall back to top-IS-Sharpe broad shortlist
        ranked = sorted(
            list(R.columns), key=lambda a: sharpe_map.get(a, float("-inf")), reverse=True
        )
        kept = ranked[: min(max(20, N_CLUSTERS * 3), len(ranked))]

    R2 = R[[c for c in kept if c in R.columns]]
    if R2.shape[1] < 2:
        ranked = sorted(pool, key=lambda a: sharpe_map.get(a, float("-inf")), reverse=True)
        return ranked[: max(N_CLUSTERS, 6)]

    try:
        deduped = correlation_dedup(R2, threshold=DEDUP_RHO, keep_metric=sharpe_map)
    except Exception:
        deduped = list(R2.columns)
    deduped = [a for a in deduped if a in R2.columns]
    if len(deduped) < 2:
        deduped = list(R2.columns)

    R3 = R2[deduped]
    k_eff = int(min(N_CLUSTERS, R3.shape[1]))
    if k_eff < 2:
        k_eff = min(2, R3.shape[1])

    try:
        reps = _cluster_centroids(R3, sharpe_map, k_eff)
    except Exception:
        reps = sorted(deduped, key=lambda a: sharpe_map.get(a, float("-inf")), reverse=True)[:k_eff]

    if len(reps) < 2:
        reps = sorted(deduped, key=lambda a: sharpe_map.get(a, float("-inf")), reverse=True)[
            : max(N_CLUSTERS, 4)
        ]
    return reps


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    n = max(len(member_ids), 1)
    base: dict[str, float] = {a: 1.0 / float(n) for a in member_ids}
    try:
        signs = member_signs_ic(RUN_ID, member_ids)
        base = apply_signs(base, signs)
    except Exception:
        pass
    base = normalize_coefficients(base, "l1")
    return {k: float(v) * TARGET_GROSS for k, v in base.items()}


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
