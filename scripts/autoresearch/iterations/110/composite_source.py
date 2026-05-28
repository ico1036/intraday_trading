"""Ward hierarchical clustering on IS-correlation distance with single
highest-IS-Sharpe centroid per cluster, equal-magnitude sign-aligned
combination (cov-free). Method: Lopez de Prado (2016) HRP-style
distance d = sqrt(0.5*(1-rho)), Ward linkage (Murtagh & Legendre 2014)
for centroid identification, regime-robust selection via per-year IS
Sharpe stability and IS max-drawdown discipline. No covariance inversion
-> avoids the 1/sigma-weighted gross-exposure trap of tangency/min-var."""
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
    select_is_submittable,
    select_all_alphas,
    load_member_is_returns,
)

COMPOSITE_ID = "auto_110_ward_centroid_eqw_signaligned_yearstable"
COMPOSITION_NOTE = "ward_centroid_eqw_signaligned_yearstable_dd25_k6"

RUN_ID = "run_2026_05_c"
N_CLUSTERS = 6
DD_THRESHOLD = 0.25
DEDUP_RHO = 0.92
MIN_DAYS = 60


def _is_sharpe(returns: pd.Series) -> float:
    s = returns.std()
    if not np.isfinite(s) or s <= 0.0:
        return -np.inf
    return float(np.sqrt(252.0) * returns.mean() / s)


def _max_drawdown(returns: pd.Series) -> float:
    if returns.empty:
        return 1.0
    eq = (1.0 + returns.fillna(0.0)).cumprod()
    peak = eq.cummax()
    dd = (eq / peak) - 1.0
    mn = dd.min()
    if not np.isfinite(mn):
        return 1.0
    return float(-mn)


def _year_stable(returns: pd.Series) -> bool:
    if returns.empty:
        return False
    n_full = 0
    for _, g in returns.groupby(returns.index.year):
        if len(g) < 20:
            continue
        n_full += 1
        if _is_sharpe(g) <= 0.0:
            return False
    return n_full >= 2


def _regime_filter(R: pd.DataFrame) -> list[str]:
    keep: list[str] = []
    for col in R.columns:
        s = R[col].dropna()
        if len(s) < MIN_DAYS:
            continue
        if _is_sharpe(s) <= 0.0:
            continue
        if _max_drawdown(s) >= DD_THRESHOLD:
            continue
        if not _year_stable(s):
            continue
        keep.append(col)
    return keep


def _ward_centroids(R_kept: pd.DataFrame, k: int) -> list[str]:
    cols = list(R_kept.columns)
    if len(cols) <= k:
        return cols
    corr = R_kept.corr().fillna(0.0).values
    corr = np.clip(corr, -1.0, 1.0)
    dist = np.sqrt(np.maximum(0.0, 0.5 * (1.0 - corr)))
    np.fill_diagonal(dist, 0.0)
    dist = 0.5 * (dist + dist.T)
    condensed = ssd.squareform(dist, checks=False)
    Z = sch.linkage(condensed, method="ward")
    labels = sch.fcluster(Z, t=k, criterion="maxclust")
    sharpes = {c: _is_sharpe(R_kept[c].dropna()) for c in cols}
    chosen: list[str] = []
    for cl in sorted(set(labels)):
        members = [cols[i] for i, lab in enumerate(labels) if lab == cl]
        if not members:
            continue
        best = max(members, key=lambda a: sharpes.get(a, -np.inf))
        chosen.append(best)
    return chosen


_CACHE: dict[str, object] = {}


def _resolve() -> tuple[list[str], dict[str, int]]:
    if "centroids" in _CACHE and "signs" in _CACHE:
        return _CACHE["centroids"], _CACHE["signs"]  # type: ignore[return-value]

    try:
        ids = select_is_submittable(RUN_ID)
    except Exception:
        ids = []
    if not ids or len(ids) < N_CLUSTERS + 2:
        try:
            ids = select_all_alphas(RUN_ID)
        except Exception:
            ids = ids or []

    signs = member_signs_ic(RUN_ID, ids) if ids else {}
    R = load_member_is_returns(RUN_ID, ids, signs=signs) if ids else pd.DataFrame()
    if isinstance(R, pd.DataFrame) and not R.empty:
        R = R.dropna(how="all", axis=1)

    if R.empty or R.shape[1] < 2:
        _CACHE["centroids"] = list(R.columns) if not R.empty else []
        _CACHE["signs"] = signs
        return _CACHE["centroids"], _CACHE["signs"]  # type: ignore[return-value]

    kept = _regime_filter(R)
    if len(kept) < N_CLUSTERS + 2:
        kept = [c for c in R.columns if _is_sharpe(R[c].dropna()) > 0.0]
    if len(kept) < 2:
        kept = list(R.columns)
    R_kept = R[kept].copy()

    keep_metric = {c: _is_sharpe(R_kept[c].dropna()) for c in R_kept.columns}
    try:
        deduped = correlation_dedup(R_kept, threshold=DEDUP_RHO, keep_metric=keep_metric)
        if isinstance(deduped, list) and len(deduped) >= max(N_CLUSTERS, 2):
            R_kept = R_kept[deduped]
    except Exception:
        pass

    try:
        centroids = _ward_centroids(R_kept, N_CLUSTERS)
    except Exception:
        centroids = []

    if len(centroids) < 2:
        ranked = sorted(
            R_kept.columns,
            key=lambda c: _is_sharpe(R_kept[c].dropna()),
            reverse=True,
        )
        centroids = ranked[: max(N_CLUSTERS, 2)]

    _CACHE["centroids"] = centroids
    _CACHE["signs"] = signs
    return centroids, signs


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    centroids, _ = _resolve()
    return list(centroids)


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    _, signs = _resolve()
    coef: dict[str, float] = {}
    for a in member_ids:
        s = int(signs.get(a, 1)) if signs else 1
        if s == 0:
            s = 1
        coef[a] = 1.0 * float(s)
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