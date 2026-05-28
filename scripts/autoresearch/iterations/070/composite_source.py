"""Ward-cluster centroid composite with per-year IS Sharpe stability and DD discipline.

Method follows Lopez de Prado (2016) HRP-style clustering: build a
correlation-distance matrix d_ij = sqrt(0.5*(1 - rho_ij)) on sign-aligned
IS daily returns, Ward-linkage hierarchical clustering, cut at K=6
clusters, then pick the single highest-IS-Sharpe alpha per cluster
(centroid representative). Pre-filter by per-year IS Sharpe positivity
over 2022/2023/2024 and IS max drawdown <= 22% to suppress regime-fragile
picks (yen-carry / FTX-era tail breaks). Combination is pure cov-FREE
1/K equal-weight on the K centroids, sign-aligned via member_signs_ic,
with explicit L1 budget set to 1.2 to push mean row L1 into the
[0.5, 0.9] band and avoid the 1/sigma underweighting trap of cov-based
optimizers.
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd
import scipy.cluster.hierarchy as sch
import scipy.spatial.distance as ssd

from intraday.composites._runner import build_and_backtest
from intraday.composites._optim_helpers import (
    load_member_is_returns,
    member_signs_ic,
    normalize_coefficients,
    select_is_submittable,
)

COMPOSITE_ID = "auto_070_ward_centroid_yearstable_dd22_k6_eqwt_co"
COMPOSITION_NOTE = "ward_centroid_yearstable_dd22_k6_eqwt_covfree_gross"

RUN_ID = "run_2026_05_c"
K_CLUSTERS = 6
MAX_DD = 0.22
GROSS_TARGET = 1.2  # Sum|c_a| after L1-norm scaled up; targets row_L1 ~0.6-0.9
YEARS = (2022, 2023, 2024)


def _max_dd(r: pd.Series) -> float:
    s = r.dropna()
    if s.empty:
        return 1.0
    eq = (1.0 + s).cumprod()
    peak = eq.cummax()
    dd = (eq / peak - 1.0).min()
    return float(abs(dd))


def _ann_sharpe(r: pd.Series) -> float:
    s = r.dropna()
    if len(s) < 2:
        return -1e9
    sd = float(s.std())
    if sd == 0.0:
        return -1e9
    return float(s.mean() / sd * np.sqrt(252.0))


def _year_stable(r: pd.Series) -> bool:
    s = r.dropna()
    if len(s) < 60:
        return False
    idx = s.index
    if not isinstance(idx, pd.DatetimeIndex):
        try:
            idx = pd.to_datetime(idx)
            s = pd.Series(s.values, index=idx)
        except Exception:
            return True
    yrs_arr = np.asarray(s.index.year)
    vals = s.values
    for y in YEARS:
        mask = (yrs_arr == y)
        if int(mask.sum()) < 20:
            continue
        sub = vals[mask]
        if float(np.std(sub)) == 0.0 or float(np.mean(sub)) <= 0.0:
            return False
    return True


def _ward_cluster_labels(R: pd.DataFrame, k: int) -> np.ndarray:
    corr = R.corr().fillna(0.0).values
    corr = (corr + corr.T) / 2.0
    np.fill_diagonal(corr, 1.0)
    corr = np.clip(corr, -1.0, 1.0)
    dist = np.sqrt(np.clip(0.5 * (1.0 - corr), 0.0, 1.0))
    np.fill_diagonal(dist, 0.0)
    cond = ssd.squareform(dist, checks=False)
    Z = sch.linkage(cond, method="ward")
    return sch.fcluster(Z, t=k, criterion="maxclust")


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    candidates = select_is_submittable(RUN_ID)
    if not candidates:
        candidates = [str(x) for x in alpha_index["alpha_id"].tolist()]
    if not candidates:
        return []

    signs = member_signs_ic(RUN_ID, candidates)
    R = load_member_is_returns(RUN_ID, candidates, signs=signs)
    R = R.dropna(axis=1, how="all")
    if R.shape[1] < 2:
        return list(R.columns)

    sharpes_all = {c: _ann_sharpe(R[c]) for c in R.columns}

    # Tier 1: year-stable AND DD <= 22% AND Sharpe > 0
    keep: list[str] = []
    sharpes: dict[str, float] = {}
    for c in R.columns:
        col = R[c]
        if not _year_stable(col):
            continue
        if _max_dd(col) > MAX_DD:
            continue
        sh = sharpes_all[c]
        if sh <= 0:
            continue
        keep.append(c)
        sharpes[c] = sh

    # Tier 2: relax DD if Tier 1 thin
    if len(keep) < K_CLUSTERS:
        keep, sharpes = [], {}
        for c in R.columns:
            if not _year_stable(R[c]):
                continue
            sh = sharpes_all[c]
            if sh <= 0:
                continue
            keep.append(c)
            sharpes[c] = sh

    # Tier 3: fall back to top-by-Sharpe
    if len(keep) < K_CLUSTERS:
        keep = sorted(sharpes_all, key=lambda x: sharpes_all[x], reverse=True)[: max(K_CLUSTERS, 8)]
        sharpes = {c: sharpes_all[c] for c in keep}

    Rk = R[keep].fillna(0.0)
    if Rk.shape[1] <= K_CLUSTERS:
        return list(Rk.columns)

    labels = _ward_cluster_labels(Rk, K_CLUSTERS)
    n = Rk.shape[1]
    cols = list(Rk.columns)

    chosen: list[str] = []
    for cl in np.unique(labels):
        cluster_members = [cols[i] for i in range(n) if labels[i] == cl]
        if not cluster_members:
            continue
        best = max(cluster_members, key=lambda a: sharpes.get(a, -1e9))
        chosen.append(best)

    if len(chosen) < 2:
        chosen = sorted(sharpes, key=lambda x: sharpes[x], reverse=True)[: K_CLUSTERS]

    # Dedup any accidental repeat (sch.fcluster shouldn't produce them, but be safe)
    seen: set[str] = set()
    out: list[str] = []
    for a in chosen:
        if a not in seen:
            out.append(a)
            seen.add(a)
    return out


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    if not member_ids:
        return {}
    signs = member_signs_ic(RUN_ID, member_ids)
    raw = {a: float(signs.get(a, 1)) for a in member_ids}
    coef = normalize_coefficients(raw, "l1")  # Sum|c| = 1
    coef = {k: float(v) * GROSS_TARGET for k, v in coef.items()}
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