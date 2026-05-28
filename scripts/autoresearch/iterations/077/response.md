**Rationale — iter 077: Ward cluster-centroid + Sharpe-tilt + gross-exposure boost (cov-free composition)**

Key empirical signals to exploit:
1. Top winners share **n∈[5,8], year-stability, DD-discipline, ρ-dedup~0.85**.
2. Composite gross-exposure ceiling is the dominant blocker — mean row L1 ≈ 0.05 vs target 0.5–0.7.
3. Cov-free methods unexplored; user explicitly said "high-return focused, not max-div".

This file does NOT repeat auto_013's cluster-median+equal-weight: it uses **highest-IS-Sharpe representative per cluster** (high-return) and **Sharpe-tilt weighting** (not 1/N), plus per-year stability and DD-20 % filters. Method cited: Ward agglomerative clustering on correlation-distance (Lopez de Prado 2016, HRP family; Murtagh & Legendre 2014, Ward-linkage criterion) with centroid selection — cov-free, so it avoids the Σ⁻¹·μ underscaling that has trapped every prior tangency / min-var attempt at gross≈0.05. A final 5× boost on the L1-normalized coefficients pushes mean row L1 into the productive [0.5, 0.9] band per the harness brief; the runner's row-L1 clamp will trim any overshoot.

```python COMPOSITE_FILE
"""Ward cluster-centroid Sharpe-tilt composite: hierarchical correlation clustering (Lopez de Prado 2016 HRP family / Ward 1963 linkage) with highest-IS-Sharpe representative per cluster, sign-aware Sharpe-tilt weighting, year-stability and drawdown filters, explicit gross-exposure rescaling to compensate optimizer underscaling."""
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

COMPOSITE_ID = "auto_077"
COMPOSITION_NOTE = "ward_cluster_centroid_sharpe_tilt_yearstable_dd20_k6_gross5x"

RUN_ID = "run_2026_05_c"
N_CLUSTERS = 6
DD_LIMIT = 0.20
RHO_DEDUP = 0.85
GROSS_BOOST = 5.0


def _year_stable(R: pd.DataFrame) -> list[str]:
    if R.empty or not isinstance(R.index, pd.DatetimeIndex):
        return list(R.columns)
    years = np.asarray(R.index.year)
    uniq = np.unique(years)
    if len(uniq) < 2:
        return list(R.columns)
    keep: list[str] = []
    for col in R.columns:
        vals = R[col].values
        ok = True
        for y in uniq:
            mask = years == y
            if mask.sum() < 20:
                continue
            r = vals[mask]
            sd = float(r.std())
            if sd <= 0 or not np.isfinite(sd):
                ok = False
                break
            sh = float(r.mean()) / sd
            if not np.isfinite(sh) or sh <= 0:
                ok = False
                break
        if ok:
            keep.append(col)
    return keep


def _max_dd(returns: np.ndarray) -> float:
    r = np.nan_to_num(returns, nan=0.0)
    eq = np.cumprod(1.0 + r)
    peak = np.maximum.accumulate(eq)
    safe_peak = np.where(peak > 0, peak, np.nan)
    dd = (eq - peak) / safe_peak
    valid = np.isfinite(dd)
    if not valid.any():
        return 1.0
    return float(-dd[valid].min())


def _dd_filter(R: pd.DataFrame, limit: float) -> list[str]:
    keep: list[str] = []
    for col in R.columns:
        if _max_dd(R[col].values) <= limit:
            keep.append(col)
    return keep


def _is_sharpe_dict(R: pd.DataFrame) -> dict[str, float]:
    out: dict[str, float] = {}
    for col in R.columns:
        v = R[col].values
        sd = float(v.std())
        if sd > 0 and np.isfinite(sd):
            sh = (float(v.mean()) / sd) * math.sqrt(252.0)
            if np.isfinite(sh):
                out[col] = float(sh)
    return out


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    ids = select_is_submittable(RUN_ID)
    if len(ids) < 4:
        return []

    signs = member_signs_ic(RUN_ID, ids)
    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    if R.empty or R.shape[1] < 4:
        return []

    # 1) Per-year Sharpe stability (regime-aware robustness)
    stable = _year_stable(R)
    if len(stable) >= 4:
        R = R[stable]

    # 2) Drawdown discipline at 20%, relax to 35% if too aggressive
    dd_ok = _dd_filter(R, DD_LIMIT)
    if len(dd_ok) < 4:
        dd_ok = _dd_filter(R, 0.35)
    if len(dd_ok) >= 4:
        R = R[dd_ok]

    # 3) IS Sharpe ranking metric
    sharpe = _is_sharpe_dict(R)
    if len(sharpe) < 4:
        return list(R.columns)[: max(4, N_CLUSTERS)]
    R = R[list(sharpe.keys())]

    # 4) Correlation dedup at rho=0.85, ranked by IS Sharpe
    try:
        deduped = correlation_dedup(R, threshold=RHO_DEDUP, keep_metric=sharpe)
    except Exception:
        deduped = list(sharpe.keys())
    if len(deduped) < 4:
        deduped = list(sharpe.keys())
    R = R[deduped]

    if R.shape[1] <= N_CLUSTERS:
        return list(R.columns)

    # 5) Ward agglomerative clustering on correlation-distance
    corr = R.corr().fillna(0.0).values
    corr = np.clip(corr, -1.0, 1.0)
    dist_sq = np.clip(0.5 * (1.0 - corr), 0.0, 1.0)
    dist = np.sqrt(dist_sq)
    np.fill_diagonal(dist, 0.0)
    dist = 0.5 * (dist + dist.T)

    try:
        cond = ssd.squareform(dist, checks=False)
        Z = sch.linkage(cond, method="ward")
        labels = sch.fcluster(Z, t=N_CLUSTERS, criterion="maxclust")
    except Exception:
        return sorted(sharpe.keys(), key=lambda a: -sharpe.get(a, -np.inf))[:N_CLUSTERS]

    cols = list(R.columns)
    by_cluster: dict[int, list[str]] = {}
    for col, lab in zip(cols, labels):
        by_cluster.setdefault(int(lab), []).append(col)

    # Highest-IS-Sharpe representative per cluster
    chosen: list[str] = []
    for _, members in by_cluster.items():
        best = max(members, key=lambda a: sharpe.get(a, -np.inf))
        chosen.append(best)

    if len(chosen) < 4:
        chosen = sorted(sharpe.keys(), key=lambda a: -sharpe.get(a, -np.inf))[: max(4, N_CLUSTERS)]

    return chosen


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    if not member_ids:
        return {}

    raw_signs = member_signs_ic(RUN_ID, member_ids)
    signs: dict[str, int] = {a: int(raw_signs.get(a, 1)) for a in member_ids}

    R = load_member_is_returns(RUN_ID, member_ids, signs=signs)
    sharpe = _is_sharpe_dict(R) if not R.empty else {}

    # Sharpe-tilt: positive, floored — no member fully zeroed
    coef: dict[str, float] = {a: max(float(sharpe.get(a, 0.1)), 0.1) for a in member_ids}

    # Deployable sign orientation via IC
    coef = apply_signs(coef, signs)

    # L1-normalize, then boost to push composite gross into [0.3, 0.9] band
    coef = normalize_coefficients(coef, "l1")
    coef = {k: float(v) * GROSS_BOOST for k, v in coef.items()}

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
```
