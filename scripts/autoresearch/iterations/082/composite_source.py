"""Ward-cluster-centroid composite (cov-free): correlation-distance hierarchical
clustering picks K=6 representatives, equal-weighted and L1-rescaled to a
target gross of 0.70. Year-stability + drawdown discipline + IC sign-alignment.
Cites Lopez de Prado (2016) HRP correlation-distance metric and Raffinot (2018)
HERC cluster-representative selection."""
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
    apply_signs,
    select_is_submittable,
    select_all_alphas,
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_082_ward_centroid_k6_yearstable_dd22_dedup08"
COMPOSITION_NOTE = "ward_centroid_k6_yearstable_dd22_dedup088_gross070"

RUN_ID = "run_2026_05_c"
N_CLUSTERS = 6
DD_THRESHOLD = 0.22
DEDUP_RHO = 0.88
TARGET_GROSS = 0.70
MIN_BARS_PER_YEAR = 30


def _safe_submittable() -> list[str]:
    try:
        ids = list(select_is_submittable(RUN_ID))
        if len(ids) >= 4:
            return ids
    except Exception:
        pass
    try:
        return list(select_all_alphas(RUN_ID))
    except Exception:
        return []


def _max_dd(returns: np.ndarray) -> float:
    r = np.nan_to_num(returns, nan=0.0)
    if r.size == 0:
        return 1.0
    eq = np.cumsum(r)
    peak = np.maximum.accumulate(eq)
    return float((peak - eq).max())


def _is_sharpe_map(R: pd.DataFrame) -> dict[str, float]:
    out: dict[str, float] = {}
    for col in R.columns:
        r = R[col].fillna(0.0).values
        sd = float(np.std(r))
        out[col] = float(np.mean(r) / sd) * math.sqrt(365.0) if sd > 0 else 0.0
    return out


def _year_stable(R: pd.DataFrame) -> list[str]:
    idx = pd.to_datetime(R.index)
    years = np.asarray(idx.year)
    unique_years = sorted(set(int(y) for y in years))
    kept: list[str] = []
    for col in R.columns:
        ok = True
        any_year_checked = False
        for y in unique_years:
            mask = years == y
            sub = R[col].values[mask]
            sub = sub[~np.isnan(sub)]
            if sub.size < MIN_BARS_PER_YEAR:
                continue
            any_year_checked = True
            mu = float(np.mean(sub))
            if mu <= 0.0:
                ok = False
                break
        if ok and any_year_checked:
            kept.append(col)
    return kept


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    ids = _safe_submittable()
    if len(ids) < 4 and alpha_index is not None and "alpha_id" in alpha_index.columns:
        ids = list(alpha_index["alpha_id"].astype(str).tolist())
    if len(ids) < 4:
        return ids[: max(2, len(ids))]

    try:
        signs = member_signs_ic(RUN_ID, ids)
    except Exception:
        signs = {a: 1 for a in ids}

    try:
        R = load_member_is_returns(RUN_ID, ids, signs=signs)
    except Exception:
        R = pd.DataFrame()

    if R is None or R.empty or R.shape[1] < 4:
        ranked = ids[: max(N_CLUSTERS, 4)]
        return ranked

    R = R.dropna(axis=1, how="all")
    if R.shape[1] < 4:
        return list(R.columns)[: max(2, R.shape[1])]

    # ---- Drawdown discipline -------------------------------------------------
    dd_keep = [c for c in R.columns if _max_dd(R[c].values) < DD_THRESHOLD]
    if len(dd_keep) < N_CLUSTERS + 2:
        pairs = sorted(((c, _max_dd(R[c].values)) for c in R.columns), key=lambda x: x[1])
        dd_keep = [c for c, _ in pairs[: max(N_CLUSTERS * 3, 12)]]
    R2 = R[dd_keep]

    # ---- Per-year stability (don't shrink past viable size) ------------------
    stable = _year_stable(R2)
    if len(stable) >= N_CLUSTERS + 2:
        R2 = R2[stable]

    is_sharpe = _is_sharpe_map(R2)

    # ---- Correlation dedup ---------------------------------------------------
    try:
        dedup_ids = correlation_dedup(R2, DEDUP_RHO, keep_metric=is_sharpe)
    except Exception:
        dedup_ids = list(R2.columns)
    if len(dedup_ids) >= N_CLUSTERS + 1:
        R2 = R2[dedup_ids]

    if R2.shape[1] <= N_CLUSTERS:
        return list(R2.columns)

    # ---- Ward hierarchical clustering on correlation distance ---------------
    corr = R2.corr().fillna(0.0).values
    np.fill_diagonal(corr, 1.0)
    corr = np.clip(corr, -1.0, 1.0)
    dist = np.sqrt(np.clip(0.5 * (1.0 - corr), 0.0, 1.0))
    dist = 0.5 * (dist + dist.T)
    np.fill_diagonal(dist, 0.0)

    try:
        condensed = ssd.squareform(dist, checks=False)
        Z = sch.linkage(condensed, method="ward")
        labels = sch.fcluster(Z, t=N_CLUSTERS, criterion="maxclust")
    except Exception:
        ranked = sorted(R2.columns, key=lambda a: is_sharpe.get(a, 0.0), reverse=True)
        return ranked[: max(N_CLUSTERS, 4)]

    cols = list(R2.columns)
    centroids: list[str] = []
    for k in range(1, int(labels.max()) + 1):
        members_k = [cols[i] for i, lab in enumerate(labels) if lab == k]
        if not members_k:
            continue
        rep = max(members_k, key=lambda a: is_sharpe.get(a, 0.0))
        centroids.append(rep)

    if len(centroids) < 2:
        ranked = sorted(cols, key=lambda a: is_sharpe.get(a, 0.0), reverse=True)
        centroids = ranked[: max(N_CLUSTERS, 4)]

    # Cap if for any reason we ended up with > N_CLUSTERS (safety)
    if len(centroids) > N_CLUSTERS:
        centroids = sorted(centroids, key=lambda a: is_sharpe.get(a, 0.0), reverse=True)[:N_CLUSTERS]

    return centroids


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    if not member_ids:
        return {}

    try:
        signs = member_signs_ic(RUN_ID, member_ids)
    except Exception:
        signs = {a: 1 for a in member_ids}
    signs = {a: int(signs.get(a, 1)) for a in member_ids}

    # Equal-weight starting coefficients over the cluster centroids
    coef: dict[str, float] = {a: 1.0 for a in member_ids}

    # Apply IC-derived signs so member weight streams contribute with deployable sign
    try:
        coef = apply_signs(coef, signs)
    except Exception:
        coef = {a: float(signs.get(a, 1)) * 1.0 for a in member_ids}

    # L1-normalize so Σ|c| = 1
    try:
        coef = normalize_coefficients(coef, "l1")
    except Exception:
        s = sum(abs(v) for v in coef.values()) or 1.0
        coef = {k: v / s for k, v in coef.items()}

    # Lift mean row L1 toward [0.5, 0.9] — runner clamps if it exceeds 1.0
    coef = {k: v * TARGET_GROSS for k, v in coef.items()}

    # Final guardrail: never return all-zero or empty
    if not coef or not any(abs(v) > 1e-12 for v in coef.values()):
        n = max(len(member_ids), 1)
        coef = {a: TARGET_GROSS / n for a in member_ids}

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