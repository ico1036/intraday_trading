"""Empirical-Bayes Sharpe shrinkage + Ward cluster centroids + drawdown-disciplined year-stable selection, cov-free equal-weight composition (Efron-Morris 1973; Ward 1963; Lo 2002 Sharpe sampling variance; Lopez de Prado 2016 cluster representatives)."""
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
)

COMPOSITE_ID = "auto_089_eb_sharpe_ward_centroid_k6_dd22_yearstab"
COMPOSITION_NOTE = "eb_sharpe_ward_centroid_k6_dd22_yearstable_eqw_boost9"

RUN_ID = "run_2026_05_c"
N_CLUSTERS = 6
RHO_DEDUP = 0.85
MAX_DD = 0.22
MIN_YEAR_SHARPE = 0.0
BOOST = 9.0  # post-equal-weight multiplier so mean row L1 lands in [0.5, 0.9]


def _eb_shrunk_sharpe(R: pd.DataFrame) -> dict[str, float]:
    """Efron-Morris empirical-Bayes shrinkage of annualized Sharpe toward grand mean.

    Sampling variance of annualized Sharpe ≈ (1 + 0.5·sh²) · 252 / T  (Lo 2002).
    """
    n = max(int(R.shape[0]), 1)
    mu = R.mean()
    sd = R.std().replace(0.0, np.nan)
    raw = (mu / sd * math.sqrt(252.0)).fillna(0.0)
    grand = float(raw.mean())
    samp_var = (1.0 + 0.5 * raw.pow(2)) * (252.0 / float(n))
    between = float(max(float(raw.var()) - float(samp_var.mean()), 1e-6))
    shrink = samp_var / (samp_var + between)
    shrunk = (1.0 - shrink) * raw + shrink * grand
    return {str(k): float(v) for k, v in shrunk.to_dict().items()}


def _year_stable(R: pd.DataFrame, min_sh: float) -> list[str]:
    """Keep alphas with per-year Sharpe ≥ min_sh in every IS sub-year."""
    idx = R.index
    if not isinstance(idx, pd.DatetimeIndex):
        try:
            idx = pd.to_datetime(idx)
        except Exception:
            return list(R.columns)
    years = sorted({int(y) for y in idx.year})
    if len(years) < 2:
        return list(R.columns)
    keep: list[str] = []
    for col in R.columns:
        ok = True
        for y in years:
            mask = (idx.year == y)
            sub = R[col].loc[mask].dropna()
            if len(sub) < 20:
                continue
            std = float(sub.std())
            if std <= 0.0 or not math.isfinite(std):
                ok = False
                break
            sh = float(sub.mean()) / std * math.sqrt(252.0)
            if not math.isfinite(sh) or sh < min_sh:
                ok = False
                break
        if ok:
            keep.append(col)
    return keep


def _dd_filter(R: pd.DataFrame, max_dd: float) -> list[str]:
    """Keep alphas whose max IS drawdown is no worse than -|max_dd|."""
    keep: list[str] = []
    for col in R.columns:
        rs = R[col].fillna(0.0)
        eq = (1.0 + rs).cumprod()
        peak = eq.cummax()
        denom = peak.replace(0.0, np.nan)
        dd = (eq - peak) / denom
        if dd.notna().any():
            worst = float(dd.min())
        else:
            worst = 0.0
        if not math.isfinite(worst):
            continue
        if worst >= -abs(max_dd):
            keep.append(col)
    return keep


def _ward_clusters(R: pd.DataFrame, k: int) -> dict[str, int]:
    """Average-linkage hierarchical clusters on correlation distance."""
    corr = R.corr().fillna(0.0)
    M = corr.values.copy().astype(float)
    np.fill_diagonal(M, 1.0)
    M = np.clip(0.5 * (1.0 - M), 0.0, 1.0)
    d = np.sqrt(M)
    np.fill_diagonal(d, 0.0)
    d = 0.5 * (d + d.T)
    cond = ssd.squareform(d, checks=False)
    Z = sch.linkage(cond, method="average")
    labels = sch.fcluster(Z, t=k, criterion="maxclust")
    return {col: int(labels[i]) for i, col in enumerate(R.columns)}


def _fallback_topn(alpha_index: pd.DataFrame, n: int) -> list[str]:
    if alpha_index is None or alpha_index.empty:
        return []
    df = alpha_index.copy()
    if "is_sharpe" in df.columns:
        df = df.sort_values("is_sharpe", ascending=False)
    return df["alpha_id"].head(n).tolist()


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    ids = select_is_submittable(RUN_ID)
    if not ids or len(ids) < max(N_CLUSTERS, 4):
        ids2 = select_all_alphas(RUN_ID)
        if ids2:
            ids = ids2
    if not ids:
        return _fallback_topn(alpha_index, 6)

    signs = member_signs_ic(RUN_ID, ids)
    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    if R is None or R.empty or R.shape[1] < 2:
        return _fallback_topn(alpha_index, 6)

    cols = _year_stable(R, MIN_YEAR_SHARPE)
    if len(cols) >= max(N_CLUSTERS, 4):
        R = R[cols]

    cols = _dd_filter(R, MAX_DD)
    if len(cols) >= max(N_CLUSTERS, 4):
        R = R[cols]
    elif len(cols) >= 2:
        R = R[cols]

    if R.shape[1] < 2:
        return _fallback_topn(alpha_index, 6)

    eb_sh = _eb_shrunk_sharpe(R)

    try:
        kept = correlation_dedup(R, threshold=RHO_DEDUP, keep_metric=eb_sh)
    except Exception:
        kept = list(R.columns)
    if not kept or len(kept) < 2:
        kept = list(R.columns)
    R = R[kept]

    k = int(min(N_CLUSTERS, R.shape[1]))
    if k <= 1:
        return _fallback_topn(alpha_index, 6)

    if R.shape[1] <= k:
        chosen = list(R.columns)
    else:
        try:
            labels = _ward_clusters(R, k)
        except Exception:
            chosen = sorted(R.columns, key=lambda c: -float(eb_sh.get(c, 0.0)))[:k]
            return chosen
        by_cluster: dict[int, tuple[str, float]] = {}
        for col, lab in labels.items():
            sc = float(eb_sh.get(col, 0.0))
            cur = by_cluster.get(lab)
            if cur is None or sc > cur[1]:
                by_cluster[lab] = (col, sc)
        chosen = [v[0] for v in by_cluster.values()]

    if len(chosen) < 2:
        chosen = sorted(R.columns, key=lambda c: -float(eb_sh.get(c, 0.0)))[:max(4, k)]

    return chosen


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    if not member_ids:
        return {}
    signs = member_signs_ic(RUN_ID, member_ids)
    k = max(len(member_ids), 1)
    base = {a: 1.0 / float(k) for a in member_ids}
    signed = apply_signs(base, signs)
    coef = {a: float(v) * BOOST for a, v in signed.items()}
    for a in member_ids:
        if a not in coef:
            coef[a] = 0.0
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