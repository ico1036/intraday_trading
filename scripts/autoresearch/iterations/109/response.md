Looking at this task: I need to generate iteration 109 of a composite alpha file. The user wants code output (the task framing is explicit: "Respond with exactly one fenced ```python COMPOSITE_FILE block ... No tools, no questions, no chit-chat"). This is a pure text-generation output, no file edits or tool calls — Plan mode's read-only restriction doesn't apply since I'm not editing files or invoking tools.

**Strategy chosen — Cov-free greedy rank-blend (Sharpe-rank + Orthogonality-rank)**

Rationale:
- The URGENT section warns every cov-based optimizer underweights by ~10×; user explicitly flags cov-free as the blocker fix.
- Gram-Schmidt was failed 9/9 (skip).
- Three cov-free options remain: cluster-centroid (already tried as auto_013), pure 1/N top-K, and **correlation-rank + Sharpe-rank blend** — the last has not appeared in the file listing.
- Stack the regime-aware filters that the leaderboard pattern endorses: per-year IS Sharpe stability, max IS DD < 25%, correlation dedup ρ=0.85.
- Target n=7 members (sweet spot 5-8).
- Final scale: equal-weight (cov-free preserves native leverage), normalize to Σ|c|=1, multiply by 8 so combined mean row L1 lands ~0.5-0.7 (per the URGENT 5-15× fix).

Literature anchor: greedy diversity selection blending Sharpe rank with mean-|corr| orthogonality rank is a classic information-coefficient-aware portfolio construction (Grinold-Kahn style "breadth via orthogonality") and is listed in the menu as the third cov-free method.

```python COMPOSITE_FILE
"""Greedy rank-blend (Sharpe-rank + orthogonality-rank) cov-free composite.

Selection: filter by per-year IS Sharpe stability and IS max drawdown < 25%,
dedup at |rho|=0.85, then greedily grow to n=7 by minimising
0.5*rank_sharpe + 0.5*rank_mean_abs_corr_with_picked.  No covariance
inversion (Grinold-Kahn breadth-via-orthogonality, cov-free family,
per the literature menu's correlation-rank + Sharpe-rank composite score).
Equal-weight inside the kept set, sign-aligned via IC, then scaled so
Sum|c|=8 to lift gross exposure off the 0.05 floor that all cov-based
attempts hit.
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
    apply_signs,
    select_is_submittable,
    select_all_alphas,
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_109"
COMPOSITION_NOTE = "covfree_rankblend_sharpe_ortho_yearstable_dd25_n7_gross8x"

RUN_ID = "run_2026_05_c"
N_TARGET = 7
DD_MAX = 0.25
DEDUP_RHO = 0.85
GROSS_SCALE = 8.0  # multiply normalized Sum|c|=1 by this to lift mean row L1


def _is_sharpe(r: pd.Series) -> float:
    r = r.dropna()
    if len(r) < 20:
        return -np.inf
    sd = float(r.std())
    if not np.isfinite(sd) or sd <= 0.0:
        return -np.inf
    return float(r.mean() / sd * math.sqrt(252.0))


def _max_drawdown(r: pd.Series) -> float:
    r = r.dropna()
    if r.empty:
        return 1.0
    cum = (1.0 + r).cumprod()
    peak = cum.cummax()
    dd = cum / peak - 1.0
    return float(-dd.min())


def _year_stable(r: pd.Series, min_years: int = 2) -> bool:
    r = r.dropna()
    if r.empty or not isinstance(r.index, pd.DatetimeIndex):
        return False
    df = r.to_frame("v")
    df["yr"] = df.index.year
    years = sorted(df["yr"].unique())
    counted = 0
    for y in years:
        sub = df.loc[df["yr"] == y, "v"]
        if len(sub) < 20:
            continue
        sd = float(sub.std())
        if not np.isfinite(sd) or sd <= 0.0:
            return False
        sh = float(sub.mean() / sd * math.sqrt(252.0))
        if sh <= 0.0:
            return False
        counted += 1
    return counted >= min_years


def _build_pool() -> tuple[pd.DataFrame, dict[str, float]]:
    ids = select_is_submittable(RUN_ID)
    if len(ids) < 10:
        ids = select_all_alphas(RUN_ID)
    signs = member_signs_ic(RUN_ID, ids)
    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    R = R.dropna(axis=1, how="all")
    R = R.loc[:, R.count() >= 60]

    keep: list[str] = []
    sharpes: dict[str, float] = {}
    for a in R.columns:
        r = R[a]
        sh = _is_sharpe(r)
        if not np.isfinite(sh) or sh <= 0.0:
            continue
        if _max_drawdown(r) > DD_MAX:
            continue
        if not _year_stable(r):
            continue
        keep.append(a)
        sharpes[a] = sh

    # Fallback: if too few survive the strict gate, relax year-stability
    if len(keep) < N_TARGET:
        keep = []
        sharpes = {}
        for a in R.columns:
            r = R[a]
            sh = _is_sharpe(r)
            if not np.isfinite(sh) or sh <= 0.0:
                continue
            if _max_drawdown(r) > 0.35:
                continue
            keep.append(a)
            sharpes[a] = sh
    # Second fallback: top by sharpe regardless
    if len(keep) < N_TARGET:
        keep = []
        sharpes = {}
        for a in R.columns:
            sh = _is_sharpe(R[a])
            if np.isfinite(sh) and sh > 0.0:
                keep.append(a)
                sharpes[a] = sh

    R_f = R[keep]
    if R_f.shape[1] > N_TARGET:
        deduped = correlation_dedup(R_f, DEDUP_RHO, keep_metric=sharpes)
        if len(deduped) >= 2:
            R_f = R_f[deduped]
            sharpes = {a: sharpes[a] for a in deduped}
    return R_f, sharpes


def _greedy_rank_blend(R: pd.DataFrame, sharpes: dict[str, float], n: int) -> list[str]:
    cands = list(R.columns)
    if len(cands) <= n:
        return cands
    corr = R.corr().abs()
    # seed with top Sharpe
    picked = [max(cands, key=lambda a: sharpes.get(a, -np.inf))]
    remaining = [a for a in cands if a not in picked]
    while len(picked) < n and remaining:
        # rank by Sharpe descending (lower rank index = better)
        sh_order = sorted(remaining, key=lambda a: -sharpes.get(a, -np.inf))
        rank_sh = {a: i for i, a in enumerate(sh_order)}
        # rank by mean |corr| with picked ascending (lower = more orthogonal = better)
        mean_corr = {
            a: float(corr.loc[a, picked].mean()) if a in corr.index else 1.0
            for a in remaining
        }
        co_order = sorted(remaining, key=lambda a: mean_corr[a])
        rank_co = {a: i for i, a in enumerate(co_order)}
        blended = {a: 0.5 * rank_sh[a] + 0.5 * rank_co[a] for a in remaining}
        nxt = min(remaining, key=lambda a: blended[a])
        picked.append(nxt)
        remaining.remove(nxt)
    return picked


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    R, sharpes = _build_pool()
    if R.shape[1] < 2:
        # absolute last-resort fallback so the runner does not get an empty list
        ids = select_is_submittable(RUN_ID)
        if len(ids) < 2:
            ids = select_all_alphas(RUN_ID)
        return list(ids[:max(N_TARGET, 2)])
    picks = _greedy_rank_blend(R, sharpes, N_TARGET)
    if len(picks) < 2:
        # belt-and-suspenders: always hand back at least 2 ids
        extras = [a for a in R.columns if a not in picks]
        picks = (picks + extras)[:max(2, len(picks))]
    return picks


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    signs = member_signs_ic(RUN_ID, member_ids)
    # equal weight then sign-align
    coef = {a: 1.0 for a in member_ids}
    coef = apply_signs(coef, signs)
    # normalise to Sum|c|=1 first (helper expects a dict)
    coef = normalize_coefficients(coef, "l1")
    # lift gross exposure off the 0.05 floor that every cov-based attempt
    # collapses to.  Each member's native row-L1 is typically ~0.05-0.10,
    # so Sum|c|=GROSS_SCALE pushes combined mean row L1 toward 0.5-0.7
    # before the runner's row-L1<=1 clamp.
    coef = {a: float(v) * GROSS_SCALE for a, v in coef.items()}
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
