"""Ward-clustered centroid + IS-year-stable + DD-disciplined equal-weight composite.

Method: hierarchical Ward clustering on Lopez-de-Prado (2016) correlation distance
d_ij = sqrt((1 - rho_ij)/2) over IS returns, then pick the highest-IS-Sharpe alpha
inside each cluster as its centroid. Equal-weight the K=6 centroids, apply IC-sign
alignment, and post-scale gross to ~0.7 to avoid the leverage-ceiling trap that
plagued cov-based attempts (mean row L1 ~ 0.05 with tangency / min-var).

Pre-filters (regime-aware robustness, matching leaderboard top-5 pattern):
  - SUBMITTABLE IS-only pool
  - per-year IS Sharpe > 0 for every sub-year in IS (2022, 2023, 2024)
  - max IS drawdown < 25%
  - correlation dedup |rho| > 0.85 (keep higher IS Sharpe)

Cov-free by construction: no inversion, no shrinkage, no eigenvalue surgery. Side-
steps the Sigma^{-1}*mu under-leverage failure mode of every prior tangency attempt.

References:
  - Ward (1963), 'Hierarchical Grouping to Optimize an Objective Function', JASA.
  - Lopez de Prado (2016), 'Building Diversified Portfolios that Outperform Out of
    Sample', JPM — the (1-rho)/2 metric and cluster-representative idea.
  - Choueifaty & Coignard (2008) on diversification gains from cluster reps.
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
    load_member_is_returns,
    normalize_coefficients,
    member_is_sharpe,
)


COMPOSITE_ID = "auto_068_ward_centroid_k6_yearstable_dd25_dedup08"
COMPOSITION_NOTE = "ward_centroid_k6_yearstable_dd25_dedup085_l1scale070"

RUN_ID = "run_2026_05_c"
N_CLUSTERS = 6
DEDUP_RHO = 0.85
MAX_IS_DD = 0.25
TARGET_GROSS = 0.70
MIN_DAYS_PER_YEAR = 30


def _per_year_stability_mask(R: pd.DataFrame) -> pd.Series:
    """True for columns whose sub-year IS Sharpe is positive in every IS year."""
    idx = pd.to_datetime(R.index)
    years = sorted({int(y) for y in idx.year})
    ok = pd.Series(True, index=R.columns)
    any_year_checked = False
    for y in years:
        mask = (idx.year == y)
        if int(mask.sum()) < MIN_DAYS_PER_YEAR:
            continue
        any_year_checked = True
        sub = R.loc[mask]
        mu = sub.mean()
        sd = sub.std().replace(0.0, np.nan)
        sh = (mu / sd).fillna(-1.0) * np.sqrt(252.0)
        ok &= (sh > 0.0)
    if not any_year_checked:
        return pd.Series(True, index=R.columns)
    return ok


def _max_drawdown(R: pd.DataFrame) -> pd.Series:
    """Per-column max drawdown (positive number) on cumulative IS returns."""
    eq = (1.0 + R.fillna(0.0)).cumprod()
    roll_max = eq.cummax().replace(0.0, np.nan)
    dd = (eq / roll_max - 1.0).min()
    return (-dd).fillna(1.0)


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    ids_all = list(select_is_submittable(RUN_ID))
    if len(ids_all) < 4:
        ids_all = [str(a) for a in alpha_index["alpha_id"].tolist()]

    signs = member_signs_ic(RUN_ID, ids_all)
    R = load_member_is_returns(RUN_ID, ids_all, signs=signs)
    R = R.loc[:, [c for c in R.columns if R[c].notna().sum() >= 60]]
    if R.shape[1] < 4:
        return list(R.columns[: max(2, R.shape[1])])

    # 1) per-year stability across IS sub-windows
    stable = _per_year_stability_mask(R)
    cols_stable = list(R.columns[stable])
    if len(cols_stable) < N_CLUSTERS:
        cols_stable = list(R.columns)

    # 2) drawdown discipline
    dd = _max_drawdown(R[cols_stable])
    cols_dd = [c for c in cols_stable if float(dd.get(c, 1.0)) < MAX_IS_DD]
    if len(cols_dd) < N_CLUSTERS:
        cols_dd = cols_stable

    # 3) IS-Sharpe ranking (for dedup keep-metric and within-cluster pick)
    sharpe_map_all = member_is_sharpe(RUN_ID, cols_dd)
    sharpe_map = {
        k: float(v) for k, v in sharpe_map_all.items()
        if v is not None and np.isfinite(float(v))
    }

    # 4) correlation dedup
    Rk = R[cols_dd]
    kept = correlation_dedup(Rk, threshold=DEDUP_RHO, keep_metric=sharpe_map)
    kept = [a for a in kept if a in R.columns]
    if len(kept) < 2:
        # last-resort fallback: top-N by IS Sharpe
        ranked = sorted(sharpe_map.items(), key=lambda kv: kv[1], reverse=True)
        kept = [a for a, _ in ranked[: max(2, N_CLUSTERS)]]
        if len(kept) < 2:
            return list(R.columns[:2])
        return kept

    if len(kept) <= N_CLUSTERS:
        return kept

    # 5) Ward clustering on (1-rho)/2 correlation distance
    Rc = R[kept]
    corr = Rc.corr().fillna(0.0).clip(-1.0, 1.0).values
    dist_sq = np.clip(0.5 * (1.0 - corr), 0.0, 1.0)
    dist = np.sqrt(dist_sq)
    np.fill_diagonal(dist, 0.0)
    dist = 0.5 * (dist + dist.T)
    try:
        condensed = ssd.squareform(dist, checks=False)
        Z = sch.linkage(condensed, method="ward")
        K = min(N_CLUSTERS, len(kept))
        labels = sch.fcluster(Z, t=K, criterion="maxclust")
    except Exception:
        # Fallback: pure top-K-by-IS-Sharpe
        ranked = sorted(((a, sharpe_map.get(a, -np.inf)) for a in kept),
                        key=lambda kv: kv[1], reverse=True)
        return [a for a, _ in ranked[:N_CLUSTERS]]

    # 6) cluster-representative = highest IS Sharpe inside the cluster
    chosen: list[str] = []
    for c in sorted({int(l) for l in labels.tolist()}):
        members_c = [kept[i] for i, lab in enumerate(labels) if int(lab) == c]
        if not members_c:
            continue
        best = max(members_c, key=lambda a: sharpe_map.get(a, -np.inf))
        chosen.append(best)

    if len(chosen) < 2:
        ranked = sorted(((a, sharpe_map.get(a, -np.inf)) for a in kept),
                        key=lambda kv: kv[1], reverse=True)
        chosen = [a for a, _ in ranked[: max(2, N_CLUSTERS)]]
    return chosen


def member_weights(
    member_ids: list[str], alpha_index: pd.DataFrame
) -> dict[str, float]:
    if not member_ids:
        return {}
    if len(member_ids) == 1:
        return {member_ids[0]: TARGET_GROSS}

    # Equal weight across cluster centroids
    n = len(member_ids)
    coef = {a: 1.0 / n for a in member_ids}

    # IC-sign alignment so each member contributes its deployable direction
    signs = member_signs_ic(RUN_ID, member_ids)
    coef = apply_signs(coef, signs)

    # L1 normalize → sum |c| = 1
    coef = normalize_coefficients(coef, "l1")

    # Gross-exposure post-scale to escape the under-leverage trap.
    # Use IS daily-vol heuristic from the harness brief, bounded to a sane range.
    try:
        R_mem = load_member_is_returns(RUN_ID, member_ids, signs=signs)
        sigma_a = R_mem.std().reindex(member_ids).fillna(0.01).astype(float)
        est_gross = float(
            sum(abs(float(coef.get(a, 0.0))) * float(sigma_a.get(a, 0.01))
                for a in member_ids)
        )
        if est_gross > 1e-9:
            scale = TARGET_GROSS / est_gross
        else:
            scale = 10.0
    except Exception:
        scale = 10.0

    # Safety clamp: keep aggregate sum |c| within [3, 30] so runner row-L1
    # clamp still has room to operate without absurd extrapolation.
    raw_sum_abs = sum(abs(float(v)) for v in coef.values())
    scaled_sum_abs = raw_sum_abs * float(scale) if raw_sum_abs > 0 else 0.0
    if scaled_sum_abs > 30.0:
        scale *= 30.0 / max(scaled_sum_abs, 1e-9)
    elif scaled_sum_abs < 3.0 and raw_sum_abs > 0:
        scale *= 3.0 / max(scaled_sum_abs, 1e-9)

    coef = {a: float(v) * float(scale) for a, v in coef.items()}
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