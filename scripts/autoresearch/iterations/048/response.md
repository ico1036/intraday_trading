Looking at the leaderboard pattern and the URGENT cov-free guidance, I'll commit to the user-suggested **Greedy Gram-Schmidt residual-Sharpe orthogonalization** — a genuinely new (untried) cov-free angle that:

- Preserves native member leverage (no Σ⁻¹ ≈ 1/σ trap)
- Concentrates on 4-8 complementary alphas (sweet spot per leaderboard)
- Selects by *residual* Sharpe after projecting out span(picked), which is exactly the marginal-information criterion missing from Sharpe-only ranking
- Layers regime-aware filters on top: per-year IS Sharpe stability + max-DD < 25%

Mechanism — for each candidate `a`, the residual `r_a^⊥ = r_a − R_picked (R_picked^T R_picked)^{-1} R_picked^T r_a`. Sharpe(r_a^⊥) measures *novel* return per unit *novel* risk. This is Gram-Schmidt orthogonalization in return-space, in spirit related to Forward Selection regression and step-wise factor model construction (Fama-MacBeth style residualization). It is mathematically distinct from HRP/NCO/MV families — no covariance inversion, no shrinkage, no eigenbasis. It naturally truncates when no orthogonal info remains.

Coefficient magnitudes weighted by IS Sharpe of each pick, sign-aligned via `member_signs_ic`, L1-normalized to Σ|c|=1, then **multiplied by a 4× boost** to push the composite away from the empirical L1≈0.05 trap. The runner row-L1 clamp will catch any overshoot.

```python COMPOSITE_FILE
"""Cov-free greedy Gram-Schmidt residual-Sharpe composite (concentrated, regime-stable, exposure-scaled).

Method: forward-selection in return space. Order candidates by IS Sharpe; at each step pick the
candidate whose residual returns (after projecting onto span of already-picked) have the highest
Sharpe — i.e. the most novel risk-adjusted information. This avoids the Sigma-inverse / tangency
1/sigma weighting trap that has muted every prior cov-based composite to mean row L1 ~ 0.05.
Regime-aware filters layered on top: per-year IS Sharpe > 0 in every sub-year + max IS DD < 25%.
"""
from __future__ import annotations

import argparse
import math
import numpy as np
import pandas as pd

from intraday.composites._runner import build_and_backtest
from intraday.composites._optim_helpers import (
    member_signs_ic,
    apply_signs,
    select_is_submittable,
    select_all_alphas,
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_048"
COMPOSITION_NOTE = "greedy_gram_schmidt_residual_sharpe_top8_yearstable_dd25_boost4"

RUN_ID = "run_2026_05_c"
MAX_MEMBERS = 8
MIN_MEMBERS = 4
MIN_RESIDUAL_SHARPE = 0.30
DD_THRESHOLD = 0.25
COEFFICIENT_BOOST = 4.0
ANNUALIZER = math.sqrt(252.0)


def _sharpe(r: np.ndarray) -> float:
    if r.size < 5:
        return 0.0
    s = float(r.std(ddof=0))
    if s <= 1e-12:
        return 0.0
    return float(r.mean()) / s * ANNUALIZER


def _max_drawdown(r: pd.Series) -> float:
    x = r.fillna(0.0).values
    if x.size == 0:
        return 1.0
    eq = np.cumprod(1.0 + x)
    peak = np.maximum.accumulate(eq)
    dd = (eq / np.maximum(peak, 1e-12)) - 1.0
    return float(-dd.min())


def _year_stable(r: pd.Series) -> bool:
    idx = r.index
    if not isinstance(idx, pd.DatetimeIndex):
        try:
            idx = pd.to_datetime(idx)
        except Exception:
            return True
    years = sorted({int(d.year) for d in idx})
    if len(years) < 2:
        return True
    arr = r.fillna(0.0).values
    yrs = np.array([int(d.year) for d in idx])
    for y in years:
        sub = arr[yrs == y]
        if sub.size < 15:
            continue
        if _sharpe(sub) <= 0.0:
            return False
    return True


def _candidate_pool(run_id: str):
    ids = select_is_submittable(run_id)
    if len(ids) < 2:
        ids = select_all_alphas(run_id)
    signs = member_signs_ic(run_id, ids)
    R = load_member_is_returns(run_id, ids, signs=signs)
    R = R.dropna(axis=1, how="all").dropna(axis=0, how="all")
    return list(R.columns), R, signs


def _robust_filter(R: pd.DataFrame) -> list[str]:
    kept = []
    for a in R.columns:
        r = R[a].dropna()
        if len(r) < 30:
            continue
        if _sharpe(r.values) <= 0.0:
            continue
        if _max_drawdown(r) > DD_THRESHOLD:
            continue
        if not _year_stable(r):
            continue
        kept.append(a)
    return kept


def _residual_returns(y: np.ndarray, X: np.ndarray) -> np.ndarray:
    if X.size == 0 or X.shape[1] == 0:
        return y.copy()
    G = X.T @ X + 1e-8 * np.eye(X.shape[1])
    try:
        beta = np.linalg.solve(G, X.T @ y)
    except np.linalg.LinAlgError:
        beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    return y - X @ beta


def _greedy_orthogonal(R: pd.DataFrame) -> list[str]:
    cols = list(R.columns)
    if len(cols) < 2:
        return cols
    Rmat = R.fillna(0.0).values
    sharpe_per = {c: _sharpe(Rmat[:, i]) for i, c in enumerate(cols)}
    order = sorted(cols, key=lambda a: -sharpe_per[a])
    picked = [order[0]]
    remaining = order[1:]
    col_idx = {a: i for i, a in enumerate(cols)}

    while len(picked) < MAX_MEMBERS and remaining:
        X = Rmat[:, [col_idx[a] for a in picked]]
        best_a, best_score = None, -1e18
        for a in remaining:
            y = Rmat[:, col_idx[a]]
            r_perp = _residual_returns(y, X)
            score = _sharpe(r_perp)
            if score > best_score:
                best_score, best_a = score, a
        if best_a is None:
            break
        if best_score < MIN_RESIDUAL_SHARPE and len(picked) >= MIN_MEMBERS:
            break
        picked.append(best_a)
        remaining = [a for a in remaining if a != best_a]
    return picked


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    _, R, _ = _candidate_pool(RUN_ID)
    if R.shape[1] < 2:
        return list(R.columns)
    robust = _robust_filter(R)
    if len(robust) < MIN_MEMBERS:
        ranked_all = sorted(R.columns, key=lambda a: -_sharpe(R[a].fillna(0.0).values))
        robust = ranked_all[: max(MIN_MEMBERS * 2, 12)]
    R_r = R[robust]
    picked = _greedy_orthogonal(R_r)
    if len(picked) < 2:
        ranked = sorted(R.columns, key=lambda a: -_sharpe(R[a].fillna(0.0).values))
        picked = ranked[:5]
    return picked


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    if not member_ids:
        return {}
    signs = member_signs_ic(RUN_ID, member_ids)
    R = load_member_is_returns(RUN_ID, member_ids, signs=signs)
    R = R.dropna(axis=1, how="all")
    cols = [a for a in member_ids if a in R.columns]
    if not cols:
        coef = {a: 1.0 for a in member_ids}
        coef = normalize_coefficients(coef, "l1")
        return {k: v * COEFFICIENT_BOOST for k, v in coef.items()}

    Rc = R[cols].fillna(0.0)
    mags = {}
    for a in cols:
        s = _sharpe(Rc[a].values)
        mags[a] = float(max(s, 0.10))

    mags_norm = normalize_coefficients(mags, "l1")
    coef = apply_signs(mags_norm, {a: int(signs.get(a, 1)) for a in cols})
    coef = {k: float(v) * COEFFICIENT_BOOST for k, v in coef.items()}

    for a in member_ids:
        coef.setdefault(a, 0.0)
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
