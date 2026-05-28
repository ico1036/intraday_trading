"""Ward hierarchical clustering (Murtagh 1985 / Raffinot 2018 HERC-adjacent) on
regime-stable IS returns; cov-free cluster-centroid equal-weight composition."""
from __future__ import annotations
import argparse
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
    member_is_sharpe,
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_069_ward_cluster_centroid_yearstable_dd25_k6"
COMPOSITION_NOTE = "ward_cluster_centroid_yearstable_dd25_k6_eqw_gross070"

RUN_ID = "run_2026_05_c"
N_CLUSTERS = 6
DD_LIMIT = 0.25
DEDUP_RHO = 0.85
TARGET_GROSS = 0.70
MIN_IS_SHARPE = 0.40
MIN_ALPHAS_AFTER_FILTER = 8
SCALE_CAP = 50.0


def _max_drawdown(s: pd.Series) -> float:
    x = s.fillna(0.0).astype(float)
    eq = (1.0 + x).cumprod()
    peak = eq.cummax()
    dd = (eq - peak) / peak.replace(0.0, np.nan)
    m = dd.min()
    if not np.isfinite(m):
        return 0.0
    return float(-m)


def _per_year_positive(R: pd.DataFrame) -> list[str]:
    idx = R.index
    if not isinstance(idx, pd.DatetimeIndex):
        try:
            idx = pd.to_datetime(idx)
        except Exception:
            return list(R.columns)
    years = sorted(set(idx.year.tolist()))
    if len(years) < 2:
        return list(R.columns)
    keep = []
    for col in R.columns:
        ok = True
        for y in years:
            sub = R[col].loc[idx.year == y]
            sub = sub.dropna()
            if len(sub) < 10:
                continue
            mu = float(sub.mean())
            sd = float(sub.std())
            if sd <= 1e-12 or mu <= 0.0:
                ok = False
                break
        if ok:
            keep.append(col)
    return keep


def _dd_filter(R: pd.DataFrame, limit: float) -> list[str]:
    return [c for c in R.columns if _max_drawdown(R[c]) <= limit]


def _ward_clusters(R: pd.DataFrame, k: int) -> dict[int, list[str]]:
    corr = R.corr().fillna(0.0).clip(-1.0, 1.0).values
    dist = np.sqrt(np.maximum(0.0, 0.5 * (1.0 - corr)))
    np.fill_diagonal(dist, 0.0)
    cond = ssd.squareform(dist, checks=False)
    Z = sch.linkage(cond, method="ward")
    K = max(2, min(k, R.shape[1]))
    labels = sch.fcluster(Z, t=K, criterion="maxclust")
    out: dict[int, list[str]] = {}
    cols = list(R.columns)
    for i, l in enumerate(labels.tolist()):
        out.setdefault(int(l), []).append(cols[i])
    return out


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    ids = select_is_submittable(RUN_ID)
    if not ids or len(ids) < MIN_ALPHAS_AFTER_FILTER:
        ids = select_all_alphas(RUN_ID)
    if not ids:
        return []

    signs = member_signs_ic(RUN_ID, ids)
    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    if R is None or R.empty or R.shape[1] < 2:
        return list(R.columns) if R is not None else []

    sharpe_map = member_is_sharpe(RUN_ID, list(R.columns))
    strong = [c for c in R.columns if float(sharpe_map.get(c, 0.0)) >= MIN_IS_SHARPE]
    if len(strong) < MIN_ALPHAS_AFTER_FILTER:
        ranked = sorted(R.columns, key=lambda c: float(sharpe_map.get(c, 0.0)), reverse=True)
        strong = ranked[: max(MIN_ALPHAS_AFTER_FILTER, len(ranked) // 4)]
    R = R[strong]

    yr_keep = _per_year_positive(R)
    if len(yr_keep) >= max(N_CLUSTERS, 6):
        R = R[yr_keep]

    dd_keep = _dd_filter(R, DD_LIMIT)
    if len(dd_keep) >= max(N_CLUSTERS, 6):
        R = R[dd_keep]

    keep_metric = {c: float(sharpe_map.get(c, 0.0)) for c in R.columns}
    if R.shape[1] > 30:
        try:
            deduped = correlation_dedup(R, DEDUP_RHO, keep_metric=keep_metric)
            if len(deduped) >= N_CLUSTERS:
                R = R[deduped]
        except Exception:
            pass

    if R.shape[1] <= N_CLUSTERS:
        return list(R.columns)

    try:
        clusters = _ward_clusters(R, N_CLUSTERS)
        chosen: list[str] = []
        for cl_id in sorted(clusters.keys()):
            mems = clusters[cl_id]
            best = max(mems, key=lambda c: keep_metric.get(c, 0.0))
            chosen.append(best)
        chosen = list(dict.fromkeys(chosen))
        if len(chosen) >= 2:
            return chosen
    except Exception:
        pass

    ranked = sorted(R.columns, key=lambda c: keep_metric.get(c, 0.0), reverse=True)
    return ranked[: N_CLUSTERS]


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    if not member_ids:
        return {}

    signs = member_signs_ic(RUN_ID, member_ids)
    R = load_member_is_returns(RUN_ID, member_ids, signs=signs)

    coef = {m: 1.0 for m in member_ids}
    coef = normalize_coefficients(coef, "l1")

    if R is not None and not R.empty:
        loaded = [c for c in member_ids if c in R.columns]
        if loaded:
            sigma_a = R[loaded].std().fillna(0.0)
            est_gross = float(
                sum(abs(coef.get(m, 0.0)) * float(sigma_a.get(m, 0.0)) for m in loaded)
            )
            if est_gross > 1e-9:
                scale = TARGET_GROSS / est_gross
                if not np.isfinite(scale) or scale <= 0:
                    scale = 10.0
                scale = float(min(scale, SCALE_CAP))
                coef = {k: v * scale for k, v in coef.items()}
            else:
                coef = {k: v * 10.0 for k, v in coef.items()}
    else:
        coef = {k: v * 10.0 for k, v in coef.items()}

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