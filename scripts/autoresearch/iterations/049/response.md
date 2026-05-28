**Rationale — iter 49 (cov-FREE Gram-Schmidt residual-Sharpe, fresh family)**

Every cov-based attempt in this run has hit the gross-exposure ceiling: `Σ⁻¹·μ`-style weights are intrinsically 1/σ-scaled, so post row-L1 clamping the panel sits at mean L1 ≈ 0.05 and leaves 95% of the risk budget unused. The user has explicitly flagged this and asked for cov-FREE composition. The leaderboard hint also says n=5–8 with year-stability + DD discipline lands top-5.

Method: **Greedy Gram-Schmidt orthogonalization on IS returns** (cf. Lopez de Prado 2019 §7 "orthogonalization of features" + Brodie/Daubechies/De Mol 2009 on residual-information ranking). For each candidate alpha I project its IS return series onto the span of already-picked alphas and rank candidates by the *annualized Sharpe of the residual* — this measures genuinely new directional information, not redundant variance. Stop when residual Sharpe < 0.30 or n=8 reached. Magnitudes set to residual Sharpe (which is naturally large for the seed and decays for later picks), then L1-normalized and rescaled by 12× to push mean row L1 into [0.5, 0.9].

Regime-aware pre-filters (per the empirical 1-14 evidence): (a) per-year IS-Sharpe stability — drop alphas with any negative-Sharpe calendar year; (b) max IS drawdown ≤ 25%. Sign-alignment via `member_signs_ic` applied to the IS returns matrix used for the Gram-Schmidt search, then re-applied to the magnitudes when writing the final signed coefficients. No covariance inverse anywhere.

Idea family is genuinely new in this run (no prior attempt used Gram-Schmidt residual ranking).

```python COMPOSITE_FILE
"""Greedy Gram-Schmidt orthogonalization on IS returns: pick alphas by residual Sharpe after projecting out prior picks (cov-free; Lopez de Prado 2019 feature-orthogonalization; Brodie et al 2009)."""
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
    normalize_coefficients,
)

COMPOSITE_ID = "auto_049"
COMPOSITION_NOTE = "gram_schmidt_residual_sharpe_top8_yearstable_dd25_grossx12"

RUN_ID = "run_2026_05_c"
MAX_MEMBERS = 8
MIN_RESID_SHARPE = 0.30
DD_MAX_ABS = 0.25
POOL_TOPK = 60
GROSS_SCALE = 12.0


def _ann_sharpe(x: np.ndarray) -> float:
    if x.size < 2:
        return -np.inf
    mu = float(np.mean(x))
    sd = float(np.std(x, ddof=1))
    if sd < 1e-12:
        return -np.inf
    return (mu / sd) * np.sqrt(252.0)


def _per_year_stable(R: pd.DataFrame) -> list[str]:
    idx = R.index
    if not isinstance(idx, pd.DatetimeIndex):
        try:
            idx = pd.to_datetime(idx)
        except Exception:
            return list(R.columns)
    years = sorted(set(idx.year))
    if len(years) <= 1:
        return list(R.columns)
    keep: list[str] = []
    for c in R.columns:
        col = R[c].to_numpy()
        ok = True
        for y in years:
            sub = col[idx.year == y]
            if sub.size < 5:
                continue
            mu = float(np.mean(sub))
            sd = float(np.std(sub, ddof=1))
            if sd < 1e-12 or mu <= 0.0:
                ok = False
                break
        if ok:
            keep.append(c)
    return keep


def _max_dd_abs(returns: np.ndarray) -> float:
    if returns.size == 0:
        return 0.0
    eq = np.cumprod(1.0 + np.nan_to_num(returns, nan=0.0))
    peak = np.maximum.accumulate(eq)
    dd = (eq - peak) / np.where(peak == 0.0, 1.0, peak)
    return float(abs(dd.min()))


def _dd_filter(R: pd.DataFrame, max_abs: float) -> list[str]:
    return [c for c in R.columns if _max_dd_abs(R[c].to_numpy()) <= max_abs]


def _greedy_order(R: pd.DataFrame, sharpes: dict[str, float]) -> list[str]:
    cols = [c for c in R.columns if np.isfinite(sharpes.get(c, -np.inf))]
    if not cols:
        return []
    seed = max(cols, key=lambda c: sharpes[c])
    selected: list[str] = [seed]
    remaining: list[str] = [c for c in cols if c != seed]
    while len(selected) < MAX_MEMBERS and remaining:
        B = R[selected].to_numpy()
        try:
            gram_inv = np.linalg.pinv(B.T @ B)
        except np.linalg.LinAlgError:
            break
        best_id = None
        best_sh = -np.inf
        for cid in remaining:
            y = R[cid].to_numpy()
            beta = gram_inv @ (B.T @ y)
            resid = y - B @ beta
            sh = _ann_sharpe(resid)
            if sh > best_sh:
                best_sh = sh
                best_id = cid
        if best_id is None or best_sh < MIN_RESID_SHARPE:
            break
        selected.append(best_id)
        remaining.remove(best_id)
    return selected


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
    return list(dict.fromkeys(ids))


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    ids = _candidate_pool()
    if len(ids) < 2:
        return ids
    try:
        signs = member_signs_ic(RUN_ID, ids)
    except Exception:
        signs = {a: 1 for a in ids}
    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    if R is None or R.shape[1] < 2:
        return ids[:5]

    cols = [c for c in R.columns if R[c].std(ddof=1) > 1e-12]
    R = R[cols]
    if R.shape[1] < 2:
        return cols[:5] if cols else ids[:5]

    stable = _per_year_stable(R)
    if len(stable) >= 8:
        R = R[stable]

    dd_ok = _dd_filter(R, DD_MAX_ABS)
    if len(dd_ok) >= 8:
        R = R[dd_ok]

    sharpes = {c: _ann_sharpe(R[c].to_numpy()) for c in R.columns}
    ranked = sorted(R.columns, key=lambda c: sharpes.get(c, -np.inf), reverse=True)
    pool = ranked[:POOL_TOPK]
    R_pool = R[pool]
    sh_pool = {c: sharpes[c] for c in pool}

    selected = _greedy_order(R_pool, sh_pool)
    if len(selected) < 2:
        selected = ranked[:5]
    return selected


def _replay_residual_sharpes(R: pd.DataFrame, ordered: list[str]) -> dict[str, float]:
    out: dict[str, float] = {}
    basis: list[str] = []
    for m in ordered:
        if m not in R.columns:
            out[m] = 0.5
            continue
        y = R[m].to_numpy()
        if not basis:
            out[m] = max(_ann_sharpe(y), 0.5)
        else:
            B = R[basis].to_numpy()
            try:
                beta = np.linalg.pinv(B.T @ B) @ (B.T @ y)
                resid = y - B @ beta
                sh = _ann_sharpe(resid)
            except np.linalg.LinAlgError:
                sh = 0.3
            if not np.isfinite(sh):
                sh = 0.3
            out[m] = max(sh, 0.3)
        basis.append(m)
    return out


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    if not member_ids:
        return {}
    try:
        signs = member_signs_ic(RUN_ID, member_ids)
    except Exception:
        signs = {m: 1 for m in member_ids}
    signs_full = {m: int(signs.get(m, 1)) for m in member_ids}

    R = load_member_is_returns(RUN_ID, member_ids, signs=signs_full)
    if R is None or R.shape[1] == 0:
        mags = {m: 1.0 for m in member_ids}
    else:
        mags = _replay_residual_sharpes(R, member_ids)
        for m in member_ids:
            mags.setdefault(m, 0.5)

    mags = normalize_coefficients(mags, "l1")
    coef = apply_signs(mags, signs_full)
    coef = {k: float(v) * GROSS_SCALE for k, v in coef.items()}
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
