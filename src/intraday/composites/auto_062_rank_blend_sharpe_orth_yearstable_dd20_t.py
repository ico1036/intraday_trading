"""Cov-free composite via Sharpe-rank x Orthogonality-rank greedy blend.

Method: Quasi-orthogonal greedy selection (Choueifaty 2008 max-diversification
spirit, without Sigma inversion) on a pool pre-filtered by per-year IS-Sharpe
stability (Lopez de Prado 2018, ch.7 regime conditioning) and max-drawdown
discipline (< 20%). Correlation dedup at rho=0.85 follows HRP distance
(Lopez de Prado 2016). Signs aligned via IC orientation (Grinold-Kahn 1995).
Equal-weight 1/k on the kept set, vol-aware post-scale to target mean row L1.
"""
from __future__ import annotations

import argparse
import numpy as np
import pandas as pd

from intraday.composites._runner import build_and_backtest
from intraday.composites._optim_helpers import (
    correlation_dedup,
    member_signs_ic,
    apply_signs,
    select_is_submittable,
    select_all_alphas,
    load_member_is_returns,
)

COMPOSITE_ID = "auto_062_rank_blend_sharpe_orth_yearstable_dd20_t"
COMPOSITION_NOTE = "rank_blend_sharpe_orth_yearstable_dd20_top6_eqw_volscaled"

RUN_ID = "run_2026_05_c"
N_TARGET = 6
DD_MAX = 0.20
RHO_DEDUP = 0.85
TARGET_GROSS = 0.65
MIN_YEAR_DAYS = 30


def _ann_sharpe(r: pd.Series) -> float:
    r = r.dropna()
    if len(r) < 10:
        return 0.0
    s = r.std()
    if not np.isfinite(s) or s <= 1e-12:
        return 0.0
    return float(r.mean() / s * np.sqrt(252.0))


def _max_dd(r: pd.Series) -> float:
    r = r.fillna(0.0)
    eq = (1.0 + r).cumprod()
    peak = eq.cummax()
    dd = eq / peak - 1.0
    return float(-dd.min()) if len(dd) else 0.0


def _year_stable(r: pd.Series) -> bool:
    r = r.dropna()
    if not isinstance(r.index, pd.DatetimeIndex):
        try:
            r.index = pd.to_datetime(r.index)
        except Exception:
            return True
    years_seen = 0
    for _, grp in r.groupby(r.index.year):
        if len(grp) < MIN_YEAR_DAYS:
            continue
        years_seen += 1
        if _ann_sharpe(grp) <= 0.0:
            return False
    return years_seen >= 2


def _candidate_pool() -> list[str]:
    try:
        ids = select_is_submittable(RUN_ID)
    except Exception:
        ids = []
    if not ids:
        try:
            ids = select_all_alphas(RUN_ID)
        except Exception:
            ids = []
    return list(ids)


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    ids = _candidate_pool()
    if len(ids) < 2:
        return ids[:2]

    signs = member_signs_ic(RUN_ID, ids)
    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    if R is None or R.empty or R.shape[1] < 2:
        return list(R.columns)[:2] if R is not None else ids[:2]

    sharpe_by_id: dict[str, float] = {}
    survivors: list[str] = []
    for aid in R.columns:
        col = R[aid]
        if col.dropna().shape[0] < 60:
            continue
        sh = _ann_sharpe(col)
        if sh <= 0.0:
            continue
        if _max_dd(col) > DD_MAX:
            continue
        if not _year_stable(col):
            continue
        sharpe_by_id[aid] = sh
        survivors.append(aid)

    if len(survivors) < N_TARGET:
        for aid in R.columns:
            if aid in sharpe_by_id:
                continue
            col = R[aid]
            if col.dropna().shape[0] < 60:
                continue
            sh = _ann_sharpe(col)
            if sh <= 0.0:
                continue
            if _max_dd(col) > 0.30:
                continue
            sharpe_by_id[aid] = sh
            survivors.append(aid)

    if len(survivors) < 2:
        scored = [(a, _ann_sharpe(R[a])) for a in R.columns]
        scored.sort(key=lambda x: -x[1])
        survivors = [a for a, _ in scored[: max(2, N_TARGET)]]
        for a, sh in scored:
            sharpe_by_id.setdefault(a, sh)

    Rs = R[survivors]
    deduped = correlation_dedup(Rs, RHO_DEDUP, keep_metric=sharpe_by_id)
    if not deduped or len(deduped) < 2:
        deduped = sorted(survivors, key=lambda a: -sharpe_by_id.get(a, 0.0))
        deduped = deduped[: max(2, N_TARGET)]

    pool = sorted(deduped, key=lambda a: -sharpe_by_id.get(a, 0.0))
    if len(pool) <= N_TARGET:
        return pool

    sharpe_order = sorted(pool, key=lambda a: -sharpe_by_id.get(a, 0.0))
    sharpe_rank = {a: i for i, a in enumerate(sharpe_order)}

    Cabs = R[pool].corr().abs().fillna(1.0)

    selected = [sharpe_order[0]]
    remaining = [a for a in pool if a != selected[0]]

    while len(selected) < N_TARGET and remaining:
        mean_corr = {a: float(Cabs.loc[a, selected].mean()) for a in remaining}
        orth_order = sorted(remaining, key=lambda a: mean_corr[a])
        orth_rank = {a: i for i, a in enumerate(orth_order)}
        scored = sorted(
            remaining,
            key=lambda a: 0.5 * sharpe_rank[a] + 0.5 * orth_rank[a],
        )
        pick = scored[0]
        selected.append(pick)
        remaining.remove(pick)

    return selected


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    if not member_ids:
        return {}
    if len(member_ids) == 1:
        only = member_ids[0]
        return {only: float(np.clip(TARGET_GROSS, 0.1, 1.0))}

    n = len(member_ids)
    base = {a: 1.0 / n for a in member_ids}

    signs = member_signs_ic(RUN_ID, member_ids)
    base = apply_signs(base, signs)

    try:
        R = load_member_is_returns(RUN_ID, member_ids, signs=signs)
    except Exception:
        R = None

    scale = 8.0
    if R is not None and not R.empty:
        sigma = R.std()
        gross_est = 0.0
        for a in member_ids:
            s = float(sigma.get(a, 0.0)) if a in sigma.index else 0.0
            gross_est += abs(base.get(a, 0.0)) * s
        if gross_est > 1e-9:
            scale = TARGET_GROSS / gross_est

    scale = float(np.clip(scale, 1.0, 60.0))
    coef = {k: float(v * scale) for k, v in base.items()}
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