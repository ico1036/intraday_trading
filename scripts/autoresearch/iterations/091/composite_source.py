"""Cov-free rank-aggregation composite: blend IS-Sharpe rank with
orthogonality rank (mean |corr| against prior picks). Year-stability
across IS sub-years + DD<25% gating + correlation dedup rho=0.85.
Equal-weight (n=6), IC sign-aligned, gross-scaled to target row-L1.
Cites: greedy rank-aggregation diversification in the spirit of
Choueifaty-Coignard Maximum Diversification (2008), but cov-free and
rank-based to bypass the 1/sigma-weighting trap of inverse-cov methods.
Regime/DD gates per Lopez de Prado backtest-robustness heuristics."""

from __future__ import annotations
import argparse
import math
import numpy as np
import pandas as pd

from intraday.composites._runner import build_and_backtest
from intraday.composites._optim_helpers import (
    correlation_dedup,
    member_signs_ic,
    apply_signs,
    select_is_submittable,
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_091_rank_agg_sharpe_orth_yearstable_dd25_top"
COMPOSITION_NOTE = "rank_agg_sharpe_orth_yearstable_dd25_top6_eqw_grossx4"

RUN_ID = "run_2026_05_c"
N_MEMBERS = 6
DEDUP_RHO = 0.85
DD_THRESHOLD = 0.25
GROSS_SCALE = 4.0


def _years_index(r: pd.Series) -> pd.Series:
    try:
        idx = pd.to_datetime(r.index)
        return pd.Series(idx.year, index=r.index)
    except Exception:
        return pd.Series([0] * len(r), index=r.index)


def _per_year_sharpe_ok(r: pd.Series, min_years: int = 2) -> bool:
    r = r.dropna()
    if len(r) < 60:
        return False
    yr = _years_index(r)
    cnt_total = 0
    for _, g in r.groupby(yr):
        if len(g) < 20:
            continue
        cnt_total += 1
        std = g.std()
        if std == 0 or pd.isna(std):
            return False
        s = float(g.mean()) / float(std) * math.sqrt(252.0)
        if s <= 0:
            return False
    return cnt_total >= min_years


def _max_drawdown(r: pd.Series) -> float:
    r = r.dropna()
    if len(r) == 0:
        return 1.0
    eq = (1.0 + r.clip(lower=-0.99)).cumprod()
    peak = eq.cummax()
    dd = (eq - peak) / peak
    mn = dd.min()
    if pd.isna(mn):
        return 1.0
    return float(-mn)


def _annual_sharpe(r: pd.Series) -> float:
    r = r.dropna()
    if len(r) < 20:
        return 0.0
    s = r.std()
    if s == 0 or pd.isna(s):
        return 0.0
    return float(r.mean() / s * math.sqrt(252.0))


def _greedy_rank_select(Rs: pd.DataFrame, sharpes: dict, n_target: int) -> list:
    kept = list(Rs.columns)
    if not kept:
        return []
    pool_sorted = sorted(kept, key=lambda a: -sharpes.get(a, 0.0))
    picks = [pool_sorted[0]]
    remaining = [a for a in pool_sorted if a != picks[0]]

    while len(picks) < n_target and remaining:
        rs_list = sorted(remaining, key=lambda a: -sharpes.get(a, 0.0))
        rank_sharpe = {a: i for i, a in enumerate(rs_list)}

        corr_avg = {}
        for a in remaining:
            cs = []
            for p in picks:
                try:
                    c = Rs[a].corr(Rs[p])
                except Exception:
                    c = float("nan")
                if pd.notna(c):
                    cs.append(abs(float(c)))
            corr_avg[a] = float(np.mean(cs)) if cs else 0.0

        ro_list = sorted(remaining, key=lambda a: corr_avg[a])
        rank_orth = {a: i for i, a in enumerate(ro_list)}

        score = {a: 0.5 * rank_sharpe[a] + 0.5 * rank_orth[a] for a in remaining}
        nxt = min(remaining, key=lambda a: score[a])
        picks.append(nxt)
        remaining = [a for a in remaining if a != nxt]

    return picks


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    ids = list(select_is_submittable(RUN_ID))
    if len(ids) < 4 and "alpha_id" in alpha_index.columns:
        ids = list(alpha_index["alpha_id"].dropna().astype(str).unique())
    if not ids:
        return []

    signs = member_signs_ic(RUN_ID, ids)
    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    keep_cols = [c for c in R.columns if R[c].notna().sum() >= 60]
    R = R.loc[:, keep_cols]
    if R.shape[1] < 2:
        return list(R.columns)

    # Pass 1: strict — year-stability + DD<25% + positive Sharpe
    survivors, sharpes = [], {}
    for a in R.columns:
        r = R[a]
        if not _per_year_sharpe_ok(r):
            continue
        if _max_drawdown(r) > DD_THRESHOLD:
            continue
        s = _annual_sharpe(r)
        if s > 0:
            survivors.append(a)
            sharpes[a] = s

    # Pass 2: relax DD to 35% but keep year-stability
    if len(survivors) < N_MEMBERS:
        survivors, sharpes = [], {}
        for a in R.columns:
            r = R[a]
            if not _per_year_sharpe_ok(r):
                continue
            if _max_drawdown(r) > 0.35:
                continue
            s = _annual_sharpe(r)
            if s > 0:
                survivors.append(a)
                sharpes[a] = s

    # Pass 3: positive Sharpe only
    if len(survivors) < N_MEMBERS:
        survivors, sharpes = [], {}
        for a in R.columns:
            s = _annual_sharpe(R[a])
            if s > 0:
                survivors.append(a)
                sharpes[a] = s

    if len(survivors) < 2:
        survivors = list(R.columns)
        sharpes = {a: _annual_sharpe(R[a]) for a in survivors}

    # Correlation dedup, ranked by IS Sharpe
    Rs = R[survivors]
    try:
        kept = correlation_dedup(Rs, threshold=DEDUP_RHO, keep_metric=sharpes)
        kept = [k for k in kept if k in survivors]
    except Exception:
        kept = survivors
    if len(kept) < 2:
        kept = survivors

    picks = _greedy_rank_select(R[kept], sharpes, N_MEMBERS)
    if len(picks) < 2:
        picks = sorted(kept, key=lambda a: -sharpes.get(a, 0.0))[:N_MEMBERS]
    return picks


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    if not member_ids:
        return {}
    signs = member_signs_ic(RUN_ID, member_ids)

    base = {a: 1.0 for a in member_ids}
    base = normalize_coefficients(base, "l1")  # 1/N each
    base = apply_signs(base, signs)

    out = {}
    for a in member_ids:
        v = float(base.get(a, 0.0)) * GROSS_SCALE
        out[a] = v
    return out


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