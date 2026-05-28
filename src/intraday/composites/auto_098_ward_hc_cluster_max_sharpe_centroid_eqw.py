"""Ward-agglomerative HC on correlation distance with cluster max-IS-Sharpe centroid + cov-free equal-weight (Ward 1963; Lopez de Prado NCO clustering insight); per-year IS-Sharpe stability + max IS DD<25% regime filters; native-exposure post-scaling to mean row L1 ≈ 0.70 to bypass the 1/sigma underweighting trap."""
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

COMPOSITE_ID = "auto_098_ward_hc_cluster_max_sharpe_centroid_eqw"
COMPOSITION_NOTE = "ward_hc_cluster_max_sharpe_centroid_eqw_yearstable_dd25_k6_gross070"

RUN_ID = "run_2026_05_c"
N_CLUSTERS = 6
DD_HARD = 0.25
DD_SOFT = 0.35
DEDUP_RHO = 0.85
MIN_OBS = 60
MIN_OBS_YEAR = 30
TARGET_GROSS = 0.70
SCALE_MIN = 1.0
SCALE_MAX = 30.0


def _annualized_sharpe(returns: pd.Series) -> float:
    r = returns.dropna()
    if len(r) < MIN_OBS:
        return 0.0
    s = float(r.std())
    if not np.isfinite(s) or s <= 0.0:
        return 0.0
    return float(r.mean() / s * math.sqrt(252.0))


def _max_drawdown(returns: pd.Series) -> float:
    r = returns.fillna(0.0)
    if len(r) == 0:
        return 1.0
    eq = (1.0 + r).cumprod()
    peak = eq.cummax()
    dd = eq / peak - 1.0
    val = dd.min()
    if not np.isfinite(val):
        return 1.0
    return float(-val)


def _ensure_datetime_index(s: pd.Series) -> pd.Series:
    if isinstance(s.index, pd.DatetimeIndex):
        return s
    try:
        out = s.copy()
        out.index = pd.to_datetime(out.index)
        return out
    except Exception:
        return s


def _year_stable(returns: pd.Series) -> bool:
    r = _ensure_datetime_index(returns).dropna()
    if not isinstance(r.index, pd.DatetimeIndex) or len(r) < MIN_OBS:
        return False
    checked = 0
    for _, sub in r.groupby(r.index.year):
        if len(sub) < MIN_OBS_YEAR:
            continue
        s = float(sub.std())
        if not np.isfinite(s) or s <= 0.0:
            return False
        if sub.mean() / s <= 0.0:
            return False
        checked += 1
    return checked >= 2


def _filter_strict(R: pd.DataFrame) -> list[str]:
    keep: list[str] = []
    for col in R.columns:
        s = R[col]
        if s.dropna().shape[0] < MIN_OBS:
            continue
        if _max_drawdown(s) >= DD_HARD:
            continue
        if _annualized_sharpe(s) <= 0.3:
            continue
        if not _year_stable(s):
            continue
        keep.append(col)
    return keep


def _filter_relaxed(R: pd.DataFrame) -> list[str]:
    keep: list[str] = []
    for col in R.columns:
        s = R[col]
        if s.dropna().shape[0] < MIN_OBS:
            continue
        if _max_drawdown(s) >= DD_SOFT:
            continue
        if _annualized_sharpe(s) <= 0.15:
            continue
        keep.append(col)
    return keep


def _ward_centroids(R: pd.DataFrame, sharpes: dict[str, float], k: int) -> list[str]:
    cols = list(R.columns)
    n = len(cols)
    if n <= k:
        return cols
    corr = R.fillna(0.0).corr().fillna(0.0).values
    np.fill_diagonal(corr, 1.0)
    dist = np.sqrt(np.clip(0.5 * (1.0 - corr), 0.0, 1.0))
    np.fill_diagonal(dist, 0.0)
    dist = 0.5 * (dist + dist.T)
    condensed = ssd.squareform(dist, checks=False)
    linkage = sch.linkage(condensed, method="ward")
    labels = sch.fcluster(linkage, t=k, criterion="maxclust")
    chosen: list[str] = []
    for cl in range(1, int(labels.max()) + 1):
        members = [cols[i] for i in range(n) if labels[i] == cl]
        if not members:
            continue
        best = max(members, key=lambda c: sharpes.get(c, 0.0))
        chosen.append(best)
    return chosen


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    ids = select_is_submittable(RUN_ID)
    if ids is None or len(ids) < N_CLUSTERS:
        ids = select_all_alphas(RUN_ID)
    if ids is None or len(ids) == 0:
        return []

    signs = member_signs_ic(RUN_ID, ids)
    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    if R is None or R.shape[1] < 2:
        return list(R.columns) if (R is not None and R.shape[1] >= 2) else ids[: N_CLUSTERS]

    strict = _filter_strict(R)
    if len(strict) < N_CLUSTERS:
        relaxed = _filter_relaxed(R)
        pool = relaxed if len(relaxed) >= N_CLUSTERS else list(R.columns)
    else:
        pool = strict

    sharpes_all = {c: _annualized_sharpe(R[c]) for c in pool}
    if len(pool) < N_CLUSTERS:
        ranked = sorted(R.columns, key=lambda c: _annualized_sharpe(R[c]), reverse=True)
        chosen = ranked[: max(N_CLUSTERS, 4)]
        return chosen

    R_pool = R[pool]
    try:
        deduped = correlation_dedup(R_pool, threshold=DEDUP_RHO, keep_metric=sharpes_all)
    except Exception:
        deduped = list(pool)
    if not isinstance(deduped, list) or len(deduped) < N_CLUSTERS:
        deduped = list(pool)

    R_d = R[deduped]
    sharpes_d = {c: sharpes_all.get(c, _annualized_sharpe(R_d[c])) for c in deduped}

    try:
        centroids = _ward_centroids(R_d, sharpes_d, N_CLUSTERS)
    except Exception:
        centroids = sorted(sharpes_d, key=lambda c: sharpes_d.get(c, 0.0), reverse=True)[: N_CLUSTERS]

    if len(centroids) < 2:
        centroids = sorted(sharpes_d, key=lambda c: sharpes_d.get(c, 0.0), reverse=True)[: max(N_CLUSTERS, 4)]
    # Dedup and preserve order
    seen: set[str] = set()
    out: list[str] = []
    for c in centroids:
        if c not in seen:
            out.append(c)
            seen.add(c)
    return out


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    if not member_ids:
        return {}

    signs = member_signs_ic(RUN_ID, member_ids)
    R = load_member_is_returns(RUN_ID, member_ids, signs=signs)
    if R is None or R.shape[1] == 0:
        coef = {m: 1.0 for m in member_ids}
        coef = normalize_coefficients(coef, "l1")
        coef = {k: v * 10.0 for k, v in coef.items()}
        return apply_signs(coef, signs)

    loaded = [m for m in member_ids if m in R.columns]
    if len(loaded) == 0:
        loaded = list(R.columns)

    coef = {m: 1.0 for m in loaded}
    coef = normalize_coefficients(coef, "l1")

    sigma_a = R[loaded].std()
    sigma_vec = np.array([float(sigma_a.get(m, 0.0)) for m in loaded])
    coef_vec = np.array([coef[m] for m in loaded])
    if np.all(np.isfinite(sigma_vec)) and float(np.sum(np.abs(sigma_vec))) > 0.0:
        est_gross = float(np.sum(np.abs(coef_vec) * sigma_vec))
        if est_gross > 0.0:
            scale = TARGET_GROSS / max(est_gross, 1e-6)
        else:
            scale = 10.0
    else:
        scale = 10.0
    scale = float(np.clip(scale, SCALE_MIN, SCALE_MAX))
    coef = {k: v * scale for k, v in coef.items()}

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