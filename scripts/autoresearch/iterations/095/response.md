Reasoning before the code block:

**Method:** Ward hierarchical clustering on IS-correlation distance + per-year Sharpe stability filter + cluster-centroid (best-IS-Sharpe) equal-weight composition. **Cov-free** — no matrix inversion, no Σ⁻¹·μ underweighting trap.

**Why this iteration:**
- Spec explicitly calls out the gross-exposure ceiling as the dominant blocker: cov-based methods produce w ∝ Σ⁻¹·μ which is 1/σ-weighted and lands at mean row L1 ≈ 0.05. This iteration bypasses cov inversion entirely.
- User's "Cluster centroid then equal-weight" option (cov-free menu) hasn't been tried directly; auto_013 used cluster-*median* on IR-stability, mine uses cluster-*best-IS-Sharpe* on per-year Sharpe stability — different representative rule, different metric.
- Concentrates to K=6 (within the empirically-favored n∈[5,8] band).
- Per-year Sharpe-stability filter (positive Sharpe in every IS sub-year 2022/2023/2024) is the regime-shift defense the spec recommends.
- Correlation dedup at ρ=0.85 (favored band).
- Sign-aligned via `member_signs_ic` so deployable sign is what enters the panel.

**Gross-exposure plan:** raw coefficients of magnitude 1.0 (signed) — no L1 normalization. With 6 signed cluster-best members whose individual gross is each ~0.2-0.4, the upper-bound row-L1 is ~1.5-2.0, the runner's row-L1 clamp pulls us to mean ≈ 0.7-0.9 (in the target band [0.3, 0.9]). Skipping `normalize_coefficients` also avoids the dict/array bug that ERRORED iter 001 and iter 004.

**Citation:** Raffinot (2018) HERC family — Ward bottom-up clustering on correlation distance — but using cluster-centroid (best-IS-Sharpe) selection rather than HERC's intra-cluster risk parity, since the latter requires cov inversion that the user has flagged as the failure mode.

```python COMPOSITE_FILE
"""Ward hierarchical clustering on IS-correlation distance with per-year IS-Sharpe
stability filter; cluster-centroid (best-IS-Sharpe representative) equal-weight
combination, sign-aligned via IC, cov-free (Raffinot 2018 HERC family without
intra-cluster risk parity — bypasses the Sigma-inverse 1/sigma underweighting trap)."""
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
)

COMPOSITE_ID = "auto_095"
COMPOSITION_NOTE = "ward_corrdist_yearstable_centroid_eq_signs_gross_hi"
RUN_ID = "run_2026_05_c"
K_CLUSTERS = 6
RHO_DEDUP = 0.85
MIN_BARS_PER_YEAR = 20
COEF_MAGNITUDE = 1.0


def _is_sharpe_map(R: pd.DataFrame) -> dict[str, float]:
    out: dict[str, float] = {}
    for col in R.columns:
        s = R[col].fillna(0.0)
        sd = float(s.std())
        out[col] = float(s.mean()) / sd * np.sqrt(252.0) if sd > 0 else 0.0
    return out


def _year_stable_set(R: pd.DataFrame) -> list[str]:
    if R.empty:
        return []
    idx = pd.to_datetime(R.index)
    years = sorted(set(idx.year))
    if len(years) < 2:
        return list(R.columns)
    keep: list[str] = []
    for col in R.columns:
        s = R[col].fillna(0.0)
        ok_years = 0
        bad = False
        for y in years:
            mask = (idx.year == y)
            sub = s[mask]
            if len(sub) < MIN_BARS_PER_YEAR:
                continue
            mu = float(sub.mean())
            sd = float(sub.std())
            if sd <= 0.0 or mu <= 0.0:
                bad = True
                break
            ok_years += 1
        if (not bad) and ok_years >= max(1, len(years) - 1):
            keep.append(col)
    return keep


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    ids = select_is_submittable(RUN_ID)
    if not ids or len(ids) < K_CLUSTERS * 2:
        ids = select_all_alphas(RUN_ID)
    if len(ids) < 2:
        return list(ids)

    signs = member_signs_ic(RUN_ID, ids)
    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    if R is None or R.shape[1] < 2:
        return list(R.columns) if R is not None else list(ids)[:K_CLUSTERS]

    sharpe_map = _is_sharpe_map(R)

    stable = _year_stable_set(R)
    if len(stable) < K_CLUSTERS:
        stable = sorted(R.columns, key=lambda c: sharpe_map.get(c, 0.0), reverse=True)[: max(K_CLUSTERS * 2, 2)]
    R_stable = R[stable]

    try:
        kept = correlation_dedup(R_stable, RHO_DEDUP, keep_metric=sharpe_map)
    except Exception:
        kept = list(R_stable.columns)
    kept = [k for k in kept if k in R_stable.columns]
    if len(kept) < 2:
        return sorted(R.columns, key=lambda c: sharpe_map.get(c, 0.0), reverse=True)[: max(K_CLUSTERS, 2)]

    R_kept = R_stable[kept]
    n = R_kept.shape[1]
    if n <= K_CLUSTERS:
        return list(R_kept.columns)

    corr = R_kept.corr().fillna(0.0).values
    np.fill_diagonal(corr, 1.0)
    corr = np.clip(corr, -1.0, 1.0)
    dist = np.sqrt(np.clip(0.5 * (1.0 - corr), 0.0, 1.0))
    np.fill_diagonal(dist, 0.0)
    cond = ssd.squareform(dist, checks=False)

    try:
        Z = sch.linkage(cond, method="ward")
        labels = sch.fcluster(Z, t=K_CLUSTERS, criterion="maxclust")
    except Exception:
        return sorted(R_kept.columns, key=lambda c: sharpe_map.get(c, 0.0), reverse=True)[:K_CLUSTERS]

    selected: list[str] = []
    cols = list(R_kept.columns)
    for k in range(1, int(labels.max()) + 1):
        members_k = [cols[i] for i in range(n) if labels[i] == k]
        if not members_k:
            continue
        best = max(members_k, key=lambda c: sharpe_map.get(c, 0.0))
        selected.append(best)

    if len(selected) < 2:
        return sorted(R.columns, key=lambda c: sharpe_map.get(c, 0.0), reverse=True)[: max(K_CLUSTERS, 2)]
    return selected


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    signs = member_signs_ic(RUN_ID, member_ids)
    coef: dict[str, float] = {m: COEF_MAGNITUDE for m in member_ids}
    coef = apply_signs(coef, signs)
    for m in member_ids:
        if m not in coef:
            coef[m] = COEF_MAGNITUDE
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
