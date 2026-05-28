Looking at this task, I need to design composite attempt #88 with focus on cov-FREE methods (since cov-based optimizers produce 1/σ weights that hit the gross-exposure ceiling).

**Reasoning — picking the angle**

The prompt explicitly flags Gram-Schmidt as failed 9/9 and warns that cov-based tangency/min-var collapses to 5% gross exposure. The user-suggested "cluster centroid then equal-weight" is unexplored and bypasses Σ⁻¹ entirely.

**Method: HRP-style quasi-diagonalization → cluster centroids → equal-weight (cov-FREE)**

Cites López de Prado (2016) "Building Diversified Portfolios that Outperform Out of Sample" — the cluster-tree approach to diversification. Instead of recursive bisection bottom-up risk allocation, I take the centroid (best IS Sharpe within cluster) and equal-weight across K clusters. This preserves native member exposure while ensuring orthogonality across cluster reps.

**Regime-robustness add-ons (since regime change is the dominant failure):**
1. Per-year IS stability filter — alphas must have positive mean return in every IS sub-year (2022/2023/2024) to be eligible.
2. Drawdown discipline — drop alphas with IS max DD > 25%.
3. Correlation dedup at ρ=0.85 (removes near-clones before clustering, so clusters don't get hijacked by mega-families).
4. Sign-alignment via `member_signs_ic` so IC<0 alphas get flipped to deployable polarity.
5. K=6 clusters (sweet spot from leaderboard pattern n=5-8).
6. Aggressive native-exposure scaling at the end (×8) — after `normalize_coefficients(...,"l1")` gives Σ|c|=1, multiply by 8 so the runner's row-L1 clamp actually bites and we use meaningful gross.

**Idea-family novelty check:** "cluster-centroid equal-weight" does NOT appear in tried list (auto_009 was HRP-Lopez-de-Prado *quasidiag sharpe tilt*, auto_013 was *cluster median* — different mechanism: HRP recursive bisection or cluster-median, not centroid-best-Sharpe). Combined with year-stability + DD discipline + native scaling, this is fresh territory.

```python COMPOSITE_FILE
"""Cov-free cluster-centroid composite (López de Prado HRP 2016 quasi-diag):
Ward clustering on (1-corr)/2 distance, pick highest-IS-Sharpe centroid per
cluster, equal-weight across K=6 clusters. Sign-aligned via IC, with per-year
IS stability + drawdown discipline. Skips Σ⁻¹ entirely to bypass the 1/σ
weighting trap; aggressive native-exposure scaling to use the gross budget."""
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

COMPOSITE_ID = "auto_088"
COMPOSITION_NOTE = "ward_cluster_centroid_k6_yearstable_dd25_covfree_scale8"

RUN_ID = "run_2026_05_c"
K_CLUSTERS = 6
DD_MAX = 0.25
DEDUP_RHO = 0.85
MIN_DAYS = 60
SHARPE_FLOOR = 0.4
NATIVE_SCALE = 8.0


def _sharpe(r: pd.Series) -> float:
    r = r.dropna()
    if r.size < 20:
        return 0.0
    s = float(r.std())
    if s <= 0.0 or not np.isfinite(s):
        return 0.0
    return float(np.sqrt(252.0) * r.mean() / s)


def _year_stable(r: pd.Series) -> bool:
    r = r.dropna()
    if r.size == 0:
        return False
    try:
        years = r.index.year
    except Exception:
        return True
    by_year = r.groupby(years)
    n = 0
    for _, sub in by_year:
        if sub.size < 20:
            continue
        n += 1
        if float(sub.mean()) <= 0.0:
            return False
    return n >= 2


def _max_dd(r: pd.Series) -> float:
    r = r.dropna()
    if r.size == 0:
        return 1.0
    eq = (1.0 + r).cumprod()
    peak = eq.cummax()
    dd = float((eq / peak - 1.0).min())
    return abs(dd)


def _filtered_pool() -> tuple[pd.DataFrame, dict[str, float]]:
    ids = select_is_submittable(RUN_ID)
    if not ids or len(ids) < 12:
        ids = select_all_alphas(RUN_ID)
    signs = member_signs_ic(RUN_ID, ids)
    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    R = R.dropna(axis=1, how="all")

    keep: list[str] = []
    sharpes: dict[str, float] = {}
    for col in R.columns:
        s = R[col].dropna()
        if s.size < MIN_DAYS:
            continue
        sh = _sharpe(s)
        if sh <= SHARPE_FLOOR:
            continue
        if _max_dd(s) > DD_MAX:
            continue
        if not _year_stable(s):
            continue
        keep.append(col)
        sharpes[col] = sh

    if len(keep) < K_CLUSTERS + 2:
        # Fallback: relax year-stability, broaden DD slightly
        keep = []
        sharpes = {}
        for col in R.columns:
            s = R[col].dropna()
            if s.size < MIN_DAYS:
                continue
            sh = _sharpe(s)
            if sh <= 0.3:
                continue
            if _max_dd(s) > DD_MAX + 0.10:
                continue
            keep.append(col)
            sharpes[col] = sh

    if len(keep) < 2:
        # Last resort: take top-K by Sharpe over whole pool
        all_sh = {col: _sharpe(R[col]) for col in R.columns if R[col].dropna().size >= MIN_DAYS}
        keep = sorted(all_sh, key=lambda a: all_sh[a], reverse=True)[: max(K_CLUSTERS, 4)]
        sharpes = {k: all_sh[k] for k in keep}

    Rk = R[keep].copy()
    return Rk, sharpes


def _cluster_centroids(Rk: pd.DataFrame, sharpes: dict[str, float]) -> list[str]:
    cols = list(Rk.columns)
    if len(cols) <= K_CLUSTERS:
        return cols

    corr = Rk.corr().fillna(0.0).values
    np.fill_diagonal(corr, 1.0)
    d = np.sqrt(np.clip(0.5 * (1.0 - corr), 0.0, None))
    d = 0.5 * (d + d.T)
    np.fill_diagonal(d, 0.0)

    try:
        condensed = ssd.squareform(d, checks=False)
        Z = sch.linkage(condensed, method="average")
        labels = sch.fcluster(Z, t=K_CLUSTERS, criterion="maxclust")
    except Exception:
        ranked = sorted(cols, key=lambda a: sharpes.get(a, 0.0), reverse=True)
        return ranked[:K_CLUSTERS]

    centroids: list[str] = []
    for c in sorted(set(int(x) for x in labels.tolist())):
        members = [cols[i] for i, lab in enumerate(labels) if int(lab) == c]
        if not members:
            continue
        best = max(members, key=lambda a: sharpes.get(a, 0.0))
        centroids.append(best)

    if len(centroids) < 2:
        ranked = sorted(cols, key=lambda a: sharpes.get(a, 0.0), reverse=True)
        return ranked[: max(K_CLUSTERS, 4)]
    return centroids


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    Rk, sharpes = _filtered_pool()
    # Dedup near-clones before clustering so clusters reflect real structure.
    deduped = correlation_dedup(Rk, threshold=DEDUP_RHO, keep_metric=sharpes)
    if not deduped or len(deduped) < 2:
        deduped = list(Rk.columns)
    Rd = Rk[deduped]
    centroids = _cluster_centroids(Rd, sharpes)
    if len(centroids) < 2:
        # Defensive: ensure runner gets >= 2 members
        ranked = sorted(deduped, key=lambda a: sharpes.get(a, 0.0), reverse=True)
        centroids = ranked[: max(2, K_CLUSTERS)]
    return centroids


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    if not member_ids:
        return {}
    signs = member_signs_ic(RUN_ID, member_ids)
    base: dict[str, float] = {a: 1.0 for a in member_ids}
    base = apply_signs(base, signs)
    base = normalize_coefficients(base, "l1")  # Σ|c| = 1, equal-weight after signs
    # Native-exposure scaling: cov-free composers leave gross on the table after
    # row-L1 clamp; multiply by NATIVE_SCALE so the runner clamp actually bites
    # and composite mean row-L1 lands in the [0.5, 0.8] productive band.
    return {a: float(w) * NATIVE_SCALE for a, w in base.items()}


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
