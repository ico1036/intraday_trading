Looking at this iteration carefully:

**Strategy choice for iter 78:**
- Recent feedback: cov-free methods bypass the 1/σ-weighting trap; Gram-Schmidt failed 9/9 (skip); cluster-centroid + equal-weight never attempted.
- Winner pattern from leaderboard: n∈[5,8], per-year IS stability filter, drawdown discipline.
- Mandate: mean row L1 in [0.5, 0.9] — must post-scale coefficients ~10×.

**Mechanism (cited in docstring):**
Ward hierarchical clustering on `sqrt(0.5(1−ρ))` distance (Lopez de Prado 2016 HRP clustering step) — but instead of using the linkage for recursive risk allocation, I pick the **single highest-IS-Sharpe representative per cluster** (centroid selection) and equal-weight across K=6 clusters. This is genuinely cov-free: no inversion, no shrinkage. Layered with two regime-aware pre-filters: (a) per-year IS positivity (Sharpe > 0 in every calendar sub-year of IS) and (b) max IS drawdown < 20%. Final coefficients post-scaled ~12× so the runner's row-L1 clamp engages and mean gross sits in [0.5, 0.9].

This is genuinely fresh territory: none of the 22+ tried autos used cluster-rep + equal-weight (auto_002 was NCO-style cluster minvar; auto_009 was HRP recursive-bisection risk parity; auto_013 was cluster-median with IR weights). This one is cluster-rep + 1/K + aggressive gross rescaling.

```python COMPOSITE_FILE
"""Ward-cluster centroid equal-weight with per-year IS stability and DD<20% gates;
cov-free composition adapted from the HRP clustering step (Lopez de Prado 2016)
where the linkage selects ONE high-Sharpe representative per cluster instead of
recursive bisection risk allocation. Coefficients post-scaled to engage the
runner's row-L1 clamp and lift mean gross into the [0.5, 0.9] band."""
from __future__ import annotations
import argparse
import math
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

COMPOSITE_ID = "auto_078"
COMPOSITION_NOTE = "ward_cluster_centroid_yearstable_dd20_k6_gross12x"

RUN_ID = "run_2026_05_c"
N_CLUSTERS = 6
DD_THRESHOLD = 0.20
COEF_SCALE = 12.0


def _per_year_positive(r: pd.Series) -> bool:
    s = r.dropna()
    if s.empty:
        return False
    try:
        years = s.index.year
    except AttributeError:
        return False
    g = s.groupby(years).sum()
    return bool((g > 0).all()) and len(g) >= 2


def _max_drawdown(r: pd.Series) -> float:
    s = r.dropna()
    if s.empty:
        return 1.0
    eq = (1.0 + s).cumprod()
    peak = eq.cummax()
    dd = eq / peak - 1.0
    val = dd.min()
    if not np.isfinite(val):
        return 1.0
    return float(-val)


def _sharpe(r: pd.Series) -> float:
    s = r.dropna()
    if s.empty:
        return 0.0
    sd = float(s.std(ddof=0))
    if sd <= 0 or not np.isfinite(sd):
        return 0.0
    return float(s.mean() / sd) * math.sqrt(252.0)


def _safe_load_returns(ids: list[str]):
    signs = member_signs_ic(RUN_ID, ids)
    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    return R, signs


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    ids = select_is_submittable(RUN_ID)
    if not ids or len(ids) < 8:
        ids = select_all_alphas(RUN_ID)
    if not ids:
        return []

    R, _ = _safe_load_returns(ids)
    cols = list(R.columns)
    if len(cols) < 2:
        return cols

    sharpe_full = {c: _sharpe(R[c]) for c in cols}

    # Tier 1: per-year positive AND DD < threshold AND Sharpe > 0
    tier1 = [
        c for c in cols
        if sharpe_full[c] > 0
        and _per_year_positive(R[c])
        and _max_drawdown(R[c]) < DD_THRESHOLD
    ]

    # Tier 2: per-year positive (relaxed DD)
    tier2 = [
        c for c in cols
        if sharpe_full[c] > 0 and _per_year_positive(R[c])
    ]

    if len(tier1) >= N_CLUSTERS + 1:
        keep = tier1
    elif len(tier2) >= N_CLUSTERS + 1:
        keep = tier2
    else:
        keep = sorted(cols, key=lambda c: sharpe_full[c], reverse=True)[:12]

    if len(keep) < 2:
        return sorted(cols, key=lambda c: sharpe_full[c], reverse=True)[:max(2, min(6, len(cols)))]

    sharpe_keep = {c: sharpe_full[c] for c in keep}

    # Ward clustering on correlation distance
    R_keep = R[keep].fillna(0.0)
    try:
        corr = R_keep.corr().fillna(0.0).values
        np.fill_diagonal(corr, 1.0)
        dist_mat = np.sqrt(np.clip(0.5 * (1.0 - corr), 0.0, 1.0))
        np.fill_diagonal(dist_mat, 0.0)
        # symmetrize
        dist_mat = 0.5 * (dist_mat + dist_mat.T)
        condensed = ssd.squareform(dist_mat, checks=False)
        Z = sch.linkage(condensed, method="ward")
        k = min(N_CLUSTERS, len(keep))
        labels = sch.fcluster(Z, t=k, criterion="maxclust")
    except Exception:
        # fallback: top-K by Sharpe
        return sorted(keep, key=lambda c: sharpe_keep[c], reverse=True)[:N_CLUSTERS]

    reps = []
    for cl in np.unique(labels):
        members = [keep[i] for i, lab in enumerate(labels) if lab == cl]
        if not members:
            continue
        rep = max(members, key=lambda c: sharpe_keep.get(c, 0.0))
        reps.append(rep)

    # Final safety: ensure at least 2 members
    if len(reps) < 2:
        reps = sorted(keep, key=lambda c: sharpe_keep[c], reverse=True)[:max(2, min(6, len(keep)))]

    return reps


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    if not member_ids:
        return {}
    if len(member_ids) == 1:
        return {member_ids[0]: 1.0}

    signs = member_signs_ic(RUN_ID, member_ids)
    R = load_member_is_returns(RUN_ID, member_ids, signs=signs)
    loaded = [m for m in member_ids if m in R.columns]
    if len(loaded) < 2:
        # equal weight fallback
        n = max(1, len(member_ids))
        return {m: float(COEF_SCALE) / n for m in member_ids}

    # Equal weight over loaded members
    base = {m: 1.0 for m in loaded}
    base = normalize_coefficients(base, "l1")  # Σ|c| = 1
    coef = {m: float(base[m]) * COEF_SCALE for m in loaded}

    # Apply IC-aligned signs
    coef = apply_signs(coef, signs)

    # Ensure all requested ids are covered (0 for unloaded)
    out = {m: 0.0 for m in member_ids}
    for m, v in coef.items():
        out[m] = float(v) if np.isfinite(v) else 0.0
    return out


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
