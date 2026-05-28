"""Ward hierarchical clustering (Ward 1963) with per-cluster IS-Sharpe centroid selection and equal-weight 1/K allocation. Cov-free composition with regime-robust filters (year-stable IS Sharpe, max-DD discipline) and explicit gross-exposure rescale to circumvent the 1/sigma cov-inversion trap."""
from __future__ import annotations

import argparse
import math
import numpy as np
import pandas as pd
import scipy.cluster.hierarchy as sch
import scipy.spatial.distance as ssd

from intraday.composites._runner import build_and_backtest
from intraday.composites._optim_helpers import (
    select_is_submittable,
    select_all_alphas,
    member_signs_ic,
    apply_signs,
    load_member_is_returns,
    normalize_coefficients,
    member_is_sharpe,
)

COMPOSITE_ID = "auto_086_ward_cluster_centroid_yearstable_dd25_k6"
COMPOSITION_NOTE = "ward_cluster_centroid_yearstable_dd25_k6_eqweight_gross070"

RUN_ID = "run_2026_05_c"
K_CLUSTERS = 6
DD_TIGHT = 0.25
DD_LOOSE = 0.35
MIN_YEAR_SHARPE_TIGHT = 0.0
MIN_YEAR_SHARPE_LOOSE = -0.20
TARGET_GROSS = 0.70
FALLBACK_SCALE = 10.0


def _max_drawdown(returns: pd.Series) -> float:
    r = returns.fillna(0.0).astype(float)
    eq = (1.0 + r).cumprod()
    peak = eq.cummax()
    dd = (eq / peak) - 1.0
    val = dd.min()
    if not np.isfinite(val):
        return 0.0
    return float(-val)


def _year_stable(returns: pd.Series, min_sharpe: float) -> bool:
    idx = returns.index
    if not isinstance(idx, pd.DatetimeIndex):
        return True
    s = returns.dropna()
    if s.empty:
        return False
    years = sorted(set(int(y) for y in s.index.year))
    if len(years) < 2:
        return True
    for y in years:
        sub = s[s.index.year == y]
        if len(sub) < 20:
            continue
        sd = float(sub.std())
        if not np.isfinite(sd) or sd <= 1e-12:
            return False
        sh = float(sub.mean() / sd * math.sqrt(252.0))
        if not np.isfinite(sh) or sh < min_sharpe:
            return False
    return True


def _candidate_ids() -> list[str]:
    try:
        ids = list(select_is_submittable(RUN_ID))
    except Exception:
        ids = []
    if len(ids) < K_CLUSTERS + 2:
        try:
            extra = list(select_all_alphas(RUN_ID))
        except Exception:
            extra = []
        merged = list(dict.fromkeys(list(ids) + list(extra)))
        ids = merged
    return ids


def _filter_pool(R: pd.DataFrame, dd_thresh: float, year_min: float) -> list[str]:
    kept: list[str] = []
    for col in R.columns:
        s = R[col].dropna()
        if len(s) < 50:
            continue
        if _max_drawdown(s) > dd_thresh:
            continue
        if not _year_stable(s, year_min):
            continue
        kept.append(col)
    return kept


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    candidates = _candidate_ids()
    if len(candidates) < 2:
        return candidates

    try:
        signs0 = member_signs_ic(RUN_ID, candidates)
    except Exception:
        signs0 = {a: 1 for a in candidates}
    R = load_member_is_returns(RUN_ID, candidates, signs=signs0)
    if R is None or R.shape[1] < 2:
        try:
            sh_map = member_is_sharpe(RUN_ID, candidates)
        except Exception:
            sh_map = {}
        ranked = sorted(candidates, key=lambda a: -float(sh_map.get(a, 0.0)))
        return ranked[: max(K_CLUSTERS, 4)]

    kept = _filter_pool(R, DD_TIGHT, MIN_YEAR_SHARPE_TIGHT)
    if len(kept) < K_CLUSTERS:
        kept = _filter_pool(R, DD_LOOSE, MIN_YEAR_SHARPE_LOOSE)
    if len(kept) < K_CLUSTERS:
        kept = list(R.columns)

    Rk = R[kept].copy()
    cols = list(Rk.columns)

    try:
        sh_map = member_is_sharpe(RUN_ID, cols)
    except Exception:
        sh_map = {}

    if len(cols) <= K_CLUSTERS:
        return cols

    corr = Rk.corr().fillna(0.0).values
    n = corr.shape[0]
    if n < 2:
        return cols

    np.fill_diagonal(corr, 1.0)
    dist = np.sqrt(np.clip(0.5 * (1.0 - corr), 0.0, 1.0))
    dist = 0.5 * (dist + dist.T)
    np.fill_diagonal(dist, 0.0)

    try:
        condensed = ssd.squareform(dist, checks=False)
        Z = sch.linkage(condensed, method="ward")
        labels = sch.fcluster(Z, t=K_CLUSTERS, criterion="maxclust")
    except Exception:
        ranked = sorted(cols, key=lambda a: -float(sh_map.get(a, 0.0)))
        return ranked[:K_CLUSTERS]

    chosen: list[str] = []
    for k in np.unique(labels):
        members_k = [cols[i] for i in range(len(cols)) if labels[i] == k]
        if not members_k:
            continue
        members_k.sort(key=lambda a: -float(sh_map.get(a, 0.0)))
        chosen.append(members_k[0])

    if len(chosen) < 2:
        ranked = sorted(cols, key=lambda a: -float(sh_map.get(a, 0.0)))
        chosen = ranked[:K_CLUSTERS]
    return chosen


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    if not member_ids:
        return {}
    try:
        signs = member_signs_ic(RUN_ID, member_ids)
    except Exception:
        signs = {a: 1 for a in member_ids}

    raw = {a: 1.0 for a in member_ids}
    coef = apply_signs(raw, signs)
    coef = normalize_coefficients(coef, "l1")

    scaled = False
    try:
        R = load_member_is_returns(RUN_ID, member_ids, signs=signs)
    except Exception:
        R = None

    if R is not None and R.shape[1] > 0:
        try:
            sigma_a = R.std()
            terms = []
            for a in member_ids:
                ca = float(coef.get(a, 0.0))
                sa = float(sigma_a.get(a, 0.0)) if a in sigma_a.index else 0.0
                if np.isfinite(sa):
                    terms.append(abs(ca) * sa)
            est_gross = float(np.sum(terms))
            if np.isfinite(est_gross) and est_gross > 1e-8:
                scale = TARGET_GROSS / est_gross
                scale = float(np.clip(scale, 1.0, 50.0))
                coef = {k: v * scale for k, v in coef.items()}
                scaled = True
        except Exception:
            scaled = False

    if not scaled:
        coef = {k: v * FALLBACK_SCALE for k, v in coef.items()}

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