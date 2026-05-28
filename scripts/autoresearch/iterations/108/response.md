Looking at this iteration 108 spec, the key signals are:

1. **Cov-FREE composition is flagged as never-attempted** — every prior attempt used cov-based optimizers which produce 1/σ underweighting and leave 95% of risk budget unused.
2. **Gram-Schmidt failed 9/9** — skip it.
3. **Cluster centroid + equal-weight is on the recommended list** (Lopez de Prado MLA-style: cluster on correlation distance, pick the highest-IS-Sharpe per cluster, equal-weight).
4. **n ∈ [5, 8] sweet spot**, per-year IS stability filter, and DD < 20% are the consistent winning ingredients.
5. **Fixed gross multiplier** (~8×) is empirically required to escape the gross-exposure ceiling, since equal-weight with K=6 leaves each coefficient at 1/6 ≈ 0.17.

Method: Ward hierarchical clustering on correlation distance `sqrt(0.5·(1-ρ))`, cut into K=6 clusters, take each cluster's centroid as the highest-IS-Sharpe member (Lopez de Prado, *Machine Learning for Asset Managers*, 2019, ch. 4 — clustering for noise reduction). Pre-filter by per-year IS stability + max DD < 20% + min IS Sharpe 0.30. Cov-free: no inversion, no tangency — preserves native member leverage. Apply IC-implied signs, L1-normalize, then multiply by 8× to hit the target mean row L1.

This is genuinely novel territory for this run (no prior attempt used cov-free clustering centroids).

```python COMPOSITE_FILE
"""Cov-free Ward cluster-centroid composite with per-year IS stability and DD discipline (Lopez de Prado, Machine Learning for Asset Managers 2019 ch.4 — cluster-then-representative approach for noise reduction). K=6 centroids picked by IS Sharpe per Ward cluster on correlation distance; equal-weight with fixed gross amplification to bypass the 1/sigma underweighting trap of cov-based optimizers."""
from __future__ import annotations
import argparse
import numpy as np
import pandas as pd
import scipy.cluster.hierarchy as sch
import scipy.spatial.distance as ssd

from intraday.composites._runner import build_and_backtest
from intraday.composites._optim_helpers import (
    member_signs_ic,
    apply_signs,
    select_all_alphas,
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_108"
COMPOSITION_NOTE = "ward_centroid_k6_yearstable_dd20_eqw_gross8x"

RUN_ID = "run_2026_05_c"
N_CLUSTERS = 6
DD_THRESHOLD = -0.20
MIN_SHARPE = 0.30
GROSS_MULTIPLIER = 8.0


def _is_sharpe(r: pd.Series) -> float:
    r = r.dropna()
    if len(r) < 30:
        return -np.inf
    s = float(r.std())
    if s <= 0.0:
        return -np.inf
    return float(r.mean() / s)


def _max_drawdown(r: pd.Series) -> float:
    r = r.fillna(0.0)
    if len(r) == 0:
        return 0.0
    cum = (1.0 + r).cumprod()
    peak = cum.cummax()
    dd = (cum / peak) - 1.0
    return float(dd.min())


def _per_year_stable(r: pd.Series) -> bool:
    idx = r.index
    if not isinstance(idx, pd.DatetimeIndex):
        try:
            idx = pd.to_datetime(idx, errors="coerce")
            r = pd.Series(r.values, index=idx)
        except Exception:
            return True
    if r.index.isna().all():
        return True
    grp = r.groupby(r.index.year)
    for _y, sub in grp:
        if len(sub) < 30:
            continue
        s = float(sub.std())
        if s <= 0.0:
            return False
        if float(sub.mean()) / s <= 0.0:
            return False
    return True


def _filter_pool(R: pd.DataFrame, dd_thr: float, sh_thr: float) -> list[str]:
    keep: list[str] = []
    for col in R.columns:
        r = R[col].dropna()
        if len(r) < 60:
            continue
        if _is_sharpe(r) < sh_thr:
            continue
        if _max_drawdown(r) < dd_thr:
            continue
        if not _per_year_stable(r):
            continue
        keep.append(col)
    return keep


def _ward_centroids(R: pd.DataFrame, k: int) -> list[str]:
    cols = list(R.columns)
    if len(cols) <= k:
        return cols
    corr = R.corr().fillna(0.0).values
    np.fill_diagonal(corr, 1.0)
    dist = np.sqrt(np.clip(0.5 * (1.0 - corr), 0.0, 1.0))
    dist = 0.5 * (dist + dist.T)
    np.fill_diagonal(dist, 0.0)
    try:
        cond = ssd.squareform(dist, checks=False)
        Z = sch.linkage(cond, method="ward")
        labels = sch.fcluster(Z, t=k, criterion="maxclust")
    except Exception:
        scores = {c: _is_sharpe(R[c]) for c in cols}
        return sorted(scores, key=lambda c: scores[c], reverse=True)[:k]
    sharpes = {c: _is_sharpe(R[c]) for c in cols}
    out: list[str] = []
    for lbl in np.unique(labels):
        members = [c for c, l in zip(cols, labels) if l == lbl]
        if not members:
            continue
        best = max(members, key=lambda c: sharpes.get(c, -np.inf))
        out.append(best)
    return out


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    ids = select_all_alphas(RUN_ID)
    if not ids:
        return []
    signs = member_signs_ic(RUN_ID, ids)
    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    if R is None or R.empty or R.shape[1] < 2:
        return [] if (R is None or R.empty) else list(R.columns)

    kept = _filter_pool(R, DD_THRESHOLD, MIN_SHARPE)
    if len(kept) < 2:
        kept = _filter_pool(R, -0.30, 0.20)
    if len(kept) < 2:
        scores = {c: _is_sharpe(R[c]) for c in R.columns}
        kept = sorted(scores, key=lambda c: scores[c], reverse=True)[:8]

    R_kept = R[kept]
    K = min(N_CLUSTERS, len(kept))
    if K < 2:
        return kept[:K] if kept else []
    centroids = _ward_centroids(R_kept, K)
    if len(centroids) < 2:
        scores = {c: _is_sharpe(R_kept[c]) for c in R_kept.columns}
        centroids = sorted(scores, key=lambda c: scores[c], reverse=True)[:K]
    return centroids


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    if not member_ids:
        return {}
    signs = member_signs_ic(RUN_ID, member_ids)
    coef = {a: 1.0 for a in member_ids}
    coef = apply_signs(coef, signs)
    coef = normalize_coefficients(coef, "l1")
    coef = {a: float(v) * GROSS_MULTIPLIER for a, v in coef.items()}
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
