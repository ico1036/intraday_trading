"""
Ward hierarchical-clustering composite on correlation distance with
per-year IS Sharpe stability gate and drawdown discipline. Cite:
Lopez de Prado (2016, HRP) correlation-distance d_ij = sqrt(0.5*(1-rho_ij))
+ Murtagh (1985) Ward linkage. Cut dendrogram at K clusters, pick the
single highest-IS-Sharpe alpha per cluster as the centroid representative,
equal-weight (|c|=1 each, IC-sign aligned). Bypasses the 1/sigma-
weighting trap of cov-inverse methods that produced anemic gross
exposure (<0.1) in prior iterations; preserves native member leverage
via Sigma|c| = K and lets the runner row-L1 clamp do the rest.
"""
from __future__ import annotations
import argparse

import numpy as np
import pandas as pd
import scipy.cluster.hierarchy as sch
import scipy.spatial.distance as ssd

from intraday.composites._runner import build_and_backtest
from intraday.composites._optim_helpers import (
    member_signs_ic,
    apply_signs,
    select_is_submittable,
    load_member_is_returns,
)

COMPOSITE_ID = "auto_107_ward_corr_dist_k6_centroid_yearstable_dd"
COMPOSITION_NOTE = "ward_corr_dist_k6_centroid_yearstable_dd25_eqw"

RUN_ID = "run_2026_05_c"
N_CLUSTERS = 6
DD_THRESHOLD = 0.25
PER_YEAR_FLOOR = 0.0
MIN_DAYS_PER_YEAR = 25
MIN_IS_SHARPE = 0.5
SHARPE_TILT_CLIP = 2.0


def _is_sharpe(returns: pd.Series) -> float:
    s = returns.dropna()
    if len(s) < 20:
        return 0.0
    sd = float(s.std(ddof=1))
    if sd <= 0.0:
        return 0.0
    return float(s.mean() / sd * np.sqrt(365.0))


def _max_drawdown(returns: pd.Series) -> float:
    s = returns.dropna()
    if s.empty:
        return 1.0
    eq = (1.0 + s).cumprod()
    peak = eq.cummax()
    dd = (eq / peak) - 1.0
    return float(-dd.min())


def _per_year_sharpe(returns: pd.Series) -> dict:
    s = returns.dropna()
    if s.empty:
        return {}
    idx = pd.to_datetime(s.index)
    out: dict = {}
    for year in sorted(set(int(y) for y in idx.year.tolist())):
        mask = (idx.year == year)
        x = s.values[mask]
        if len(x) < MIN_DAYS_PER_YEAR:
            continue
        mu = float(np.mean(x))
        sd = float(np.std(x, ddof=1))
        out[int(year)] = (mu / sd * np.sqrt(365.0)) if sd > 0.0 else 0.0
    return out


def _filter_stable(R: pd.DataFrame) -> list:
    kept: list = []
    for a in R.columns:
        ret = R[a]
        py = _per_year_sharpe(ret)
        if len(py) < 2:
            continue
        if any(v <= PER_YEAR_FLOOR for v in py.values()):
            continue
        if _max_drawdown(ret) > DD_THRESHOLD:
            continue
        if _is_sharpe(ret) < MIN_IS_SHARPE:
            continue
        kept.append(a)
    return kept


def _ward_centroid_pick(R: pd.DataFrame, k: int) -> list:
    cols = list(R.columns)
    if len(cols) <= k:
        return cols
    corr = R.corr().clip(-1.0, 1.0).fillna(0.0).values
    np.fill_diagonal(corr, 1.0)
    dist = np.sqrt(np.clip(0.5 * (1.0 - corr), 0.0, 1.0))
    np.fill_diagonal(dist, 0.0)
    dist = 0.5 * (dist + dist.T)
    try:
        condensed = ssd.squareform(dist, checks=False)
        Z = sch.linkage(condensed, method="ward")
        labels = sch.fcluster(Z, t=k, criterion="maxclust")
    except Exception:
        sharpe_map = {a: _is_sharpe(R[a]) for a in cols}
        return sorted(cols, key=lambda a: sharpe_map.get(a, 0.0), reverse=True)[:k]
    sharpe_map = {a: _is_sharpe(R[a]) for a in cols}
    picks: list = []
    for c in sorted({int(x) for x in labels}):
        members = [cols[i] for i in range(len(labels)) if int(labels[i]) == c]
        members.sort(key=lambda a: sharpe_map.get(a, 0.0), reverse=True)
        if members:
            picks.append(members[0])
    return picks


def _load_universe():
    ids_all = select_is_submittable(RUN_ID) or []
    if len(ids_all) < 5:
        return None, {}
    signs = member_signs_ic(RUN_ID, ids_all) or {}
    R = load_member_is_returns(RUN_ID, ids_all, signs=signs)
    return R, signs


def select_members(alpha_index: pd.DataFrame) -> list:
    R, _ = _load_universe()
    if R is None or R.empty:
        ranked = alpha_index.sort_values("is_sharpe", ascending=False)
        out = ranked["alpha_id"].astype(str).head(N_CLUSTERS).tolist()
        return out if len(out) >= 2 else ranked["alpha_id"].astype(str).head(2).tolist()
    kept = _filter_stable(R)
    if len(kept) < N_CLUSTERS:
        relaxed = []
        for a in R.columns:
            py = _per_year_sharpe(R[a])
            if py and all(v > 0.0 for v in py.values()) and _is_sharpe(R[a]) >= 0.4:
                relaxed.append(a)
        kept = relaxed
    if len(kept) < N_CLUSTERS:
        sharpe_map = {a: _is_sharpe(R[a]) for a in R.columns}
        kept = sorted(R.columns, key=lambda a: sharpe_map.get(a, 0.0), reverse=True)[: max(3 * N_CLUSTERS, 18)]
    R_kept = R[kept]
    picks = _ward_centroid_pick(R_kept, N_CLUSTERS)
    if len(picks) < 2:
        sharpe_map = {a: _is_sharpe(R[a]) for a in R.columns}
        picks = sorted(R.columns, key=lambda a: sharpe_map.get(a, 0.0), reverse=True)[:N_CLUSTERS]
    return list(picks)


def member_weights(member_ids: list, alpha_index: pd.DataFrame) -> dict:
    if not member_ids:
        return {}
    signs_raw = member_signs_ic(RUN_ID, member_ids) or {}
    signs = {a: int(signs_raw.get(a, 1)) for a in member_ids}
    coef = {a: 1.0 for a in member_ids}
    R = load_member_is_returns(RUN_ID, member_ids, signs=signs)
    if R is not None and not R.empty:
        sharpe_map = {a: max(_is_sharpe(R[a]), 0.1) for a in member_ids}
        avg_sh = float(np.mean(list(sharpe_map.values())))
        if avg_sh > 0.0:
            for a in member_ids:
                tilt = sharpe_map.get(a, avg_sh) / avg_sh
                tilt = float(min(max(tilt, 1.0 / SHARPE_TILT_CLIP), SHARPE_TILT_CLIP))
                coef[a] = coef[a] * tilt
    coef = apply_signs(coef, signs)
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