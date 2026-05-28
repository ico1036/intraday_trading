"""Cov-free rank-composite (Sharpe+orthogonality greedy) with per-year IS stability + DD discipline.

Inspired by Asness-Frazzini-Pedersen (2013) rank-IC composite scoring and Bayer & Stahl (2019)
correlation-distance portfolio construction. Bypasses the Sigma^-1 . mu gross-exposure trap of
tangency / min-variance optimizers by using equal sign-embedded magnitudes over a greedily
selected, ortho-diverse, regime-robust top-6 set.
"""
from __future__ import annotations
import argparse
import math
import numpy as np
import pandas as pd

from intraday.composites._runner import build_and_backtest
from intraday.composites._optim_helpers import (
    correlation_dedup,
    member_signs_ic,
    select_is_submittable,
    select_all_alphas,
    load_member_is_returns,
)

COMPOSITE_ID = "auto_087_rank_sharpe_corr_greedy_yearstable_dd25"
COMPOSITION_NOTE = "rank_sharpe_corr_greedy_yearstable_dd25_top6_eqwgt_signemb"

RUN_ID = "run_2026_05_c"
N_TARGET = 6
DD_MAX = 0.25
DEDUP_RHO = 0.85
PER_MEMBER_MAGNITUDE = 1.0


def _max_drawdown(returns: pd.Series) -> float:
    s = returns.fillna(0.0)
    if len(s) == 0:
        return 0.0
    eq = (1.0 + s).cumprod()
    peak = eq.cummax()
    dd = eq / peak - 1.0
    return float(-dd.min())


def _annualized_sharpe(returns: pd.Series) -> float:
    s = returns.dropna()
    if len(s) < 2:
        return 0.0
    std = float(s.std(ddof=0))
    if std == 0.0:
        return 0.0
    return float(s.mean() / std * math.sqrt(252))


def _year_stable(returns: pd.Series, min_years: int = 2) -> bool:
    s = returns.dropna()
    if not isinstance(s.index, pd.DatetimeIndex) or len(s) == 0:
        return True
    years = s.index.year
    uniq = sorted(set(years))
    if len(uniq) < min_years:
        return True
    for y in uniq:
        yr = s[years == y]
        if len(yr) < 2:
            continue
        std = float(yr.std(ddof=0))
        if std == 0.0:
            continue
        sh = float(yr.mean() / std)
        if sh <= 0.0:
            return False
    return True


def _safe_signs(ids: list[str]) -> dict[str, int]:
    try:
        s = member_signs_ic(RUN_ID, ids)
        return {a: int(s.get(a, 1)) if a in s else 1 for a in ids}
    except Exception:
        return {a: 1 for a in ids}


def _safe_pool(alpha_index: pd.DataFrame) -> list[str]:
    try:
        ids = list(select_is_submittable(RUN_ID))
        if len(ids) >= N_TARGET:
            return ids
    except Exception:
        pass
    try:
        ids = list(select_all_alphas(RUN_ID))
        if len(ids) >= N_TARGET:
            return ids
    except Exception:
        pass
    return list(alpha_index["alpha_id"].astype(str).unique())


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    pool = _safe_pool(alpha_index)
    if len(pool) < 2:
        return pool
    signs = _safe_signs(pool)
    R = load_member_is_returns(RUN_ID, pool, signs=signs)
    R = R.dropna(axis=1, how="all")
    if R.shape[1] < 2:
        return list(R.columns)

    # Regime-aware filters: year stability + drawdown discipline
    survivors: list[str] = []
    for a in R.columns:
        s = R[a].dropna()
        if len(s) < 60:
            continue
        if _max_drawdown(s) > DD_MAX:
            continue
        if not _year_stable(s, min_years=2):
            continue
        survivors.append(a)

    # Progressive fallbacks if filters too strict for this pool
    if len(survivors) < N_TARGET:
        survivors = [
            a for a in R.columns
            if R[a].dropna().shape[0] >= 60 and _max_drawdown(R[a].dropna()) <= 0.40
        ]
    if len(survivors) < N_TARGET:
        survivors = [a for a in R.columns if R[a].dropna().shape[0] >= 30]
    if len(survivors) < N_TARGET:
        survivors = list(R.columns)

    sharpes = {a: _annualized_sharpe(R[a]) for a in survivors}

    # Correlation dedup at rho=0.85, keeping highest IS Sharpe of each near-clone group
    kept = list(survivors)
    try:
        kept = list(correlation_dedup(
            R[survivors], threshold=DEDUP_RHO, keep_metric=sharpes
        ))
    except Exception:
        kept = list(survivors)
    if len(kept) < N_TARGET:
        try:
            kept = list(correlation_dedup(
                R[survivors], threshold=0.92, keep_metric=sharpes
            ))
        except Exception:
            kept = list(survivors)
    if len(kept) < N_TARGET:
        kept = list(survivors)

    # Greedy rank-composite: 0.5 * rank_sharpe_desc + 0.5 * rank_mean_abs_corr_asc
    R2 = R[kept].fillna(0.0)
    sharpe_series = pd.Series({a: sharpes.get(a, 0.0) for a in kept})

    seed = sharpe_series.idxmax()
    selected: list[str] = [seed]
    remaining = [a for a in kept if a != seed]

    while remaining and len(selected) < N_TARGET:
        sub_sharpe = sharpe_series.loc[remaining]
        sub_rank_sharpe = sub_sharpe.rank(ascending=False, method="min")

        corr_means: dict[str, float] = {}
        for a in remaining:
            cs: list[float] = []
            for sd in selected:
                try:
                    c = R2[a].corr(R2[sd])
                except Exception:
                    c = None
                if c is None:
                    continue
                cf = float(c)
                if math.isnan(cf):
                    continue
                cs.append(abs(cf))
            corr_means[a] = float(np.mean(cs)) if cs else 1.0
        corr_series = pd.Series(corr_means)
        sub_rank_ortho = corr_series.rank(ascending=True, method="min")

        score = 0.5 * sub_rank_sharpe + 0.5 * sub_rank_ortho
        pick = score.idxmin()
        selected.append(pick)
        remaining.remove(pick)

    if len(selected) < 2:
        # Final safety: pad with next-best by Sharpe so runner gets >= 2 members
        extras = [a for a in kept if a not in selected]
        extras.sort(key=lambda x: sharpes.get(x, 0.0), reverse=True)
        for x in extras:
            selected.append(x)
            if len(selected) >= 2:
                break
    return selected


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    if not member_ids:
        return {}
    signs = _safe_signs(member_ids)
    # Equal magnitude per member; sign embedded so runner combines raw W_a with deployable direction.
    # Avoids cov-inversion underweighting; Sum|c| = N gives row-L1 clamp meaningful headroom.
    coef: dict[str, float] = {}
    for a in member_ids:
        sgn = int(signs.get(a, 1))
        if sgn == 0:
            sgn = 1
        coef[a] = PER_MEMBER_MAGNITUDE * float(sgn)
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