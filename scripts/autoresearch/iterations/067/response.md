Brief rationale: iteration 67 needs a cov-free composition that hasn't been tried. The strongest unexplored vector in the prompt is the **Correlation-rank + Sharpe-rank Borda composite score** — flagged as "NEW — never attempted." It avoids the 1/σ underweighting trap that has capped every cov-inverse attempt at mean row L1 ≈ 0.05, while still pursuing Choueifaty-style orthogonal diversification combined with selection-bias defense (year-stability + max-DD discipline). I'll pair it with IC-sign alignment (Grinold & Kahn FLA) and final L1-normalised coefficients scaled by 3× so the runner's row-L1 clamp at 1.0 binds and we hold real gross. Member count 7 sits in the empirically winning [5,8] window.

```python COMPOSITE_FILE
"""Borda-rank greedy selection: IS-Sharpe rank blended 50/50 with orthogonality
rank (mean |corr| vs already-picked, asc), filtered by per-year IS positivity
and IS max-DD < 22%. Cov-free, sidesteps the Sigma^-1 1/sigma underweighting
trap. Cites Choueifaty (2008) maximum diversification + Lopez de Prado (2018)
regime-stability filtering + Grinold-Kahn FLA via IC-sign alignment. Members
equal-weighted post-selection, sign-aligned, L1-normalised, then boosted so
the runner's row-L1 gross budget binds.
"""
from __future__ import annotations
import argparse
import math
import numpy as np
import pandas as pd

from intraday.composites._runner import build_and_backtest
from intraday.composites._optim_helpers import (
    select_is_submittable,
    select_all_alphas,
    load_member_is_returns,
    member_signs_ic,
    apply_signs,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_067"
COMPOSITION_NOTE = "borda_sharpe_orth_rank_yrstable_dd22_eqw_ic_l1_boost3"
RUN_ID = "run_2026_05_c"
N_TARGET = 7
MAX_DD = 0.22
GROSS_BOOST = 3.0


def _max_dd_from_ret(r: pd.Series) -> float:
    if len(r) < 2:
        return 1.0
    cum = (1.0 + r.fillna(0.0)).cumprod()
    peak = cum.cummax()
    rel = (cum / peak.replace(0.0, np.nan)) - 1.0
    val = float(-rel.min(skipna=True))
    return val if math.isfinite(val) else 1.0


def _year_stable(r: pd.Series) -> bool:
    idx = r.index
    if not isinstance(idx, pd.DatetimeIndex):
        try:
            r = r.copy()
            r.index = pd.to_datetime(idx)
        except Exception:
            return True
    yrs = sorted({d.year for d in r.index})
    if len(yrs) < 2:
        return True
    for y in yrs:
        sub = r[r.index.year == y]
        if len(sub) < 5:
            continue
        std = float(sub.std())
        if not math.isfinite(std) or std <= 0:
            return False
        sh = float(sub.mean()) / std
        if not math.isfinite(sh) or sh <= 0:
            return False
    return True


def _score_universe(ids: list[str], R: pd.DataFrame) -> tuple[list[str], dict[str, float]]:
    sharpe_map: dict[str, float] = {}
    survivors: list[str] = []
    for c in list(R.columns):
        r = R[c].dropna()
        if len(r) < 30:
            continue
        std = float(r.std())
        if not math.isfinite(std) or std <= 0:
            continue
        sh = float(r.mean()) / std
        if not math.isfinite(sh) or sh <= 0:
            continue
        if not _year_stable(r):
            continue
        if _max_dd_from_ret(r) > MAX_DD:
            continue
        sharpe_map[c] = sh
        survivors.append(c)
    return survivors, sharpe_map


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    ids = select_is_submittable(RUN_ID)
    if not ids or len(ids) < N_TARGET:
        ids = select_all_alphas(RUN_ID)
    if not ids:
        return []

    signs = member_signs_ic(RUN_ID, ids)
    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    if R is None or R.shape[1] < 2:
        return list(ids)[: max(2, N_TARGET)]

    survivors, sharpe_map = _score_universe(ids, R)

    if len(survivors) < N_TARGET:
        # relax filters — drop year-stability + DD, keep only positive-Sharpe
        sharpe_map = {}
        survivors = []
        for c in list(R.columns):
            r = R[c].dropna()
            if len(r) < 20:
                continue
            std = float(r.std())
            if not math.isfinite(std) or std <= 0:
                continue
            sh = float(r.mean()) / std
            if not math.isfinite(sh) or sh <= 0:
                continue
            sharpe_map[c] = sh
            survivors.append(c)

    if len(survivors) < 2:
        fallback = list(R.columns)[: max(2, N_TARGET)]
        return fallback

    if len(survivors) <= N_TARGET:
        return survivors

    # Borda greedy: 50% Sharpe-rank + 50% orthogonality-rank
    Rs = R[survivors].fillna(0.0)
    corr = Rs.corr().fillna(0.0)

    ranked_sharpe = sorted(survivors, key=lambda x: sharpe_map[x], reverse=True)
    sharpe_rank = {a: i for i, a in enumerate(ranked_sharpe)}  # 0 = best

    chosen: list[str] = [ranked_sharpe[0]]
    remaining = [a for a in survivors if a != chosen[0]]

    while len(chosen) < N_TARGET and remaining:
        mean_abs: dict[str, float] = {}
        for a in remaining:
            vals = [abs(float(corr.at[a, c])) for c in chosen if c in corr.columns and a in corr.index]
            mean_abs[a] = float(np.mean(vals)) if vals else 1.0
        ortho_sorted = sorted(remaining, key=lambda x: mean_abs[x])
        ortho_rank = {a: i for i, a in enumerate(ortho_sorted)}  # 0 = most orthogonal
        combined = {a: 0.5 * sharpe_rank[a] + 0.5 * ortho_rank[a] for a in remaining}
        next_pick = min(remaining, key=lambda x: combined[x])
        chosen.append(next_pick)
        remaining.remove(next_pick)

    return chosen


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    if not member_ids:
        return {}
    signs = member_signs_ic(RUN_ID, member_ids)
    n = len(member_ids)
    coef: dict[str, float] = {a: 1.0 / float(n) for a in member_ids}
    coef = apply_signs(coef, signs)
    coef = normalize_coefficients(coef, scheme="l1")
    coef = {k: float(v) * GROSS_BOOST for k, v in coef.items()}
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
