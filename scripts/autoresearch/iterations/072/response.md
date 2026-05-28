Picking a cov-FREE method (per user's URGENT note) and avoiding Gram-Schmidt (failed 9/9). Going with **Ward hierarchical clustering on correlation-distance + per-cluster top-IS-Sharpe centroid + equal-weight** — this is Lopez de Prado's clustering primitive minus the bisection-bottom-up risk allocation, deliberately keeping the combination *cov-free* so we don't trigger the 1/σ underweighting trap. Layered with the empirically-winning filters: per-year IS Sharpe stability (positive in every IS year) and IS max-drawdown < 22%. Final coefficients normalized then scaled to target mean row-L1 ≈ 0.7 via the sigma-of-returns proxy with a sanity-bounded multiplier.

```python COMPOSITE_FILE
"""Ward HC cluster-centroid composite (cov-free): per-cluster top-IS-Sharpe, equal-weight, gross-scaled.

Method: Ward hierarchical clustering (Ward 1963) on correlation-distance
d = sqrt(0.5 * (1 - corr)) of sign-aligned IS returns. Cut tree at K=6
clusters; within each cluster pick the centroid as the highest IS-Sharpe
alpha (cluster representative). Equal-weight the K centroids, then rescale
to a target gross-exposure (mean row-L1 ≈ 0.7) via per-member return-std
proxy with a bounded multiplier.

References:
- Ward 1963, "Hierarchical Grouping to Optimize an Objective Function" (JASA)
- Lopez de Prado 2016, HRP (correlation-distance metric)
- Raffinot 2018, HERC (cluster-then-aggregate primitive)

This is deliberately cov-FREE — no Σ inversion, no tangency, no min-var —
to avoid the 1/σ underweighting trap that has held composite gross
exposure at ~5% in prior cov-based attempts.
"""
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
    member_signs_ic,
    apply_signs,
    load_member_is_returns,
    normalize_coefficients,
    member_is_sharpe,
)

COMPOSITE_ID = "auto_072"
COMPOSITION_NOTE = "ward_hc_centroid_K6_yearstable_dd22_eqweight_gross070"

RUN_ID = "run_2026_05_c"
K_CLUSTERS = 6
DD_MAX = 0.22
TARGET_GROSS = 0.70
SCALE_CAP = 12.0
SCALE_FLOOR = 3.0


def _max_drawdown(s: pd.Series) -> float:
    s = s.dropna()
    if len(s) == 0:
        return 1.0
    eq = (1.0 + s).cumprod()
    peak = eq.cummax()
    dd = (eq / peak) - 1.0
    return float(-dd.min())


def _year_stable_cols(R: pd.DataFrame) -> list[str]:
    if R.empty or not isinstance(R.index, pd.DatetimeIndex):
        return list(R.columns)
    years = sorted(set(R.index.year.tolist()))
    keep: list[str] = []
    for col in R.columns:
        s = R[col].dropna()
        if len(s) < 30:
            continue
        ok = True
        seen_years = 0
        for y in years:
            sub = s[s.index.year == y]
            if len(sub) < 10:
                continue
            seen_years += 1
            std = float(sub.std())
            if not np.isfinite(std) or std <= 0.0:
                ok = False
                break
            sh = float(sub.mean()) / std * math.sqrt(252.0)
            if sh <= 0.0:
                ok = False
                break
        if ok and seen_years >= 2:
            keep.append(col)
    return keep


def _dd_filter_cols(R: pd.DataFrame, dd_max: float) -> list[str]:
    keep: list[str] = []
    for col in R.columns:
        s = R[col]
        if len(s.dropna()) < 30:
            continue
        if _max_drawdown(s) <= dd_max:
            keep.append(col)
    return keep


def _ward_clusters(R: pd.DataFrame, k: int) -> dict[int, list[str]]:
    corr = R.corr().fillna(0.0).clip(-1.0, 1.0).to_numpy()
    np.fill_diagonal(corr, 1.0)
    d = np.sqrt(np.clip(0.5 * (1.0 - corr), 0.0, 1.0))
    d = 0.5 * (d + d.T)
    np.fill_diagonal(d, 0.0)
    cond = ssd.squareform(d, checks=False)
    Z = sch.linkage(cond, method="ward")
    labels = sch.fcluster(Z, t=k, criterion="maxclust")
    out: dict[int, list[str]] = {}
    for col, lab in zip(R.columns, labels):
        out.setdefault(int(lab), []).append(col)
    return out


def _build_pool() -> tuple[pd.DataFrame, dict[str, float]]:
    ids = select_is_submittable(RUN_ID)
    if not ids:
        return pd.DataFrame(), {}
    signs = member_signs_ic(RUN_ID, ids)
    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    if R is None or R.empty or R.shape[1] < 2:
        return pd.DataFrame() if R is None else R, {}

    R = R.loc[:, R.std() > 0]

    ys = _year_stable_cols(R)
    if len(ys) >= max(K_CLUSTERS, 4):
        R = R[ys]

    dd = _dd_filter_cols(R, DD_MAX)
    if len(dd) >= max(K_CLUSTERS, 4):
        R = R[dd]

    is_sh = member_is_sharpe(RUN_ID, list(R.columns))
    return R, is_sh


def _fallback_topk(k: int) -> list[str]:
    all_ids = select_is_submittable(RUN_ID)
    sh = member_is_sharpe(RUN_ID, all_ids)
    ranked = sorted(sh.items(), key=lambda kv: kv[1], reverse=True)
    return [a for a, _ in ranked[:k]]


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    try:
        R, is_sh = _build_pool()
        if R.empty or R.shape[1] < 2:
            return _fallback_topk(K_CLUSTERS)
        if R.shape[1] <= K_CLUSTERS:
            return list(R.columns)
        clusters = _ward_clusters(R, K_CLUSTERS)
        picks: list[str] = []
        for _lab, members in clusters.items():
            if not members:
                continue
            best = max(members, key=lambda m: is_sh.get(m, -1e9))
            picks.append(best)
        if len(picks) < 2:
            return _fallback_topk(K_CLUSTERS)
        return picks
    except Exception:
        return _fallback_topk(K_CLUSTERS)


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    if not member_ids:
        return {}
    signs = member_signs_ic(RUN_ID, member_ids)
    R = load_member_is_returns(RUN_ID, member_ids, signs=signs)
    if R is None or R.empty:
        available = list(member_ids)
    else:
        available = [a for a in member_ids if a in R.columns]
        if not available:
            available = list(R.columns)
    if not available:
        return {}

    coef = {a: 1.0 for a in available}
    coef = normalize_coefficients(coef, "l1")
    coef = apply_signs(coef, signs)

    # Heuristic gross-scaling: use member return-std as a proxy for activity.
    scale = SCALE_FLOOR
    if R is not None and not R.empty:
        try:
            sigma = R[available].std().fillna(0.0).to_dict()
            est = float(sum(abs(coef.get(a, 0.0)) * float(sigma.get(a, 0.0))
                            for a in available))
            if est > 1e-8:
                proposed = TARGET_GROSS / est * 0.05  # damp; sigma ≈ daily-ret scale
                scale = float(np.clip(proposed, SCALE_FLOOR, SCALE_CAP))
        except Exception:
            scale = SCALE_FLOOR

    coef = {a: float(v) * scale for a, v in coef.items()}
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
