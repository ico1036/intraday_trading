I'll go with a **Ward-cluster centroid + equal-weight** composite (cov-FREE, explicitly user-suggested, never tried). Mechanism: cluster IS-return correlations into K=6 groups via Ward linkage on `sqrt(0.5(1−ρ))`, pick the highest-IS-Sharpe representative from each cluster, then equal-weight at native scale (coef=1.0 each) to let the runner's row-L1 clamp do the budgeting. Universe is pre-filtered by per-year IS-Sharpe stability (positive Sharpe in every IS sub-year) and IS max-drawdown < 25% — the two regime-robustness levers the recent feedback flagged as top-of-leaderboard ingredients.

Citation: Lopez de Prado 2019, *Machine Learning for Asset Managers* ch.4 (cluster-representative portfolios); Raffinot 2018 for the Ward-on-correlation-distance ingredient. This is cov-free, avoids the `Σ⁻¹·μ → 1/σ` weighting trap, and uses native member leverage rather than the min-var dilution.

```python COMPOSITE_FILE
"""Ward-cluster centroid composite: hierarchical clustering on IS-return
correlation distance sqrt(0.5*(1-rho)) (Lopez de Prado 2019, MLAM ch.4 --
cluster-representative portfolios; Raffinot 2018), K=6 clusters,
year-stable + drawdown-disciplined universe, equal-weight at native
scale the highest-IS-Sharpe representative from each cluster.
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
    correlation_dedup,
    member_signs_ic,
    select_is_submittable,
    select_all_alphas,
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_117"
COMPOSITION_NOTE = "ward_cluster_centroid_k6_yearstable_dd25_native"

RUN_ID = "run_2026_05_c"
N_CLUSTERS = 6
MAX_DD = 0.25
DEDUP_RHO = 0.92


def _max_drawdown(equity: np.ndarray) -> float:
    if equity.size < 2:
        return 0.0
    peak = np.maximum.accumulate(equity)
    safe_peak = np.where(peak == 0, 1.0, peak)
    dd = (equity - peak) / safe_peak
    return float(-dd.min())


def _year_stable(returns: pd.Series) -> bool:
    if len(returns) < 30:
        return False
    idx = returns.index
    if not isinstance(idx, pd.DatetimeIndex):
        try:
            idx = pd.to_datetime(idx)
        except Exception:
            return True
    years = pd.Series(idx.year, index=returns.index)
    for _, sub in returns.groupby(years):
        if len(sub) < 20:
            continue
        sd = float(sub.std())
        if sd == 0.0 or not np.isfinite(sd):
            return False
        sh = (float(sub.mean()) / sd) * math.sqrt(252)
        if sh <= 0.0:
            return False
    return True


def _candidate_pool(run_id: str):
    ids = select_is_submittable(run_id)
    if len(ids) < N_CLUSTERS * 2:
        ids = select_all_alphas(run_id)
    signs = member_signs_ic(run_id, ids)
    R = load_member_is_returns(run_id, ids, signs=signs)
    R = R.dropna(axis=1, how="all").fillna(0.0)
    live_cols = [c for c in R.columns if float(R[c].std()) > 0.0]
    R = R[live_cols]

    kept = []
    for a in R.columns:
        r = R[a]
        if not _year_stable(r):
            continue
        eq = (1.0 + r.values).cumprod()
        if _max_drawdown(eq) > MAX_DD:
            continue
        kept.append(a)

    if len(kept) < N_CLUSTERS:
        kept = []
        for a in R.columns:
            r = R[a]
            eq = (1.0 + r.values).cumprod()
            if _max_drawdown(eq) > MAX_DD:
                continue
            kept.append(a)

    if len(kept) < N_CLUSTERS:
        kept = list(R.columns)

    sharpe = {}
    for a in kept:
        sd = float(R[a].std())
        sharpe[a] = float((R[a].mean() / sd) * math.sqrt(252)) if sd > 0.0 else 0.0

    R_kept = R[kept]
    try:
        kept = correlation_dedup(R_kept, DEDUP_RHO, keep_metric=sharpe)
    except Exception:
        pass
    return kept, R[kept], sharpe


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    kept, R, sharpe = _candidate_pool(RUN_ID)
    if len(kept) <= N_CLUSTERS:
        return kept

    corr = R.corr().fillna(0.0).values
    corr = np.clip(corr, -1.0, 1.0)
    np.fill_diagonal(corr, 1.0)
    dist_mat = np.sqrt(np.clip(0.5 * (1.0 - corr), 0.0, 1.0))
    dist_mat = 0.5 * (dist_mat + dist_mat.T)
    np.fill_diagonal(dist_mat, 0.0)

    try:
        condensed = ssd.squareform(dist_mat, checks=False)
        Z = sch.linkage(condensed, method="ward")
        labels = sch.fcluster(Z, t=N_CLUSTERS, criterion="maxclust")
    except Exception:
        ranked = sorted(kept, key=lambda a: sharpe.get(a, 0.0), reverse=True)
        return ranked[:N_CLUSTERS]

    chosen = []
    for c in np.unique(labels):
        members_c = [kept[i] for i in range(len(kept)) if labels[i] == c]
        if not members_c:
            continue
        best = max(members_c, key=lambda a: sharpe.get(a, 0.0))
        chosen.append(best)

    if len(chosen) < 2:
        ranked = sorted(kept, key=lambda a: sharpe.get(a, 0.0), reverse=True)
        return ranked[:N_CLUSTERS]
    return chosen


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    if not member_ids:
        return {}
    coef = {a: 1.0 for a in member_ids}
    coef = normalize_coefficients(coef, "l1")
    K = max(len(coef), 1)
    coef = {a: float(v) * float(K) for a, v in coef.items()}
    for m in member_ids:
        coef.setdefault(m, 0.0)
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
