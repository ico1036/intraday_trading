Looking at the brief carefully, I need to try a **cov-FREE** method (the user's flagged blocker). The cluster-centroid approach with equal weighting is explicitly recommended and hasn't been tried. Method: Ward hierarchical clustering on IS-return correlation distance → one highest-IS-Sharpe representative per cluster → equal weight → rescale gross to ≈0.7.

Regime-aware ingredients I'll add per the recent-failures section:
- Per-year IS Sharpe stability filter (positive Sharpe in every IS sub-year)
- Max IS drawdown < 25%
- Sign-alignment via `member_signs_ic`
- Concentration: K=6 clusters → 6 members (sweet spot per leaderboard)

This avoids the `Σ⁻¹·μ` 1/σ-weighting trap that drove mean_row_l1 to 0.05 in prior attempts.

```python COMPOSITE_FILE
"""Ward cluster-centroid composite (cov-free): hierarchical clustering on IS-return
correlation distance (Lopez de Prado clustering, simplified representative selection),
year-stability + drawdown filters, equal-weighted across one top-IS-Sharpe rep per
cluster, then gross-exposure rescaled to ~0.7 to bypass the 1/σ underweighting trap.
"""
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
    select_is_submittable,
    select_all_alphas,
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_101"
COMPOSITION_NOTE = "ward_centroid_k6_yearstable_dd25_eq_gross070"

RUN_ID = "run_2026_05_c"
N_CLUSTERS = 6
DD_MAX = 0.25
MIN_OBS_PER_ALPHA = 60
MIN_OBS_PER_YEAR = 20
TARGET_GROSS = 0.70


def _annualized_sharpe(s: pd.Series) -> float:
    sd = s.std()
    if sd == 0 or not np.isfinite(sd):
        return 0.0
    return float(s.mean() / sd * np.sqrt(252))


def _max_drawdown(returns: pd.Series) -> float:
    eq = (1.0 + returns.fillna(0.0)).cumprod()
    cummax = eq.cummax().replace(0, np.nan)
    dd = (eq - cummax) / cummax
    mn = dd.min()
    return float(abs(mn)) if np.isfinite(mn) else 1.0


def _year_stable(returns: pd.Series) -> bool:
    idx = returns.index
    if not isinstance(idx, pd.DatetimeIndex):
        try:
            idx = pd.to_datetime(idx)
        except Exception:
            return True
    years = idx.year
    uniq = np.unique(years)
    if len(uniq) < 2:
        return True
    for y in uniq:
        sub = returns[years == y].dropna()
        if len(sub) < MIN_OBS_PER_YEAR:
            continue
        if _annualized_sharpe(sub) <= 0:
            return False
    return True


def _candidate_ids(alpha_index: pd.DataFrame) -> list[str]:
    try:
        ids = list(select_is_submittable(RUN_ID))
    except Exception:
        ids = []
    if len(ids) < N_CLUSTERS * 2:
        try:
            ids = list(select_all_alphas(RUN_ID))
        except Exception:
            pass
    if (not ids) and alpha_index is not None and "alpha_id" in getattr(alpha_index, "columns", []):
        ids = list(alpha_index["alpha_id"].astype(str))
    # de-dup while preserving order
    seen: set[str] = set()
    out: list[str] = []
    for a in ids:
        sa = str(a)
        if sa not in seen:
            seen.add(sa)
            out.append(sa)
    return out


def _filter_pool(R: pd.DataFrame, strict: bool) -> tuple[list[str], dict[str, float]]:
    keep: list[str] = []
    sharpe_map: dict[str, float] = {}
    for c in R.columns:
        s = R[c].dropna()
        if len(s) < MIN_OBS_PER_ALPHA:
            continue
        sh = _annualized_sharpe(s)
        if sh <= 0:
            continue
        if strict:
            if _max_drawdown(s) > DD_MAX:
                continue
            if not _year_stable(s):
                continue
        sharpe_map[c] = sh
        keep.append(c)
    return keep, sharpe_map


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    cand = _candidate_ids(alpha_index)
    if len(cand) < 2:
        return cand

    try:
        signs = member_signs_ic(RUN_ID, cand)
    except Exception:
        signs = {a: 1 for a in cand}

    try:
        R = load_member_is_returns(RUN_ID, cand, signs=signs)
    except Exception:
        R = None

    if R is None or R.empty or R.shape[1] < 2:
        if alpha_index is not None and "is_sharpe" in getattr(alpha_index, "columns", []):
            top = alpha_index.sort_values("is_sharpe", ascending=False)["alpha_id"].astype(str)
            return list(top.head(max(2, N_CLUSTERS)))
        return cand[: max(2, N_CLUSTERS)]

    keep, sharpe_map = _filter_pool(R, strict=True)
    if len(keep) < N_CLUSTERS:
        keep, sharpe_map = _filter_pool(R, strict=False)
    if len(keep) < 2:
        # last-ditch: highest-vol-adjusted from raw R
        for c in R.columns:
            s = R[c].dropna()
            if len(s) >= 30:
                sharpe_map[c] = _annualized_sharpe(s)
                keep.append(c)
        if len(keep) < 2:
            return cand[: max(2, N_CLUSTERS)]

    Rk = R[keep].dropna(how="any")
    if Rk.shape[0] < 30 or Rk.shape[1] < 2:
        Rk = R[keep].fillna(0.0)

    n = Rk.shape[1]
    if n <= N_CLUSTERS:
        # not enough breadth to cluster — just return what we have, capped at 8
        ranked = sorted(Rk.columns, key=lambda a: sharpe_map.get(a, 0.0), reverse=True)
        return ranked[: max(2, min(n, 8))]

    corr = Rk.corr().fillna(0.0).values
    np.fill_diagonal(corr, 1.0)
    dist = np.sqrt(np.clip(0.5 * (1.0 - corr), 0.0, 1.0))
    np.fill_diagonal(dist, 0.0)
    # enforce symmetry for squareform
    dist = 0.5 * (dist + dist.T)
    try:
        cond = ssd.squareform(dist, checks=False)
        Z = sch.linkage(cond, method="ward")
        k = min(N_CLUSTERS, n)
        labels = sch.fcluster(Z, t=k, criterion="maxclust")
    except Exception:
        ranked = sorted(Rk.columns, key=lambda a: sharpe_map.get(a, 0.0), reverse=True)
        return ranked[: max(2, N_CLUSTERS)]

    cols = list(Rk.columns)
    reps: list[str] = []
    for cl in np.unique(labels):
        members_in = [cols[i] for i in range(n) if labels[i] == cl]
        if not members_in:
            continue
        best = max(members_in, key=lambda a: sharpe_map.get(a, 0.0))
        reps.append(best)

    if len(reps) < 2:
        ranked = sorted(Rk.columns, key=lambda a: sharpe_map.get(a, 0.0), reverse=True)
        return ranked[: max(2, N_CLUSTERS)]
    return reps


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    if not member_ids:
        return {}

    try:
        signs = member_signs_ic(RUN_ID, member_ids)
    except Exception:
        signs = {a: 1 for a in member_ids}

    # Equal-weighted, sign-aligned
    coef: dict[str, float] = {a: 1.0 for a in member_ids}
    coef = apply_signs(coef, signs)
    coef = normalize_coefficients(coef, "l1")   # Σ|c| = 1

    # Estimate implied gross from per-member daily vol of return stream and rescale
    est_gross = 0.0
    try:
        R = load_member_is_returns(RUN_ID, member_ids, signs=signs)
        if R is not None and not R.empty:
            sigma = {c: float(R[c].std()) for c in R.columns}
            est_gross = sum(abs(coef.get(k, 0.0)) * sigma.get(k, 0.0) for k in coef)
    except Exception:
        est_gross = 0.0

    if est_gross > 1e-6:
        scale = TARGET_GROSS / est_gross
        # clamp to a reasonable band — avoid runaway leverage on vanishingly-small sigma
        scale = float(np.clip(scale, 1.0, 60.0))
    else:
        # No vol info — apply the 10x rule-of-thumb from prior empirical evidence
        scale = 10.0

    coef = {k: v * scale for k, v in coef.items()}
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
