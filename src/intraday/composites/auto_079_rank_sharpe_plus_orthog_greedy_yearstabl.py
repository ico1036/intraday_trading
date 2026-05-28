"""Correlation-rank + Sharpe-rank greedy composite — cov-free hybrid scoring (mRMR-style, Peng-Long-Ding 2005 adapted) with per-year IS stability and 20% drawdown discipline."""
from __future__ import annotations
import argparse
import numpy as np
import pandas as pd

from intraday.composites._runner import build_and_backtest
from intraday.composites._optim_helpers import (
    member_signs_ic,
    apply_signs,
    select_is_submittable,
    select_all_alphas,
    member_is_sharpe,
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_079_rank_sharpe_plus_orthog_greedy_yearstabl"
COMPOSITION_NOTE = "rank_sharpe_plus_orthog_greedy_yearstable_dd20_n8_gross_x6"

RUN_ID = "run_2026_05_c"
N_MEMBERS = 8
DD_LIMIT_TIGHT = 0.20
DD_LIMIT_LOOSE = 0.30
GROSS_SCALE = 6.0
RANK_SHARPE_WEIGHT = 0.5


def _max_drawdown(returns: pd.Series) -> float:
    r = returns.dropna()
    if r.empty:
        return float("inf")
    eq = (1.0 + r).cumprod()
    peak = eq.cummax()
    dd = (eq / peak - 1.0).min()
    if not np.isfinite(dd):
        return float("inf")
    return float(abs(dd))


def _per_year_positive_sharpe(returns: pd.Series, min_days: int = 30) -> bool:
    r = returns.dropna()
    if r.empty:
        return False
    try:
        idx = pd.to_datetime(r.index)
    except Exception:
        return False
    s = r.copy()
    s.index = idx
    years_seen = 0
    for _, sub in s.groupby(idx.year):
        sub_clean = sub.dropna()
        if sub_clean.shape[0] < min_days:
            continue
        years_seen += 1
        std = sub_clean.std()
        if not np.isfinite(std) or std <= 0:
            return False
        if (sub_clean.mean() / std) <= 0:
            return False
    return years_seen >= 2


def _candidate_pool() -> list[str]:
    ids = select_is_submittable(RUN_ID)
    if len(ids) < N_MEMBERS * 2:
        ids = select_all_alphas(RUN_ID)
    return ids


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    ids = _candidate_pool()
    if not ids:
        return []
    signs = member_signs_ic(RUN_ID, ids)
    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    if R.empty or R.shape[1] < 2:
        sh = member_is_sharpe(RUN_ID, ids)
        return sorted(sh.keys(), key=lambda k: sh.get(k, -np.inf), reverse=True)[:N_MEMBERS]

    sh_all = member_is_sharpe(RUN_ID, list(R.columns))

    kept = [c for c in R.columns
            if _max_drawdown(R[c]) <= DD_LIMIT_TIGHT and _per_year_positive_sharpe(R[c])]
    if len(kept) < N_MEMBERS:
        kept = [c for c in R.columns
                if _max_drawdown(R[c]) <= DD_LIMIT_LOOSE and _per_year_positive_sharpe(R[c])]
    if len(kept) < N_MEMBERS:
        kept = sorted(R.columns, key=lambda k: sh_all.get(k, -np.inf), reverse=True)[:max(N_MEMBERS * 3, 24)]
    R = R[kept]

    if R.shape[1] <= N_MEMBERS:
        return list(R.columns)

    corr_abs = R.corr().fillna(0.0).clip(-1.0, 1.0).abs()
    candidates = list(R.columns)
    sharpe_sorted = sorted(candidates, key=lambda a: sh_all.get(a, -np.inf), reverse=True)
    sharpe_rank = {a: i + 1 for i, a in enumerate(sharpe_sorted)}

    chosen: list[str] = [sharpe_sorted[0]]
    remaining = [a for a in sharpe_sorted if a != chosen[0]]

    while len(chosen) < N_MEMBERS and remaining:
        mean_abs_corr = {a: float(corr_abs.loc[a, chosen].mean()) for a in remaining}
        orth_sorted = sorted(remaining, key=lambda a: mean_abs_corr[a])
        orth_rank = {a: i + 1 for i, a in enumerate(orth_sorted)}
        scored = sorted(
            remaining,
            key=lambda a: RANK_SHARPE_WEIGHT * sharpe_rank[a]
                          + (1.0 - RANK_SHARPE_WEIGHT) * orth_rank[a],
        )
        pick = scored[0]
        chosen.append(pick)
        remaining.remove(pick)

    return chosen


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    if not member_ids:
        return {}
    signs = member_signs_ic(RUN_ID, member_ids)
    base = {a: 1.0 for a in member_ids}
    signed = apply_signs(base, signs)
    coef = normalize_coefficients(signed, "l1")
    return {a: float(v * GROSS_SCALE) for a, v in coef.items()}


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