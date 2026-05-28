Looking at the task: I'm an automated quant-research code generator with an explicit contract to produce ONE fenced `python COMPOSITE_FILE` block. This is text output, not a filesystem edit, so it doesn't violate the plan-mode constraint on edits/tools.

**Reasoning for auto_052:**

The prompt flags the dominant blocker: every prior covariance-based optimizer (tangency / min-var / Neumann-inverse) collapses `mean_row_l1` to ~0.05 because `w ∝ Σ⁻¹·μ` is naturally 1/σ-weighted, leaving 95% of the gross-exposure budget unused. The prompt explicitly proposes **cov-FREE** alternatives that "preserve native member leverage" and lists Greedy Gram-Schmidt orthogonalization as a fresh untried angle.

**Method:** Greedy residual-Sharpe selection via Gram-Schmidt orthogonalization (related to Brodie–Daubechies–Friedlander–De Mol 2009 *Sparse and stable Markowitz portfolios* and forward-stepwise regression on returns). 

1. Load `select_is_submittable("run_2026_05_c")`, sign-align with `member_signs_ic`.
2. Filter pool by **per-year IS Sharpe stability** (positive Sharpe in every IS calendar year — the top regime-aware angle in the leaderboard pattern) and **max IS DD < 25%**.
3. Dedup at ρ=0.85 keyed by IS Sharpe.
4. **Greedy Gram-Schmidt**: seed with highest IS Sharpe; for each next candidate, regress its IS return stream on the already-selected set (with intercept), score by annualized Sharpe of the *residual*; pick top, repeat. Stop at n=8 or residual Sharpe < 0.3.
5. Weights ∝ residual Sharpe (rewards orthogonal new info), L1-normalized, sign-aligned to the original weight panels via `apply_signs`.
6. **Gross-exposure rescale**: multiply by 8× to combat the 10–20× cancellation dilution observed in prior attempts. The runner's row-L1 cap at 1.0 acts as a natural ceiling.

This is cov-FREE (no inversion, no shrinkage), regime-aware (per-year stability), concentrated (n≤8), and explicitly addresses the gross-exposure ceiling.

```python COMPOSITE_FILE
"""Greedy Gram-Schmidt residual-Sharpe sparse portfolio (Brodie-Daubechies-De Mol 2009 style).

Cov-FREE composition: iteratively select members by their annualized Sharpe AFTER
orthogonalizing IS returns against the already-selected set. Weights proportional to
residual Sharpe (rewarding orthogonal new info), then rescaled to lift mean row L1
out of the 1/sigma trap that crushed prior tangency/min-var attempts.
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
    correlation_dedup,
)

COMPOSITE_ID = "auto_052"
COMPOSITION_NOTE = "greedy_gs_residual_sharpe_yearstable_dd25_n8_gross8x"

RUN_ID = "run_2026_05_c"
N_MAX = 8
RESIDUAL_SHARPE_FLOOR = 0.30
MIN_IS_SHARPE = 0.40
DD_THRESHOLD = 0.25
CORR_DEDUP_RHO = 0.85
GROSS_MULTIPLIER = 8.0


def _ann_sharpe(r: np.ndarray) -> float:
    r = np.asarray(r, dtype=float)
    if r.size < 5:
        return 0.0
    sd = float(np.std(r, ddof=1))
    if not np.isfinite(sd) or sd <= 1e-12:
        return 0.0
    mu = float(np.mean(r))
    if not np.isfinite(mu):
        return 0.0
    return mu / sd * math.sqrt(252.0)


def _max_dd(r: np.ndarray) -> float:
    r = np.asarray(r, dtype=float)
    if r.size == 0:
        return 1.0
    eq = np.cumsum(r)
    peak = np.maximum.accumulate(eq)
    dd = peak - eq
    return float(np.max(dd))


def _per_year_stable(s: pd.Series) -> bool:
    if s.size < 60:
        return False
    idx = s.index
    try:
        years = idx.year
    except AttributeError:
        return True
    bucket: dict = {}
    for y, v in zip(years, s.values):
        bucket.setdefault(int(y), []).append(float(v))
    n_buckets = 0
    for y, vals in bucket.items():
        arr = np.asarray(vals, dtype=float)
        if arr.size < 20:
            continue
        n_buckets += 1
        if _ann_sharpe(arr) <= 0.0:
            return False
    return n_buckets >= 2


def _residual_sharpe(y: np.ndarray, X: np.ndarray) -> float:
    n = y.shape[0]
    if X.size == 0 or X.shape[1] == 0:
        return _ann_sharpe(y)
    X_aug = np.column_stack([np.ones(n), X])
    try:
        beta, *_ = np.linalg.lstsq(X_aug, y, rcond=None)
    except np.linalg.LinAlgError:
        return _ann_sharpe(y)
    resid = y - X_aug @ beta
    return _ann_sharpe(resid)


def _load_pool() -> tuple[pd.DataFrame, dict, dict]:
    ids = select_is_submittable(RUN_ID)
    if len(ids) < 4:
        ids = select_all_alphas(RUN_ID)
    signs = member_signs_ic(RUN_ID, ids)
    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    if R is None or R.shape[1] == 0:
        return pd.DataFrame(), {}, {}
    R = R.dropna(how="all", axis=1).fillna(0.0)
    keep_cols = [c for c in R.columns if float(R[c].std(ddof=1)) > 1e-9]
    R = R.loc[:, keep_cols]
    return R, signs, {c: _ann_sharpe(R[c].values) for c in R.columns}


def _filter_pool(R: pd.DataFrame, sharpe_map: dict, strict: bool) -> tuple[pd.DataFrame, dict]:
    sh_floor = MIN_IS_SHARPE if strict else 0.20
    dd_thr = DD_THRESHOLD if strict else DD_THRESHOLD * 1.6
    keep: list[str] = []
    for c in R.columns:
        if sharpe_map.get(c, 0.0) < sh_floor:
            continue
        if _max_dd(R[c].values) > dd_thr:
            continue
        if strict and not _per_year_stable(R[c]):
            continue
        keep.append(c)
    if not keep:
        return pd.DataFrame(), {}
    sub = R.loc[:, keep]
    sub_sh = {c: sharpe_map[c] for c in keep}
    if len(keep) > 12:
        try:
            kept = correlation_dedup(sub, CORR_DEDUP_RHO, keep_metric=sub_sh)
            if kept:
                sub = sub.loc[:, kept]
                sub_sh = {c: sub_sh[c] for c in kept if c in sub_sh}
        except Exception:
            pass
    return sub, sub_sh


def _greedy_select(R: pd.DataFrame, sharpe_map: dict, n_max: int, floor: float) -> list[str]:
    cols = list(R.columns)
    if len(cols) <= 1:
        return cols
    selected: list[str] = []
    remaining = list(cols)
    seed = max(remaining, key=lambda c: sharpe_map.get(c, 0.0))
    selected.append(seed)
    remaining.remove(seed)
    while remaining and len(selected) < n_max:
        X = R[selected].values
        best_id = None
        best_rs = -1e18
        for cand in remaining:
            rs = _residual_sharpe(R[cand].values, X)
            if rs > best_rs:
                best_rs = rs
                best_id = cand
        if best_id is None or best_rs < floor:
            break
        selected.append(best_id)
        remaining.remove(best_id)
    return selected


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    R_all, _signs, sharpe_all = _load_pool()
    if R_all.shape[1] < 2:
        return list(R_all.columns)
    R_f, sh_f = _filter_pool(R_all, sharpe_all, strict=True)
    if R_f.shape[1] < 3:
        R_f, sh_f = _filter_pool(R_all, sharpe_all, strict=False)
    if R_f.shape[1] < 2:
        ranked = sorted(sharpe_all.items(), key=lambda kv: kv[1], reverse=True)
        return [k for k, _ in ranked[:6]]
    chosen = _greedy_select(R_f, sh_f, N_MAX, RESIDUAL_SHARPE_FLOOR)
    if len(chosen) < 2:
        ranked = sorted(sh_f.items(), key=lambda kv: kv[1], reverse=True)
        chosen = [k for k, _ in ranked[: max(4, len(ranked) // 2)]]
    return chosen


def _residual_sharpe_path(R: pd.DataFrame, order: list[str]) -> dict:
    out: dict = {}
    if not order:
        return out
    out[order[0]] = max(_ann_sharpe(R[order[0]].values), 0.10)
    for i in range(1, len(order)):
        X = R[order[: i]].values
        y = R[order[i]].values
        rs = _residual_sharpe(y, X)
        out[order[i]] = max(rs, 0.05)
    return out


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    if not member_ids:
        return {}
    signs = member_signs_ic(RUN_ID, member_ids)
    R = load_member_is_returns(RUN_ID, member_ids, signs=signs)
    if R is None or R.shape[1] == 0:
        n = len(member_ids)
        return {m: GROSS_MULTIPLIER / n for m in member_ids}
    R = R.fillna(0.0)
    cols = [c for c in member_ids if c in R.columns and float(R[c].std(ddof=1)) > 1e-9]
    if not cols:
        n = len(member_ids)
        return {m: GROSS_MULTIPLIER / n for m in member_ids}
    sharpe_map = {c: _ann_sharpe(R[c].values) for c in cols}
    order: list[str] = []
    remaining = list(cols)
    seed = max(remaining, key=lambda c: sharpe_map[c])
    order.append(seed)
    remaining.remove(seed)
    while remaining:
        X = R[order].values
        best_id = None
        best_rs = -1e18
        for cand in remaining:
            rs = _residual_sharpe(R[cand].values, X)
            if rs > best_rs:
                best_rs = rs
                best_id = cand
        if best_id is None:
            break
        order.append(best_id)
        remaining.remove(best_id)
    raw = _residual_sharpe_path(R, order)
    for m in member_ids:
        if m not in raw:
            raw[m] = 0.0
    total_abs = sum(abs(v) for v in raw.values())
    if total_abs <= 1e-12:
        coef = {m: 1.0 / len(member_ids) for m in member_ids}
    else:
        coef = normalize_coefficients(raw, "l1")
    coef = apply_signs(coef, signs)
    coef = {k: float(v) * GROSS_MULTIPLIER for k, v in coef.items()}
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
