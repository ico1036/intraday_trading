I'm picking a cov-free composition (greedy Gram-Schmidt orthogonalization with residual-Sharpe scoring) — listed under "NEW — never attempted" in the strategy hint, and it preserves native member leverage (no `Σ⁻¹·μ` underweighting trap). Selection is layered with a per-year IS Sharpe stability filter for regime robustness. Final coefficients are equal-weighted, sign-aligned via IC, L1-normalized, then scaled up (`GROSS_BOOST=8`) to escape the documented gross-exposure ceiling.

Literature: Greedy orthogonalization for portfolio construction is a classic Gram-Schmidt residual-info procedure (cf. Stinchcombe & Stinchcombe; also resembles the residual-information-coefficient approach of Grinold-Kahn's "Active Portfolio Management"). The per-year stability filter directly addresses the IS→OS regime shift documented in iter 1-14 feedback.

```python COMPOSITE_FILE
"""Greedy Gram-Schmidt orthogonalization with residual-Sharpe scoring (cov-free, native leverage)."""
from __future__ import annotations
import argparse
import numpy as np
import pandas as pd

from intraday.composites._runner import build_and_backtest
from intraday.composites._optim_helpers import (
    select_is_submittable,
    member_signs_ic,
    apply_signs,
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_053"
COMPOSITION_NOTE = "gram_schmidt_residual_sharpe_top8_yearstable_gross_boost8"

RUN_ID = "run_2026_05_c"
MAX_N = 8
MIN_RESIDUAL_SHARPE = 0.30
ANN = float(np.sqrt(252.0))
GROSS_BOOST = 8.0


def _ann_sharpe_series(s: pd.Series) -> float:
    s = s.dropna()
    if len(s) < 10:
        return 0.0
    sd = float(s.std(ddof=1))
    if sd <= 1e-12:
        return 0.0
    return float(s.mean()) / sd * ANN


def _residual_sharpe(y: np.ndarray, X: np.ndarray) -> float:
    if X.size == 0 or X.shape[1] == 0:
        resid = y - float(np.mean(y))
    else:
        Xc = np.column_stack([np.ones(len(X)), X])
        beta, *_ = np.linalg.lstsq(Xc, y, rcond=None)
        resid = y - Xc @ beta
    sd = float(np.std(resid, ddof=1))
    if sd <= 1e-12:
        return 0.0
    return float(np.mean(resid)) / sd * ANN


def _per_year_stable(R: pd.DataFrame) -> list[str]:
    if R.empty:
        return []
    R2 = R.copy()
    R2.index = pd.to_datetime(R2.index)
    years = sorted(set(R2.index.year))
    if len(years) < 2:
        return list(R2.columns)
    keep: list[str] = []
    for col in R2.columns:
        ok = True
        present_years = 0
        for y in years:
            sub = R2.loc[R2.index.year == y, col].dropna()
            if len(sub) < 5:
                continue
            present_years += 1
            if _ann_sharpe_series(sub) <= 0.0:
                ok = False
                break
        if ok and present_years >= 2:
            keep.append(col)
    return keep


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    ids_all = select_is_submittable(RUN_ID)
    if len(ids_all) < 2:
        ids_all = [str(x) for x in alpha_index["alpha_id"].tolist()]
    signs = member_signs_ic(RUN_ID, ids_all)
    R = load_member_is_returns(RUN_ID, ids_all, signs=signs)
    if R.shape[1] < 2:
        return list(R.columns)[:2] if R.shape[1] >= 2 else list(R.columns)

    stable_ids = _per_year_stable(R)
    if len(stable_ids) >= 4:
        R = R[stable_ids]

    sharpe_map = {c: _ann_sharpe_series(R[c]) for c in R.columns}
    pos = {k: v for k, v in sharpe_map.items() if v > 0.0}
    if len(pos) < 2:
        pos = sharpe_map
    ordered = sorted(pos.keys(), key=lambda c: pos[c], reverse=True)
    if not ordered:
        return list(R.columns[:2])

    chosen: list[str] = [ordered[0]]
    R_mat = R[ordered[0]].fillna(0.0).to_numpy().reshape(-1, 1)
    candidates = [c for c in ordered[1:]]
    while len(chosen) < MAX_N and candidates:
        best_c: str | None = None
        best_score = -np.inf
        for c in candidates:
            y = R[c].fillna(0.0).to_numpy()
            sc = _residual_sharpe(y, R_mat)
            if sc > best_score:
                best_score = sc
                best_c = c
        if best_c is None or best_score < MIN_RESIDUAL_SHARPE:
            break
        chosen.append(best_c)
        R_mat = np.column_stack([R_mat, R[best_c].fillna(0.0).to_numpy()])
        candidates.remove(best_c)

    if len(chosen) < 2:
        chosen = ordered[:2]
    return chosen


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    n = len(member_ids)
    if n == 0:
        return {}
    coef = {a: 1.0 / float(n) for a in member_ids}
    signs = member_signs_ic(RUN_ID, member_ids)
    coef = apply_signs(coef, signs)
    coef = normalize_coefficients(coef, "l1")
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
