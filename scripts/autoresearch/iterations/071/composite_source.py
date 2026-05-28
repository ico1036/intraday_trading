"""HERC-style cluster-centroid composite: Ward clustering on correlation distance,
per-cluster IS-Sharpe centroid, year-stability + max-DD discipline filters,
vol-aware gross-exposure rescale. Cites Raffinot (2018) HERC and Lopez de Prado
(2016) quasi-diagonalization — cov-free combination to avoid 1/σ-weighting trap."""
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

COMPOSITE_ID = "auto_071_herc_ward_centroids_yearstable_dd20_dedu"
COMPOSITION_NOTE = "herc_ward_centroids_yearstable_dd20_dedup085_k6_gross070"

RUN_ID = "run_2026_05_c"
N_CLUSTERS = 6
MAX_DD_THRESH = 0.20
DEDUP_RHO = 0.85
TARGET_GROSS = 0.70
ANN = math.sqrt(252.0)


def _ensure_datetime_index(R: pd.DataFrame) -> pd.DataFrame:
    if isinstance(R.index, pd.DatetimeIndex):
        return R
    try:
        R2 = R.copy()
        R2.index = pd.to_datetime(R2.index)
        return R2
    except Exception:
        return R


def _year_stable(R: pd.DataFrame) -> list[str]:
    """Keep alphas with positive annualized Sharpe in EVERY IS sub-year."""
    R = _ensure_datetime_index(R)
    if not isinstance(R.index, pd.DatetimeIndex):
        return list(R.columns)
    years = sorted({int(y) for y in R.index.year.unique()})
    if len(years) < 2:
        return list(R.columns)
    keep: list[str] = []
    for col in R.columns:
        ok = True
        for y in years:
            seg = R.loc[R.index.year == y, col].dropna()
            if len(seg) < 10:
                continue
            mu = float(seg.mean())
            sd = float(seg.std(ddof=1))
            if not np.isfinite(sd) or sd <= 0:
                ok = False
                break
            sh = (mu / sd) * ANN
            if sh <= 0:
                ok = False
                break
        if ok:
            keep.append(col)
    return keep


def _dd_filter(R: pd.DataFrame, max_dd: float) -> list[str]:
    """Keep alphas whose IS max-drawdown (additive returns) ≤ max_dd."""
    keep: list[str] = []
    for col in R.columns:
        s = R[col].dropna()
        if len(s) < 20:
            continue
        eq = s.cumsum()
        peak = eq.cummax()
        dd = float((eq - peak).min())
        if (-dd) <= max_dd:
            keep.append(col)
    return keep


def _sharpe_dict(R: pd.DataFrame) -> dict[str, float]:
    mu = R.mean()
    sd = R.std(ddof=1).replace(0.0, np.nan)
    sh = (mu / sd) * ANN
    return {k: float(v) for k, v in sh.dropna().items()}


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    # 1. Candidate pool: prefer SUBMITTABLE, fall back to all alphas on the run
    try:
        ids = list(select_is_submittable(RUN_ID))
    except Exception:
        ids = []
    if len(ids) < 8:
        try:
            ids = list(select_all_alphas(RUN_ID))
        except Exception:
            pass
    if len(ids) < 2:
        # last-resort fallback to alpha_index column if available
        if "alpha_id" in alpha_index.columns:
            ids = alpha_index["alpha_id"].astype(str).tolist()
    if len(ids) < 2:
        raise RuntimeError("no alpha candidates for run %s" % RUN_ID)

    # 2. Sign-align via IC dead-band sign
    try:
        signs = member_signs_ic(RUN_ID, ids)
    except Exception:
        signs = {a: 1 for a in ids}

    # 3. Load IS returns (sign-applied)
    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    if R is None or R.shape[1] < 2:
        return ids[: max(2, N_CLUSTERS)]

    # 4. Year-stability — only collapse if it leaves enough candidates
    stable = _year_stable(R)
    if len(stable) >= N_CLUSTERS + 2:
        R = R[stable]

    # 5. Drawdown discipline
    dd_kept = _dd_filter(R, MAX_DD_THRESH)
    if len(dd_kept) >= N_CLUSTERS + 2:
        R = R[dd_kept]

    # 6. Correlation dedup at ρ=0.85, keep highest-IS-Sharpe in each cluster
    sh = _sharpe_dict(R)
    try:
        kept_cols = correlation_dedup(R, DEDUP_RHO, keep_metric=sh)
    except Exception:
        kept_cols = list(R.columns)
    if len(kept_cols) < N_CLUSTERS:
        # widen if dedup was too aggressive
        order = sorted(R.columns, key=lambda a: sh.get(a, -1e9), reverse=True)
        kept_cols = order[: max(N_CLUSTERS * 2, len(kept_cols))]
    R = R[kept_cols]

    # 7. If after all filters we still have very few, just return top-IS-Sharpe
    if R.shape[1] <= N_CLUSTERS:
        order = sorted(R.columns, key=lambda a: sh.get(a, -1e9), reverse=True)
        return order[: max(2, R.shape[1])]

    # 8. Ward hierarchical clustering on correlation distance
    try:
        corr = R.corr().fillna(0.0).values
        np.fill_diagonal(corr, 1.0)
        corr = np.clip(corr, -1.0, 1.0)
        dist = np.sqrt(np.clip(0.5 * (1.0 - corr), 0.0, 1.0))
        dist = (dist + dist.T) / 2.0
        np.fill_diagonal(dist, 0.0)
        condensed = ssd.squareform(dist, checks=False)
        Z = sch.linkage(condensed, method="ward")
        K = int(min(N_CLUSTERS, R.shape[1]))
        labels = sch.fcluster(Z, t=K, criterion="maxclust")
    except Exception:
        # Fallback: top-K by IS-Sharpe
        order = sorted(R.columns, key=lambda a: sh.get(a, -1e9), reverse=True)
        return order[:N_CLUSTERS]

    # 9. Pick highest-IS-Sharpe alpha from each cluster (centroid representative)
    cols = list(R.columns)
    local_sh = _sharpe_dict(R)
    chosen: list[str] = []
    for k in sorted(set(int(x) for x in labels)):
        members = [cols[i] for i in range(len(cols)) if int(labels[i]) == k]
        if not members:
            continue
        best = max(members, key=lambda a: local_sh.get(a, -1e9))
        chosen.append(best)

    if len(chosen) < 2:
        order = sorted(R.columns, key=lambda a: local_sh.get(a, -1e9), reverse=True)
        chosen = order[: max(2, N_CLUSTERS)]
    return chosen


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    if not member_ids:
        return {}
    if len(member_ids) == 1:
        # Degenerate but valid; runner will row-L1 cap to 1.
        return {member_ids[0]: TARGET_GROSS}

    # Sign-align coefficients to the deployable sign of each member
    try:
        signs = member_signs_ic(RUN_ID, member_ids)
    except Exception:
        signs = {a: 1 for a in member_ids}

    # Equal-weight cluster centroids → Σ|c| = 1 after l1 normalization
    coef = {a: 1.0 for a in member_ids}
    coef = apply_signs(coef, signs)
    coef = normalize_coefficients(coef, "l1")

    # Gross-exposure rescale: aim for mean row L1 ≈ TARGET_GROSS.
    # Use per-member daily return vol as a proxy for typical weight magnitude.
    try:
        R = load_member_is_returns(RUN_ID, member_ids, signs=signs)
    except Exception:
        R = None

    scale = 10.0  # safety floor — empirically 1/N-after-l1 needs ~10x
    if R is not None and R.shape[1] >= 1:
        common = [a for a in member_ids if a in R.columns]
        if common:
            sigma = R[common].std(ddof=1).fillna(0.0)
            # Estimate Σ|c_a|·σ_a as a stand-in for the implied gross.
            denom = float(sum(abs(coef.get(a, 0.0)) * float(sigma.get(a, 0.0)) for a in common))
            if denom > 1e-9:
                scale = float(np.clip(TARGET_GROSS / denom, 1.0, 25.0))

    coef = {k: float(v) * scale for k, v in coef.items()}
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