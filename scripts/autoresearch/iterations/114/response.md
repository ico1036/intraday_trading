Rationale: prior attempts on this run consistently produced mean row L1 around 0.05 — composite leaves 95% of its gross-exposure budget unused, which is the dominant cap on OS Sharpe per the harness notes. Cov-based optimizers (tangency, min-var, Neumann) inherently underweight here. The user explicitly recommends cov-free composition with native exposure preservation.

I'm picking **cluster-centroid + equal-weight** (cov-free, Mantegna 1999 correlation-distance + Ward; HRP-flavored single-representative-per-cluster, no cov inversion). Selection gates: max IS drawdown < 25% (Calmar-style discipline) + per-year IS Sharpe positivity (regime-conditional robustness — the harness flagged regime shift as the #1 OS failure mode). Correlation dedup at ρ=0.85 before clustering, then 6 Ward clusters, one IS-Sharpe-max centroid per cluster. Sign alignment via `member_signs_ic` so IC<0 members contribute their deployable polarity. Final step: explicit ×10 coefficient amplification so the runner's per-row L1 clamp actually engages → composite mean row L1 lifts from ≈0.05 → ≈0.5–0.8 region. Idea family is cov-free hierarchical clustering with stability gates — distinct from prior tried families (Neumann, NCO, BL, HERC, MaxDiv, CVaR, James-Stein, etc.).

```python COMPOSITE_FILE
"""Cluster-centroid equal-weight (cov-free) composite with per-year IS Sharpe
stability and max-drawdown discipline. Mantegna (1999) correlation-distance
hierarchical clustering + Ward linkage + 1-per-cluster IS-Sharpe centroid
selection; HRP-flavored (Lopez de Prado 2016) but sidesteps cov inversion to
preserve native gross exposure.
"""
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
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_114"
COMPOSITION_NOTE = "cluster_centroid_eqw_yearstab_dd25_k6_grossamp10"

RUN_ID = "run_2026_05_c"
N_CLUSTERS = 6
DD_MAX = 0.25
DEDUP_RHO = 0.85
GROSS_AMP = 10.0  # amplify equal-weight coefs so row-L1 clamp engages
ANN = 252.0


def _max_drawdown(returns: pd.Series) -> float:
    r = returns.fillna(0.0).to_numpy()
    if r.size == 0:
        return 0.0
    eq = np.cumprod(1.0 + r)
    peak = np.maximum.accumulate(eq)
    peak_safe = np.where(peak == 0, 1.0, peak)
    dd = (eq - peak) / peak_safe
    return float(-dd.min())


def _year_stable(r: pd.Series) -> bool:
    if r.empty:
        return False
    try:
        idx = pd.to_datetime(r.index)
    except Exception:
        return False
    years = idx.year
    df = pd.DataFrame({"r": r.to_numpy(), "y": years})
    grouped = df.groupby("y")["r"]
    if grouped.ngroups < 2:
        return True
    for _, g in grouped:
        if len(g) < 10:
            continue
        sd = g.std()
        if sd == 0 or not np.isfinite(sd):
            return False
        sh = g.mean() / sd * np.sqrt(ANN)
        if sh <= 0:
            return False
    return True


def _is_sharpe(s: pd.Series) -> float:
    sd = s.std()
    if sd == 0 or not np.isfinite(sd):
        return float("nan")
    return float(s.mean() / sd * np.sqrt(ANN))


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    ids_all = select_is_submittable(RUN_ID)
    if not ids_all:
        return []
    signs = member_signs_ic(RUN_ID, ids_all)
    R = load_member_is_returns(RUN_ID, ids_all, signs=signs)
    R = R.dropna(how="all", axis=1)
    if R.shape[1] < 2:
        return list(R.columns)

    # Pass 1: strict — DD < 25%, per-year IS Sharpe > 0
    strict: list[str] = []
    strict_sh: dict[str, float] = {}
    for col in R.columns:
        s = R[col].dropna()
        if len(s) < 30:
            continue
        sh = _is_sharpe(s)
        if not np.isfinite(sh):
            continue
        if _max_drawdown(s) > DD_MAX:
            continue
        if not _year_stable(s):
            continue
        strict.append(col)
        strict_sh[col] = sh

    # Pass 2: relax year-stability if pool too narrow
    if len(strict) < N_CLUSTERS + 2:
        strict, strict_sh = [], {}
        for col in R.columns:
            s = R[col].dropna()
            if len(s) < 30:
                continue
            sh = _is_sharpe(s)
            if not np.isfinite(sh):
                continue
            if _max_drawdown(s) > DD_MAX:
                continue
            strict.append(col)
            strict_sh[col] = sh

    # Pass 3: final fallback — top-K by IS Sharpe ignoring filters
    if len(strict) < 2:
        cands: list[tuple[str, float]] = []
        for col in R.columns:
            s = R[col].dropna()
            if len(s) < 30:
                continue
            sh = _is_sharpe(s)
            if np.isfinite(sh):
                cands.append((col, sh))
        cands.sort(key=lambda x: -x[1])
        chosen = [c for c, _ in cands[:N_CLUSTERS]]
        if len(chosen) >= 2:
            return chosen
        return list(R.columns)[: max(2, min(N_CLUSTERS, R.shape[1]))]

    # Correlation dedup at 0.85 keeping by IS Sharpe
    try:
        kept = correlation_dedup(R[strict].fillna(0.0),
                                 threshold=DEDUP_RHO,
                                 keep_metric=strict_sh)
    except Exception:
        kept = sorted(strict, key=lambda c: -strict_sh.get(c, -1e9))

    if not kept or len(kept) < 2:
        kept = sorted(strict, key=lambda c: -strict_sh.get(c, -1e9))[:max(2, N_CLUSTERS)]

    if len(kept) <= N_CLUSTERS:
        return list(kept)

    # Ward clustering on Mantegna correlation distance
    Rk = R[kept].fillna(0.0)
    corr = Rk.corr().to_numpy()
    corr = np.clip(corr, -1.0, 1.0)
    dist = np.sqrt(np.maximum(0.5 * (1.0 - corr), 0.0))
    np.fill_diagonal(dist, 0.0)
    cond = ssd.squareform(dist, checks=False)
    link = sch.linkage(cond, method="ward")
    K = int(min(N_CLUSTERS, len(kept)))
    labels = sch.fcluster(link, t=K, criterion="maxclust")

    centroids: list[str] = []
    for cl in np.unique(labels):
        members = [kept[i] for i in range(len(kept)) if labels[i] == cl]
        if not members:
            continue
        best = max(members, key=lambda m: strict_sh.get(m, -1e9))
        centroids.append(best)

    if len(centroids) < 2:
        centroids = sorted(kept, key=lambda c: -strict_sh.get(c, -1e9))[:max(2, K)]
    return centroids


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    if not member_ids:
        return {}
    signs = member_signs_ic(RUN_ID, member_ids)
    base = {m: 1.0 for m in member_ids}
    coef = normalize_coefficients(base, scheme="l1")  # 1/K each
    coef = apply_signs(coef, signs)
    coef = {m: float(v * GROSS_AMP) for m, v in coef.items()}
    for m in member_ids:
        coef.setdefault(m, 0.0)
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
