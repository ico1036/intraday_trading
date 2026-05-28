Reasoning before code:

The user's spec frames iter 76 with a clear empirical signal: cov-based optimizers (tangency / min-var / Neumann-suppressed MinVol) keep producing mean row L1 ≈ 0.05–0.25, leaving 75–95% of the risk budget on the table. The system prompt explicitly recommends **cov-FREE** methods this iteration: cluster-centroid equal-weight, correlation-rank × Sharpe-rank composite, or pure 1/N over top-K. Gram-Schmidt is explicitly blacklisted (failed 9/9). The leaderboard pattern is n∈[5,8], per-year IS Sharpe stability, DD<20–25%, dedup ρ∈[0.80,0.90].

I'll combine three regime-robust ingredients into a single cov-FREE recipe:

1. **Year-stability filter** (positive Sharpe in every IS sub-year ≥20 obs) — proven robust against the 2024-04 regime shift between IS (LUNA→FTX→2023 chop→pre-halving) and OS (post-halving + 2025 bull/correction).
2. **Drawdown discipline** (max IS DD ≤ 22%) — kills lucky-tail-event alphas.
3. **Ward-linkage clustering on correlation-distance** (Ward 1963 minimum-variance hierarchical clustering, `d_ij = sqrt(0.5·(1−ρ_ij))`) cut into K=6 clusters, pick the highest-IS-Sharpe representative per cluster.

This is the "cluster centroid then equal-weight" recipe explicitly recommended in the spec, with two regime-aware pre-filters layered on top. No matrix inversion, no Σ⁻¹·μ ⇒ no 1/σ weighting trap.

Final layer: equal-weight the 6 centroids, sign-align via `member_signs_ic`, normalize to Σ|c|=1, then **scale all coefficients by 8×** so the realized mean row L1 sits in the 0.5–0.8 sweet spot per the explicit user instruction.

Citation: Ward, J. H. Jr. (1963), *Hierarchical Grouping to Optimize an Objective Function*. JASA — the basis of the cluster-centroid construction. Distance metric follows Mantegna (1999) / López de Prado (2016, HRP) convention.

Idea family not in the tried-list (no prior iter used Ward centroid + year-stability + DD + cov-free equal-weight).

```python COMPOSITE_FILE
"""Ward-linkage cluster-centroid equal-weight composite (Ward 1963).

Cov-FREE allocation: skips Sigma^-1 mu and the 1/sigma weighting trap that
suppressed mean row L1 to <0.20 in prior tangency/MinVol attempts. Picks one
representative per Ward cluster on the Mantegna correlation-distance
d_ij = sqrt(0.5*(1 - rho_ij)), conditioned on regime-robust filters:
per-year IS Sharpe positivity and max IS drawdown <= 22%. Equal-weight the
K cluster centroids, sign-align via IC, then up-scale coefficients to push
realized mean row L1 toward the 0.5-0.8 risk-budget sweet spot.
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
    select_all_alphas,
    load_member_is_returns,
    member_signs_ic,
    apply_signs,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_076"
COMPOSITION_NOTE = "ward_centroid_yearstable_dd22_k6_eqweight_scale8x"

RUN_ID = "run_2026_05_c"
K_CLUSTERS = 6
DD_MAX = 0.22
COEF_SCALE = 8.0
MIN_YEAR_OBS = 20


def _annual_sharpe(r: pd.Series) -> float:
    s = r.dropna()
    if s.empty:
        return 0.0
    mu = float(s.mean())
    sd = float(s.std())
    if sd <= 0.0 or not np.isfinite(sd):
        return 0.0
    return mu / sd * float(np.sqrt(252.0))


def _max_drawdown(r: pd.Series) -> float:
    s = r.dropna()
    if s.empty:
        return 1.0
    eq = (1.0 + s).cumprod()
    peak = eq.cummax()
    dd = eq / peak - 1.0
    val = float(-dd.min())
    if not np.isfinite(val):
        return 1.0
    return val


def _year_stable_positive(r: pd.Series) -> bool:
    s = r.dropna()
    if s.empty:
        return False
    idx = s.index
    if not isinstance(idx, pd.DatetimeIndex):
        return float(s.mean()) > 0.0
    grouped = s.groupby(idx.year)
    seen = 0
    for _, g in grouped:
        if len(g) < MIN_YEAR_OBS:
            continue
        if float(g.mean()) <= 0.0:
            return False
        seen += 1
    return seen >= 1


def _safe_select_pool() -> list[str]:
    try:
        ids = select_is_submittable(RUN_ID)
    except Exception:
        ids = []
    if len(ids) < 2 * K_CLUSTERS:
        try:
            ids = list(set(ids).union(set(select_all_alphas(RUN_ID))))
        except Exception:
            pass
    return list(ids)


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    ids = _safe_select_pool()
    if len(ids) < 2:
        return ids

    try:
        signs = member_signs_ic(RUN_ID, ids)
    except Exception:
        signs = {a: 1 for a in ids}

    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    R = R.dropna(how="all", axis=1)
    cols = list(R.columns)
    if len(cols) < 2:
        return cols[: max(2, len(cols))]

    sharpe_map: dict[str, float] = {c: _annual_sharpe(R[c]) for c in cols}
    dd_map: dict[str, float] = {c: _max_drawdown(R[c]) for c in cols}
    ystab_map: dict[str, bool] = {c: _year_stable_positive(R[c]) for c in cols}

    kept = [
        c for c in cols
        if sharpe_map[c] > 0.0 and dd_map[c] <= DD_MAX and ystab_map[c]
    ]
    if len(kept) < K_CLUSTERS + 2:
        kept = [c for c in cols if sharpe_map[c] > 0.0 and dd_map[c] <= DD_MAX]
    if len(kept) < K_CLUSTERS + 2:
        kept = [c for c in cols if sharpe_map[c] > 0.0]
    if len(kept) < 2:
        ranked = sorted(cols, key=lambda a: sharpe_map[a], reverse=True)
        return ranked[: min(K_CLUSTERS, max(2, len(ranked)))]

    # cap pool size before clustering for numerical stability
    if len(kept) > 80:
        kept = sorted(kept, key=lambda a: sharpe_map[a], reverse=True)[:80]

    R_keep = R[kept].fillna(0.0)
    corr = R_keep.corr().fillna(0.0).values.astype(float)
    n = corr.shape[0]
    if n < 2:
        return kept[: min(K_CLUSTERS, n)]
    np.fill_diagonal(corr, 1.0)
    corr = np.clip(corr, -1.0, 1.0)
    dmat = np.sqrt(np.clip(0.5 * (1.0 - corr), 0.0, 1.0))
    # symmetrize numerically
    dmat = 0.5 * (dmat + dmat.T)
    np.fill_diagonal(dmat, 0.0)

    try:
        cond = ssd.squareform(dmat, checks=False)
        k = min(K_CLUSTERS, max(2, n // 2))
        Z = sch.linkage(cond, method="ward")
        labels = sch.fcluster(Z, t=k, criterion="maxclust")
    except Exception:
        return sorted(kept, key=lambda a: sharpe_map[a], reverse=True)[:K_CLUSTERS]

    chosen: list[str] = []
    for cl in np.unique(labels):
        members = [kept[i] for i, lbl in enumerate(labels) if lbl == cl]
        members.sort(key=lambda a: sharpe_map.get(a, 0.0), reverse=True)
        if members:
            chosen.append(members[0])

    if len(chosen) < 2:
        chosen = sorted(kept, key=lambda a: sharpe_map[a], reverse=True)[:K_CLUSTERS]
    # de-dup just in case
    seen_set: set[str] = set()
    unique_chosen: list[str] = []
    for a in chosen:
        if a not in seen_set:
            seen_set.add(a)
            unique_chosen.append(a)
    return unique_chosen


def member_weights(
    member_ids: list[str], alpha_index: pd.DataFrame
) -> dict[str, float]:
    if not member_ids:
        return {}

    coef: dict[str, float] = {a: 1.0 for a in member_ids}
    try:
        signs = member_signs_ic(RUN_ID, member_ids)
    except Exception:
        signs = {a: 1 for a in member_ids}
    coef = apply_signs(coef, signs)
    coef = normalize_coefficients(coef, scheme="l1")
    # uplift to escape the sub-0.20 gross-exposure ceiling that crushed
    # all prior cov-based attempts; runner row-L1 clamp absorbs overshoot.
    coef = {a: float(v) * COEF_SCALE for a, v in coef.items()}
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
