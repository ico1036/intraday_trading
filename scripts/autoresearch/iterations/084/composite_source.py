"""Ward-hierarchical cluster-centroid composite (cov-free): correlation
distance d_ij = sqrt(0.5*(1-rho)) (Mantegna 1999), Ward linkage, cut at
K=6, pick highest-IS-Sharpe per cluster as exemplar, 1/N weight, scale to
~0.7 mean row L1. Sidesteps the Sigma^-1 dilution trap that muted prior
cov-based composites (Lopez de Prado 2016 HRP idea, simplified to
cluster-centroid + equal-weight rather than recursive bisection)."""
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

COMPOSITE_ID = "auto_084_ward_cluster_centroid_k6_yearstable_dd25"
COMPOSITION_NOTE = "ward_cluster_centroid_k6_yearstable_dd25_dedup088_scale5"

RUN_ID = "run_2026_05_c"
N_CLUSTERS = 6
DEDUP_RHO = 0.88
MAX_DD = 0.25
GROSS_SCALE = 5.0  # multiplies L1-normalized 1/N coefs to push gross into runner's cap


def _per_year_positive(R: pd.DataFrame) -> list[str]:
    """Keep cols whose Sharpe is positive in every calendar year with enough data."""
    try:
        idx = pd.to_datetime(R.index)
    except Exception:
        return list(R.columns)
    years = np.asarray(idx.year)
    unique_years = sorted(set(int(y) for y in years))
    if len(unique_years) < 2:
        return list(R.columns)
    keep: list[str] = []
    for col in R.columns:
        s = R[col].values
        ok = True
        for y in unique_years:
            mask = years == y
            sub = s[mask]
            if sub.size < 20:
                continue
            mu = float(np.nanmean(sub))
            sd = float(np.nanstd(sub))
            if not np.isfinite(mu) or not np.isfinite(sd) or sd <= 0:
                ok = False
                break
            sh = mu / sd * math.sqrt(252.0)
            if sh <= 0.0:
                ok = False
                break
        if ok:
            keep.append(col)
    return keep


def _max_drawdown(returns: pd.Series) -> float:
    r = returns.fillna(0.0).values
    if r.size == 0:
        return 1.0
    eq = np.cumprod(1.0 + r)
    peak = np.maximum.accumulate(eq)
    dd = (eq - peak) / peak
    return float(-dd.min()) if dd.size else 1.0


def _drawdown_filter(R: pd.DataFrame, max_dd: float) -> list[str]:
    return [c for c in R.columns if _max_drawdown(R[c]) <= max_dd]


def _is_sharpe_map(R: pd.DataFrame) -> dict[str, float]:
    out: dict[str, float] = {}
    for col in R.columns:
        s = R[col].values
        mu = float(np.nanmean(s))
        sd = float(np.nanstd(s))
        if not np.isfinite(mu) or not np.isfinite(sd) or sd <= 0.0:
            out[col] = 0.0
        else:
            out[col] = mu / sd * math.sqrt(252.0)
    return out


def _safe_corr(R: pd.DataFrame) -> np.ndarray:
    C = R.corr().fillna(0.0).values
    n = C.shape[0]
    if n == 0:
        return C
    np.fill_diagonal(C, 1.0)
    return np.clip(C, -1.0, 1.0)


def _ward_cluster_labels(R: pd.DataFrame, k: int) -> np.ndarray:
    C = _safe_corr(R)
    D = np.sqrt(np.maximum(0.0, 0.5 * (1.0 - C)))
    np.fill_diagonal(D, 0.0)
    # Force symmetry to satisfy squareform's strict checks
    D = 0.5 * (D + D.T)
    condensed = ssd.squareform(D, checks=False)
    Z = sch.linkage(condensed, method="ward")
    k_eff = max(1, min(k, R.shape[1]))
    return sch.fcluster(Z, t=k_eff, criterion="maxclust")


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    ids = select_is_submittable(RUN_ID)
    if not ids or len(ids) < 4:
        return list(ids) if ids else []

    signs = member_signs_ic(RUN_ID, ids)
    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    if R is None or R.shape[1] < 4:
        return list(R.columns) if R is not None else []

    # Drop columns that are mostly NaN; fill rest with 0
    R = R.dropna(axis=1, thresh=int(0.5 * len(R))).fillna(0.0)
    if R.shape[1] < 4:
        return list(R.columns)

    try:
        R.index = pd.to_datetime(R.index)
    except Exception:
        pass

    # 1) per-year stability
    stable = _per_year_positive(R)
    if len(stable) >= max(N_CLUSTERS, 4):
        R = R[stable]

    # 2) drawdown discipline
    dd_ok = _drawdown_filter(R, MAX_DD)
    if len(dd_ok) >= max(N_CLUSTERS, 4):
        R = R[dd_ok]

    # 3) correlation dedup keeping highest IS Sharpe
    sh_map = _is_sharpe_map(R)
    try:
        kept = correlation_dedup(R, threshold=DEDUP_RHO, keep_metric=sh_map)
    except Exception:
        kept = list(R.columns)
    if isinstance(kept, list) and len(kept) >= max(N_CLUSTERS, 2):
        R = R[kept]

    if R.shape[1] < 2:
        return list(R.columns)

    # If we already have <= N_CLUSTERS candidates, just take them all.
    if R.shape[1] <= N_CLUSTERS:
        sh_map = _is_sharpe_map(R)
        chosen = sorted(R.columns.tolist(), key=lambda c: -sh_map.get(c, 0.0))
        return chosen

    # 4) Ward clustering on correlation distance
    try:
        labels = _ward_cluster_labels(R, N_CLUSTERS)
    except Exception:
        # Fallback: top-K by IS Sharpe
        sh_map = _is_sharpe_map(R)
        chosen = sorted(R.columns.tolist(), key=lambda c: -sh_map.get(c, 0.0))[:N_CLUSTERS]
        return chosen

    # 5) centroid (highest IS Sharpe) per cluster
    cluster_map: dict[int, list[str]] = {}
    cols = list(R.columns)
    for col, lab in zip(cols, labels):
        cluster_map.setdefault(int(lab), []).append(col)

    sh_map = _is_sharpe_map(R)
    chosen: list[str] = []
    for lab, members in cluster_map.items():
        if not members:
            continue
        best = max(members, key=lambda c: sh_map.get(c, 0.0))
        # Only include if its IS Sharpe is positive — defensive against
        # clusters made entirely of marginal alphas.
        if sh_map.get(best, 0.0) > 0.0:
            chosen.append(best)

    if len(chosen) < 2:
        chosen = sorted(cols, key=lambda c: -sh_map.get(c, 0.0))[:N_CLUSTERS]

    chosen.sort(key=lambda c: -sh_map.get(c, 0.0))
    return chosen


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    if not member_ids:
        return {}
    if len(member_ids) == 1:
        # Single member: just hand it the full budget with IC sign.
        signs = member_signs_ic(RUN_ID, member_ids)
        sgn = float(signs.get(member_ids[0], 1))
        return {member_ids[0]: sgn * 1.0}

    signs = member_signs_ic(RUN_ID, member_ids)

    # Base 1/N over kept members
    base: dict[str, float] = {a: 1.0 for a in member_ids}
    # Sign-flip per IC
    base = apply_signs(base, signs)
    # L1-normalize: sum |c| = 1
    try:
        base = normalize_coefficients(base, "l1")
    except Exception:
        n = float(len(member_ids))
        base = {k: v / n for k, v in base.items()}

    # Scale up to push composite gross firmly into runner's L1 cap region.
    coef = {k: v * GROSS_SCALE for k, v in base.items()}
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