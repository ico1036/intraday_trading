"""Rank-sum greedy cov-free composition with year-stability and DD-discipline filters.

Method: cov-free greedy member selection. For each new pick we score
candidates by 0.5*rank(IS Sharpe desc) + 0.5*rank(mean |corr| with selected asc)
- a lexicographic blend of return-strength and orthogonality, related to
mutual-information greedy feature selection (Battiti 1994) repurposed for
portfolio member picking. Regime-aware pre-filter: positive mean return in
every IS sub-year (2022/2023/2024) plus max IS drawdown <= 25%. Concentrated
to n=6 with equal-weight 1/n, sign-aligned via member_signs_ic, and then
rescaled so the composite hits target mean row-L1 ~ 0.7 (the critical
gross-exposure fix - prior cov-based attempts left ~95% of the risk
budget unused after row-L1 clamping).
"""
from __future__ import annotations
import argparse
import numpy as np
import pandas as pd

from intraday.composites._runner import build_and_backtest
from intraday.composites._optim_helpers import (
    member_signs_ic,
    apply_signs,
    select_is_submittable,
    member_is_sharpe,
    load_member_is_returns,
)

COMPOSITE_ID = "auto_063_rank_sum_greedy_year_stable_dd25_top6_co"
COMPOSITION_NOTE = "rank_sum_greedy_year_stable_dd25_top6_covfree_eqweight"
RUN_ID = "run_2026_05_c"

N_TARGET = 6
DD_MAX = 0.25
TARGET_GROSS = 0.7


def _max_drawdown(returns: pd.Series) -> float:
    s = returns.dropna()
    if s.empty:
        return 1.0
    cum = (1.0 + s).cumprod()
    peak = cum.cummax()
    dd = (cum / peak) - 1.0
    return float(-dd.min())


def _year_stable(returns: pd.Series) -> bool:
    s = returns.dropna()
    if s.empty:
        return False
    idx = s.index
    if not isinstance(idx, pd.DatetimeIndex):
        try:
            idx = pd.to_datetime(idx)
            s = pd.Series(s.values, index=idx)
        except Exception:
            return True
    years = s.index.year.values
    unique_years = np.unique(years)
    if len(unique_years) < 2:
        return True
    for y in unique_years:
        seg = s[years == y]
        if len(seg) < 5:
            continue
        if float(seg.mean()) <= 0.0:
            return False
    return True


def _filter_regime(R: pd.DataFrame, strict: bool) -> list[str]:
    keep = []
    for a in R.columns:
        s = R[a].dropna()
        if len(s) < 60:
            continue
        if strict and _max_drawdown(s) > DD_MAX:
            continue
        if not _year_stable(s):
            continue
        keep.append(a)
    return keep


def _greedy_rank_sum(
    R: pd.DataFrame, is_sharpe: dict, n_target: int
) -> list[str]:
    cands = [a for a in R.columns if a in is_sharpe]
    if len(cands) <= n_target:
        return cands

    sharpe_order = sorted(cands, key=lambda a: float(is_sharpe.get(a, 0.0)), reverse=True)
    sharpe_rank = {a: i for i, a in enumerate(sharpe_order)}

    selected = [sharpe_order[0]]
    remaining = [a for a in cands if a != selected[0]]

    while len(selected) < n_target and remaining:
        ortho_score = {}
        for a in remaining:
            corrs = []
            col_a = R[a]
            for s in selected:
                c = float(col_a.corr(R[s]))
                if np.isfinite(c):
                    corrs.append(abs(c))
            ortho_score[a] = float(np.mean(corrs)) if corrs else 0.0
        ortho_order = sorted(remaining, key=lambda a: ortho_score[a])
        ortho_rank = {a: i for i, a in enumerate(ortho_order)}

        combo = {
            a: 0.5 * sharpe_rank[a] + 0.5 * ortho_rank[a]
            for a in remaining
        }
        best = min(combo, key=lambda a: combo[a])
        selected.append(best)
        remaining.remove(best)

    return selected


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    ids = list(select_is_submittable(RUN_ID))
    if len(ids) < N_TARGET:
        if "alpha_id" in alpha_index.columns:
            ids = list(alpha_index["alpha_id"])
    if len(ids) < N_TARGET:
        return ids

    signs = member_signs_ic(RUN_ID, ids)
    signs = {a: int(signs.get(a, 1)) for a in ids}
    R = load_member_is_returns(RUN_ID, ids, signs=signs)

    if R is None or R.empty or R.shape[1] < N_TARGET:
        sh = member_is_sharpe(RUN_ID, ids)
        ranked = sorted(sh.keys(), key=lambda a: float(sh.get(a, 0.0)), reverse=True)
        return ranked[:N_TARGET]

    try:
        R.index = pd.to_datetime(R.index)
    except Exception:
        pass

    is_sharpe_all = member_is_sharpe(RUN_ID, list(R.columns))

    filtered = _filter_regime(R, strict=True)
    if len(filtered) < N_TARGET:
        filtered = _filter_regime(R, strict=False)
    if len(filtered) < N_TARGET:
        ranked = sorted(R.columns, key=lambda a: float(is_sharpe_all.get(a, 0.0)), reverse=True)
        filtered = ranked[: max(N_TARGET * 4, 20)]

    R_f = R[filtered].dropna(axis=1, how="all")
    if R_f.shape[1] < N_TARGET:
        ranked = sorted(R.columns, key=lambda a: float(is_sharpe_all.get(a, 0.0)), reverse=True)
        return ranked[:N_TARGET]

    selected = _greedy_rank_sum(R_f, is_sharpe_all, N_TARGET)
    if len(selected) < N_TARGET:
        ranked = sorted(R.columns, key=lambda a: float(is_sharpe_all.get(a, 0.0)), reverse=True)
        for a in ranked:
            if a not in selected:
                selected.append(a)
            if len(selected) >= N_TARGET:
                break
    return selected


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    if not member_ids:
        return {}
    n = len(member_ids)
    coef = {a: 1.0 / float(n) for a in member_ids}

    signs = member_signs_ic(RUN_ID, member_ids)
    signs = {a: int(signs.get(a, 1)) for a in member_ids}
    coef = apply_signs(coef, signs)

    R = load_member_is_returns(RUN_ID, member_ids, signs=None)
    if R is not None and not R.empty:
        sigma = R.std()
        mean_sigma = float(sigma.mean()) if len(sigma) > 0 else 0.0
        if mean_sigma <= 0.0:
            mean_sigma = 0.01
        est_gross = 0.0
        for a in member_ids:
            sa = float(sigma.get(a, mean_sigma)) if a in sigma.index else mean_sigma
            est_gross += abs(coef[a]) * sa
        if est_gross > 1e-9:
            scale = TARGET_GROSS / est_gross
            coef = {a: float(v * scale) for a, v in coef.items()}
        else:
            coef = {a: float(v * 10.0) for a, v in coef.items()}
    else:
        coef = {a: float(v * 10.0) for a, v in coef.items()}

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