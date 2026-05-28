"""Ward hierarchical clustering on IS correlation distance with top-IS-Sharpe
centroid-per-cluster equal weighting (Lopez de Prado MLAM 2019, Raffinot HERC 2018
distance metric d=sqrt(0.5*(1-rho))), with year-stability + max-DD regime filter
and explicit gross-exposure rescaling to the [0.5, 0.8] risk budget."""
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

COMPOSITE_ID = "auto_119_ward_corrdist_topsharpe_centroid_yearsta"
COMPOSITION_NOTE = "ward_corrdist_topsharpe_centroid_yearstable_dd25_k6_gross070"

RUN_ID = "run_2026_05_c"
K_CLUSTERS = 6
DD_MAX = 0.25
DEDUP_RHO = 0.85
TARGET_GROSS = 0.70
ANN = math.sqrt(252.0)


# ------------------------------ helpers -----------------------------------

def _ann_sharpe(R: pd.DataFrame) -> pd.Series:
    mu = R.mean()
    sd = R.std(ddof=1).replace(0.0, np.nan)
    return (mu / sd) * ANN


def _year_stable(R: pd.DataFrame) -> list[str]:
    """Keep columns whose per-calendar-year Sharpe is > 0 in every IS year
    that has >= 20 observations (regime-conditional robustness)."""
    idx = R.index
    if not isinstance(idx, pd.DatetimeIndex):
        try:
            idx = pd.to_datetime(idx, errors="coerce")
        except Exception:
            return list(R.columns)
        R = R.copy()
        R.index = idx
    years = sorted({int(d.year) for d in idx if pd.notna(d)})
    if len(years) < 2:
        return list(R.columns)
    keep: list[str] = []
    for col in R.columns:
        s_all = R[col]
        ok = True
        for y in years:
            sub = s_all.loc[R.index.year == y].dropna()
            if len(sub) < 20:
                continue
            sd = float(sub.std(ddof=1))
            if not np.isfinite(sd) or sd <= 0.0:
                ok = False
                break
            sh = float(sub.mean()) / sd * ANN
            if not (sh > 0.0):
                ok = False
                break
        if ok:
            keep.append(col)
    return keep


def _drawdown_filter(R: pd.DataFrame, dd_max: float) -> list[str]:
    keep: list[str] = []
    for col in R.columns:
        s = R[col].dropna()
        if len(s) < 30:
            continue
        eq = (1.0 + s).cumprod()
        peak = eq.cummax()
        dd = float((eq / peak - 1.0).min())
        if dd > -dd_max:
            keep.append(col)
    return keep


def _ward_cluster_labels(R: pd.DataFrame, k: int) -> np.ndarray:
    corr = R.corr().fillna(0.0).clip(-1.0, 1.0).values
    n = corr.shape[0]
    if n <= 1:
        return np.ones(n, dtype=int)
    dist_mat = np.sqrt(np.clip(0.5 * (1.0 - corr), 0.0, 1.0))
    np.fill_diagonal(dist_mat, 0.0)
    # symmetrize against tiny FP asymmetry
    dist_mat = 0.5 * (dist_mat + dist_mat.T)
    cond = ssd.squareform(dist_mat, checks=False)
    Z = sch.linkage(cond, method="ward")
    k_eff = max(1, min(k, n))
    labels = sch.fcluster(Z, t=k_eff, criterion="maxclust")
    return np.asarray(labels, dtype=int)


def _filtered_returns(run_id: str) -> tuple[pd.DataFrame, dict[str, int]]:
    ids = list(select_is_submittable(run_id) or [])
    if len(ids) < 4:
        return pd.DataFrame(), {}
    signs = member_signs_ic(run_id, ids, dead_band=0.005) or {}
    R = load_member_is_returns(run_id, ids, signs=signs)
    if R is None or R.shape[1] < 4:
        return pd.DataFrame(), signs
    R = R.dropna(how="all").dropna(axis=1, how="all")
    if R.shape[1] < 4:
        return R, signs

    # year stability
    ys = _year_stable(R)
    if len(ys) >= max(K_CLUSTERS, 4):
        R = R[ys]

    # max-drawdown discipline
    dd = _drawdown_filter(R, DD_MAX)
    if len(dd) >= max(K_CLUSTERS, 4):
        R = R[dd]

    # rank-pre / dedup-near-clones at rho>=0.85, keeping higher IS Sharpe
    sh = _ann_sharpe(R).dropna()
    if sh.empty:
        return R, signs
    R = R[sh.index]
    if R.shape[1] > max(K_CLUSTERS, 8):
        keep_metric = {k: float(v) for k, v in sh.items()}
        kept = correlation_dedup(R, threshold=DEDUP_RHO, keep_metric=keep_metric)
        if isinstance(kept, list) and len(kept) >= max(K_CLUSTERS, 4):
            R = R[kept]
    return R, signs


# ------------------------------ contract ----------------------------------

def select_members(alpha_index: pd.DataFrame) -> list[str]:
    R, _signs = _filtered_returns(RUN_ID)
    if R is None or R.shape[1] < 2:
        # fallback: pure top-IS-Sharpe from submittable
        ids = list(select_is_submittable(RUN_ID) or [])
        if len(ids) < 2:
            return ids
        signs = member_signs_ic(RUN_ID, ids, dead_band=0.005) or {}
        Rb = load_member_is_returns(RUN_ID, ids, signs=signs)
        if Rb is None or Rb.shape[1] < 2:
            return ids[: min(6, len(ids))]
        sh = _ann_sharpe(Rb).dropna().sort_values(ascending=False)
        n_take = max(2, min(K_CLUSTERS, len(sh)))
        return list(sh.head(n_take).index)

    cols = list(R.columns)
    sh = _ann_sharpe(R)

    # If we still have fewer than K members, just return them all
    if len(cols) <= K_CLUSTERS:
        return cols

    labels = _ward_cluster_labels(R, K_CLUSTERS)

    by_cluster: dict[int, list[str]] = {}
    for col, lab in zip(cols, labels):
        by_cluster.setdefault(int(lab), []).append(col)

    reps: list[str] = []
    for members in by_cluster.values():
        best = None
        best_sh = -math.inf
        for m in members:
            v = sh.get(m, np.nan)
            if v is None or not np.isfinite(v):
                continue
            if float(v) > best_sh:
                best_sh = float(v)
                best = m
        if best is None and members:
            best = members[0]
        if best is not None:
            reps.append(best)

    # Order by IS Sharpe desc; cap to K_CLUSTERS
    reps = sorted(reps, key=lambda m: -float(sh.get(m, -np.inf)) if np.isfinite(sh.get(m, np.nan)) else math.inf)
    reps = reps[:K_CLUSTERS]
    if len(reps) < 2:
        # ultimate fallback
        ranked = sh.dropna().sort_values(ascending=False)
        reps = list(ranked.head(max(2, K_CLUSTERS)).index)
    return reps


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    if not member_ids:
        return {}
    n = len(member_ids)

    # 1) start equal-weight over the centroid representatives
    coef: dict[str, float] = {m: 1.0 / float(n) for m in member_ids}

    # 2) flip IC<0 members so they contribute their deployable direction
    signs = member_signs_ic(RUN_ID, member_ids, dead_band=0.005) or {}
    # apply_signs takes dict of int signs; make sure each member has one
    signs = {m: int(signs.get(m, 1)) or 1 for m in member_ids}
    coef = apply_signs(coef, signs)

    # 3) L1-normalize coefficients (sum |c| = 1)
    coef = normalize_coefficients(coef, "l1")

    # 4) Aggressively rescale to hit target mean row L1 ~ TARGET_GROSS.
    #    Estimate realized gross as Σ_a |c_a| * σ(W_a) where σ(W_a) is the
    #    daily std of the (signed) per-alpha weight-stream returns.
    R = load_member_is_returns(RUN_ID, member_ids, signs=signs)
    scale = 8.0  # safe-ish default if estimation fails
    if R is not None and R.shape[1] > 0:
        sig = R.std(ddof=1)
        sig = sig.replace([np.inf, -np.inf], np.nan).fillna(0.0)
        est_gross = 0.0
        for m in member_ids:
            est_gross += abs(float(coef.get(m, 0.0))) * float(sig.get(m, 0.0))
        if est_gross > 1e-9:
            scale = TARGET_GROSS / est_gross
            # clamp to keep things sane: don't go below 1x (don't shrink an
            # already-tiny exposure), don't blow past 50x
            scale = max(1.0, min(scale, 50.0))

    coef = {k: float(v) * float(scale) for k, v in coef.items()}
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