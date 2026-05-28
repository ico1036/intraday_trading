"""Ward-cluster centroid composite: max-IS-Sharpe representative per cluster,
per-year IS stability + DD<20% gate, cov-free equal-weight aggregation.

Cites Lopez de Prado NCO (2019) and Raffinot HERC (2018) for the hierarchical
cluster-representative framework. Variant: within each Ward cluster on the
sqrt(0.5*(1-rho)) correlation distance, pick the highest-IS-Sharpe member as
centroid (not median), then equal-weight across K=6 centroids and post-scale
to break the gross-exposure ceiling. No covariance inversion involved.
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
    apply_signs,
    select_is_submittable,
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_113_ward_centroid_max_sharpe_yearstable_dd20"
COMPOSITION_NOTE = "ward_centroid_max_sharpe_yearstable_dd20_eqw_covfree_gross10"

RUN_ID = "run_2026_05_c"
N_CLUSTERS = 6
DD_MAX = 0.20
DEDUP_RHO = 0.85
POST_SCALE = 10.0  # break the gross-exposure ceiling (prior best 0.838 stuck at mean L1=0.05)
MIN_OBS_PER_YEAR = 20


def _max_drawdown(returns: pd.Series) -> float:
    if returns is None or returns.empty:
        return 1.0
    cum = (1.0 + returns.fillna(0.0)).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    val = float(-dd.min())
    if not math.isfinite(val):
        return 1.0
    return val


def _per_year_all_positive(returns: pd.Series, min_years: int = 2) -> bool:
    if returns is None or returns.empty:
        return False
    try:
        years = returns.dropna().groupby(returns.dropna().index.year)
    except Exception:
        return False
    total = 0
    ok = 0
    for _, ser in years:
        if len(ser) < MIN_OBS_PER_YEAR:
            continue
        total += 1
        mu = float(ser.mean())
        sd = float(ser.std())
        if sd > 0 and (mu / sd) > 0.0:
            ok += 1
    return total >= min_years and ok == total


def _annualized_sharpe(returns: pd.Series) -> float:
    if returns is None or returns.empty:
        return -1e9
    mu = float(returns.mean())
    sd = float(returns.std())
    if sd <= 0 or not math.isfinite(sd):
        return -1e9
    return (mu / sd) * math.sqrt(252.0)


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    try:
        ids = select_is_submittable(RUN_ID)
    except Exception:
        ids = []
    if not ids:
        ids = alpha_index["alpha_id"].astype(str).tolist()
    if len(ids) < 2:
        return ids

    try:
        signs = member_signs_ic(RUN_ID, ids)
    except Exception:
        signs = {a: 1 for a in ids}

    try:
        R = load_member_is_returns(RUN_ID, ids, signs=signs)
    except Exception:
        R = pd.DataFrame()

    if R is None or R.empty or R.shape[1] < 2:
        # Fallback: top-K by alpha_index is_sharpe
        try:
            top = (alpha_index.sort_values("is_sharpe", ascending=False)
                   ["alpha_id"].astype(str).tolist())
        except Exception:
            top = ids
        out = top[:max(N_CLUSTERS, 2)]
        return out if len(out) >= 2 else ids[:2]

    # Stage 1: per-year stability + DD filter
    sharpe_map: dict[str, float] = {}
    survivors: list[str] = []
    for col in R.columns:
        ser = R[col].dropna()
        if ser.empty:
            continue
        sh = _annualized_sharpe(ser)
        sharpe_map[col] = sh
        if not _per_year_all_positive(ser, min_years=2):
            continue
        if _max_drawdown(ser) > DD_MAX:
            continue
        survivors.append(col)

    # Stage 2: relax if too few
    if len(survivors) < N_CLUSTERS:
        survivors = [c for c in R.columns if sharpe_map.get(c, -1e9) > 0.0]
    if len(survivors) < N_CLUSTERS:
        survivors = sorted(
            R.columns.tolist(),
            key=lambda a: sharpe_map.get(a, -1e9),
            reverse=True,
        )[: max(N_CLUSTERS * 3, 12)]
    if len(survivors) < 2:
        survivors = sorted(
            R.columns.tolist(),
            key=lambda a: sharpe_map.get(a, -1e9),
            reverse=True,
        )[:2]

    # Stage 3: correlation dedup
    R_keep = R[survivors]
    try:
        deduped = correlation_dedup(R_keep, DEDUP_RHO, keep_metric=sharpe_map)
        if not deduped or len(deduped) < 2:
            deduped = survivors
    except Exception:
        deduped = survivors

    R_use = R[deduped]
    if R_use.shape[1] <= N_CLUSTERS:
        # nothing to cluster — just take all
        chosen = list(R_use.columns)
        if len(chosen) >= 2:
            return chosen

    # Stage 4: Ward hierarchical clustering on correlation distance
    try:
        corr = R_use.corr().fillna(0.0).values
        np.fill_diagonal(corr, 1.0)
        dist = np.sqrt(np.clip(0.5 * (1.0 - corr), 0.0, 1.0))
        np.fill_diagonal(dist, 0.0)
        condensed = ssd.squareform(dist, checks=False)
        Z = sch.linkage(condensed, method="ward")
        k = min(N_CLUSTERS, R_use.shape[1])
        labels = sch.fcluster(Z, t=k, criterion="maxclust")
    except Exception:
        # fallback: top-K by IS Sharpe
        return sorted(
            R_use.columns.tolist(),
            key=lambda a: sharpe_map.get(a, -1e9),
            reverse=True,
        )[: max(N_CLUSTERS, 2)]

    cols = list(R_use.columns)
    chosen: list[str] = []
    for c in range(1, int(labels.max()) + 1):
        members_in = [cols[i] for i in range(len(cols)) if labels[i] == c]
        if not members_in:
            continue
        best = max(members_in, key=lambda a: sharpe_map.get(a, -1e9))
        chosen.append(best)

    # Dedup any accidental duplicates while preserving order
    seen = set()
    final = []
    for a in chosen:
        if a not in seen:
            seen.add(a)
            final.append(a)
    if len(final) < 2:
        final = sorted(
            sharpe_map.keys(), key=lambda a: sharpe_map[a], reverse=True
        )[: max(N_CLUSTERS, 2)]
    return final


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    if not member_ids:
        return {}
    if len(member_ids) == 1:
        return {member_ids[0]: POST_SCALE}

    try:
        signs = member_signs_ic(RUN_ID, member_ids)
    except Exception:
        signs = {a: 1 for a in member_ids}

    # Equal-weight base, sign-aligned via IC
    n = len(member_ids)
    coef = {a: 1.0 / n for a in member_ids}
    try:
        coef = apply_signs(coef, signs)
    except Exception:
        pass

    # L1-normalize then aggressively scale (break the gross-exposure ceiling)
    try:
        coef = normalize_coefficients(coef, "l1")
    except Exception:
        # ensure dict[str, float]
        s = sum(abs(v) for v in coef.values()) or 1.0
        coef = {k: v / s for k, v in coef.items()}

    coef = {k: float(v) * POST_SCALE for k, v in coef.items()}
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