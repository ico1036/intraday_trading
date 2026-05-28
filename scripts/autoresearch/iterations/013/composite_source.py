"""Stability-IR selection with cluster-median representatives, an anti-selection-bias composite.

Cites Bailey, Borwein, Lopez de Prado, Zhu (2017) 'The Probability of Backtest Overfitting'
and Lopez de Prado (2016) HRP quasi-diagonalization. Per-alpha rolling-Sharpe IR
(mean/std of 60d rolling Sharpe across IS) replaces peak IS Sharpe as the ranking metric,
since IR-of-Sharpe rewards consistency rather than single-window luck. Within each
correlation-distance cluster we take the MEDIAN-IR alpha (not the best) to further blunt
selection bias. Equal-weight aggregation across cluster reps, scaled to a non-trivial
aggregate gross so the composite actually deploys.
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
    correlation_dedup,
    member_signs_ic,
    apply_signs,
    select_is_submittable,
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_013_stability_ir_cluster_median_repr_eqweigh"
COMPOSITION_NOTE = "stability_ir_cluster_median_repr_eqweight_gross085"

RUN_ID = "run_2026_05_c"
ROLL_WIN = 60
DEDUP_RHO = 0.85
N_CLUSTERS = 20
TARGET_GROSS = 0.85
IR_KEEP_FRAC = 0.55


def _stability_ir(R: pd.DataFrame, window: int = ROLL_WIN) -> pd.Series:
    """Per-alpha IR-of-rolling-Sharpe: high value = consistently positive risk-adjusted return."""
    mean_roll = R.rolling(window).mean()
    std_roll = R.rolling(window).std().replace(0.0, np.nan)
    sharpe_roll = (mean_roll / std_roll) * math.sqrt(252.0)
    mu = sharpe_roll.mean(axis=0)
    sd = sharpe_roll.std(axis=0).replace(0.0, np.nan)
    ir = (mu / sd).replace([np.inf, -np.inf], np.nan).fillna(-1e9)
    return ir


def _build_pool() -> tuple[pd.DataFrame, pd.Series, dict[str, int]]:
    ids = select_is_submittable(RUN_ID)
    if len(ids) < 4:
        return pd.DataFrame(), pd.Series(dtype=float), {}
    signs = member_signs_ic(RUN_ID, ids)
    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    if R is None or R.shape[1] < 2:
        return pd.DataFrame(), pd.Series(dtype=float), signs
    R = R.loc[:, R.std(axis=0) > 0.0].dropna(axis=1, how="all").fillna(0.0)
    if R.shape[1] < 2:
        return pd.DataFrame(), pd.Series(dtype=float), signs
    ir = _stability_ir(R)
    ir = ir.reindex(R.columns).fillna(-1e9)
    return R, ir, signs


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    R, ir, _signs = _build_pool()
    if R.empty or R.shape[1] < 2:
        return []

    # Stage 1: keep top fraction by stability-IR (consistency, not peak Sharpe)
    n_keep = max(N_CLUSTERS * 3, int(R.shape[1] * IR_KEEP_FRAC))
    n_keep = min(n_keep, R.shape[1])
    candidates = ir.sort_values(ascending=False).head(n_keep).index.tolist()
    R_c = R[candidates]

    # Stage 2: correlation dedup keyed by IR (so each near-clone group keeps the most stable one)
    keep_metric = {a: float(ir[a]) for a in candidates}
    try:
        deduped = correlation_dedup(R_c, threshold=DEDUP_RHO, keep_metric=keep_metric)
    except Exception:
        deduped = candidates
    if not deduped or len(deduped) < 2:
        deduped = candidates
    R_d = R[deduped]

    # If too few to cluster meaningfully, just return them
    if len(deduped) <= N_CLUSTERS:
        return list(deduped)

    # Stage 3: hierarchical clustering on correlation distance
    corr = R_d.corr().fillna(0.0).values
    np.fill_diagonal(corr, 1.0)
    dist = np.sqrt(np.clip(0.5 * (1.0 - corr), 0.0, 1.0))
    # Symmetrize numerically and zero the diagonal for squareform
    dist = 0.5 * (dist + dist.T)
    np.fill_diagonal(dist, 0.0)
    try:
        condensed = ssd.squareform(dist, checks=False)
        Z = sch.linkage(condensed, method="average")
        labels = sch.fcluster(Z, t=N_CLUSTERS, criterion="maxclust")
    except Exception:
        return list(deduped[:N_CLUSTERS])

    # Stage 4: pick MEDIAN-IR member within each cluster (anti-selection-bias)
    cols = list(R_d.columns)
    chosen: list[str] = []
    for k in sorted(set(labels)):
        members = [cols[i] for i in range(len(cols)) if labels[i] == k]
        if not members:
            continue
        members.sort(key=lambda a: float(ir[a]))
        mid = members[len(members) // 2]
        chosen.append(mid)

    if len(chosen) < 2:
        return list(deduped[:N_CLUSTERS])
    # De-dup any accidental repeats while preserving order
    seen = set()
    out: list[str] = []
    for a in chosen:
        if a not in seen:
            seen.add(a)
            out.append(a)
    return out


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    if not member_ids:
        return {}
    signs = member_signs_ic(RUN_ID, member_ids)
    # Equal weight on signed (deployable-direction) space, then back to raw via apply_signs.
    n = float(len(member_ids))
    eq = {a: 1.0 / n for a in member_ids}
    c = normalize_coefficients(eq, "l1")          # Σ|c| = 1
    c = {a: float(v) * TARGET_GROSS for a, v in c.items()}  # scale aggregate gross
    return apply_signs(c, signs)


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