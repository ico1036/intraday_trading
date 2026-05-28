Iteration 74 — picking the **Correlation-rank + Sharpe-rank greedy** cov-free composition (explicitly flagged as never attempted), combined with regime-robustness pre-filters (per-year IS Sharpe stability + IS max DD < 25%) that the leaderboard pattern says wins. Concentrated n=8. Equal-weight final set, then uniformly scaled up 8× to lift mean row L1 out of the 0.05 anemic-gross trap into the target [0.5, 0.8] band.

Why this combination:
- Cov-free greedy bypasses the 1/σ underweighting that has crushed every tangency/min-var attempt.
- Combined-rank score `0.5·rank_Sharpe + 0.5·rank_orth(|corr| to picks)` is conceptually a discrete Choueifaty-style diversification ratio without inverting Σ — robust to RMT noise and singular Σ.
- Year-stability + DD filter directly addresses the IS→OS regime-shift dominant failure mode noted in the spec.
- Sign-alignment via `member_signs_ic` before greedy build so the orthogonality measure operates on *deployable* directions, not raw weight streams.
- 8× lift on the final equal-weight dict is the simplest fix for the gross-exposure ceiling — prior cov-based composites all saturated at ~0.05 mean row L1; 8 members × (1/8 × 8) = unit-magnitude coefs that should land mean row L1 in the target band after `_runner`'s L1 clamp.

```python COMPOSITE_FILE
"""Cov-free greedy composite: combined Sharpe-rank + orthogonality-rank selection.

Method (Choueifaty-style diversification ratio, discretized & cov-free):
  1. Filter alphas by regime-robustness: positive IS Sharpe in EVERY IS sub-year
     (Lopez de Prado CSCV intuition, 2016) AND max IS drawdown < 25%.
  2. Seed with highest IS-Sharpe survivor.
  3. Greedy add next member by score = 0.5*rank_sharpe_desc + 0.5*rank_orth_asc,
     where rank_orth uses mean |corr| against already-picked members. Stop at n=8.
  4. Equal-weight, sign-align via IC, then lift gross 8x so mean composite row L1
     escapes the 0.05 anemic-leverage trap that crushed prior cov-based attempts.

References: Choueifaty & Coignard (2008) on diversification ratio; Lopez de Prado
(2016) CSCV/PBO on regime-robust IS validation; rank-aggregation greedy selection.
"""
from __future__ import annotations
import argparse
import numpy as np
import pandas as pd

from intraday.composites._runner import build_and_backtest
from intraday.composites._optim_helpers import (
    select_is_submittable,
    select_all_alphas,
    load_member_is_returns,
    member_signs_ic,
    apply_signs,
)

COMPOSITE_ID = "auto_074"
COMPOSITION_NOTE = "corr_sharpe_rank_greedy_yearstable_dd25_top8_eqw_gross_lift8x"

RUN_ID = "run_2026_05_c"
N_MEMBERS = 8
DD_MAX = 0.25
GROSS_LIFT = 8.0


def _max_drawdown(returns: pd.Series) -> float:
    r = returns.fillna(0.0)
    if r.empty:
        return 1.0
    eq = (1.0 + r).cumprod()
    peak = eq.cummax()
    dd = (eq / peak - 1.0).min()
    if not np.isfinite(dd):
        return 1.0
    return float(-dd)


def _annual_sharpe(returns: pd.Series) -> float:
    r = returns.dropna()
    if len(r) < 20:
        return -np.inf
    sd = float(r.std())
    if sd <= 0.0 or not np.isfinite(sd):
        return -np.inf
    return float(r.mean() / sd * np.sqrt(252.0))


def _year_stable(returns: pd.Series) -> bool:
    r = returns.dropna()
    if r.empty:
        return False
    if not isinstance(r.index, pd.DatetimeIndex):
        try:
            r.index = pd.to_datetime(r.index)
        except Exception:
            return False
    years = r.index.year.unique()
    if len(years) < 2:
        return False
    for y in years:
        sub = r[r.index.year == y]
        if len(sub) < 15:
            continue
        sd = float(sub.std())
        if sd <= 0.0 or not np.isfinite(sd):
            return False
        sh = sub.mean() / sd * np.sqrt(252.0)
        if not np.isfinite(sh) or sh <= 0.0:
            return False
    return True


def _build_pool(R: pd.DataFrame) -> list[str]:
    keep: list[str] = []
    for aid in R.columns:
        ser = R[aid].dropna()
        if len(ser) < 60:
            continue
        if _annual_sharpe(ser) <= 0.0:
            continue
        if _max_drawdown(ser) > DD_MAX:
            continue
        if not _year_stable(ser):
            continue
        keep.append(aid)
    return keep


def _greedy_rank_select(
    R: pd.DataFrame, sharpes: dict[str, float], n: int
) -> list[str]:
    cand = [a for a in R.columns if np.isfinite(sharpes.get(a, -np.inf))]
    if not cand:
        return []
    n = min(n, len(cand))
    seed = max(cand, key=lambda a: sharpes.get(a, -np.inf))
    picked: list[str] = [seed]
    remaining = [a for a in cand if a != seed]
    if not remaining:
        return picked
    abs_corr = R[cand].corr().abs()
    while len(picked) < n and remaining:
        sh_ser = pd.Series({a: sharpes.get(a, -np.inf) for a in remaining})
        rank_sh = sh_ser.rank(ascending=False, method="min")
        mean_corr = abs_corr.loc[remaining, picked].mean(axis=1).fillna(1.0)
        rank_orth = mean_corr.rank(ascending=True, method="min")
        score = 0.5 * rank_sh + 0.5 * rank_orth
        nxt = score.idxmin()
        picked.append(str(nxt))
        remaining.remove(str(nxt))
    return picked


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    ids = select_is_submittable(RUN_ID)
    if not ids or len(ids) < N_MEMBERS:
        ids = select_all_alphas(RUN_ID)
    if not ids:
        return []
    signs = member_signs_ic(RUN_ID, ids)
    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    if R is None or R.empty or R.shape[1] < 2:
        return list(R.columns) if R is not None else []

    pool = _build_pool(R)
    if len(pool) < N_MEMBERS:
        pool = [a for a in R.columns if _annual_sharpe(R[a].dropna()) > 0.0]
    if len(pool) < N_MEMBERS:
        pool = list(R.columns)

    sharpes = {a: _annual_sharpe(R[a].dropna()) for a in pool}
    R_pool = R[pool]
    picks = _greedy_rank_select(R_pool, sharpes, N_MEMBERS)
    if len(picks) < 2:
        ranked = sorted(R.columns, key=lambda a: _annual_sharpe(R[a].dropna()), reverse=True)
        picks = ranked[:N_MEMBERS]
    return picks


def member_weights(
    member_ids: list[str], alpha_index: pd.DataFrame
) -> dict[str, float]:
    if not member_ids:
        return {}
    n = len(member_ids)
    coef = {a: 1.0 / float(n) for a in member_ids}
    signs = member_signs_ic(RUN_ID, member_ids)
    coef = apply_signs(coef, signs)
    coef = {a: float(v) * GROSS_LIFT for a, v in coef.items()}
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
