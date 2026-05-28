I'll generate the composite alpha file. The system role for this task is explicit — emit one fenced `COMPOSITE_FILE` block, no tools. (Plan-mode reminder is the generic default; the specialized role here is text emission, not editing.)

**Reasoning (mechanism + literature):**
The empirical evidence is overwhelming: cov-based optimizers (`Σ⁻¹·μ`, `Σ⁻¹·1`) produce 1/σ-weighted coefficients that collapse to mean row L1 ≈ 0.05 after the runner's L1 clamp — the composite leaves 95% of risk on the table. The prompt explicitly flags **greedy Gram–Schmidt orthogonalization** (Strang, *Introduction to Linear Algebra*; analogous to forward-stepwise selection by partial F-test) as a cov-free alternative that has never been tried.

The pick:
- Filter pool by **drawdown discipline** (max IS DD < 22%) and **per-year IS stability** (positive mean return in every calendar IS year). Both have explicit live-leaderboard evidence.
- **Greedy Gram–Schmidt residual-Sharpe selection** (n ≤ 8): order by raw IS Sharpe; iteratively add the candidate whose IS-returns residual *after projecting out the chosen basis* has the highest residual Sharpe. Stop when residual Sharpe < 0.30 or n=8.
- Weight by per-step **residual Sharpe** (orthogonal contribution metric, not raw vol).
- Sign-align via `member_signs_ic`; L1-normalize then boost coefficients by a fixed empirical factor (TARGET_GROSS · 5×) to overcome the documented ~10× under-weighting trap.

This is squarely in the "cov-FREE composition methods to try (NEW)" bucket and matches the n∈[5,8] / year-stable / DD-disciplined winning pattern, with one genuinely new angle: residual-Sharpe rather than corr/Sharpe rank.

```python COMPOSITE_FILE
"""Greedy Gram-Schmidt residual-Sharpe composite (Strang); cov-free, year-stable, DD-disciplined."""
from __future__ import annotations

import argparse
import math

import numpy as np
import pandas as pd

from intraday.composites._runner import build_and_backtest
from intraday.composites._optim_helpers import (
    load_member_is_returns,
    member_signs_ic,
    normalize_coefficients,
    select_is_submittable,
)

COMPOSITE_ID = "auto_057"
COMPOSITION_NOTE = "gram_schmidt_resid_sharpe_year_stable_dd22_n8_gross065"

RUN_ID = "run_2026_05_c"
MAX_MEMBERS = 8
MIN_RESID_SHARPE = 0.30
DD_LIMIT = 0.22
MIN_YEAR_BARS = 30
TARGET_GROSS = 0.65
GROSS_BOOST = 5.0


def _sharpe(r: np.ndarray) -> float:
    if r.size == 0:
        return 0.0
    s = float(np.std(r))
    if s <= 0.0 or not np.isfinite(s):
        return 0.0
    return float(np.mean(r) / s * math.sqrt(252.0))


def _max_dd(r: np.ndarray) -> float:
    if r.size == 0:
        return 1.0
    eq = np.cumprod(1.0 + r)
    peak = np.maximum.accumulate(eq)
    dd = eq / peak - 1.0
    return float(-dd.min())


def _year_stable(s: pd.Series) -> bool:
    idx = pd.to_datetime(s.index)
    years = idx.year.values
    for y in np.unique(years):
        sub = s.values[years == y]
        if len(sub) < MIN_YEAR_BARS:
            continue
        if float(np.mean(sub)) <= 0.0:
            return False
    return True


def _filter_candidates(R: pd.DataFrame) -> list[str]:
    out = []
    for a in R.columns:
        col = R[a].dropna()
        if len(col) < 90:
            continue
        if _max_dd(col.values) > DD_LIMIT:
            continue
        if not _year_stable(col):
            continue
        out.append(a)
    return out


def _load_pool() -> tuple[pd.DataFrame, dict]:
    ids = select_is_submittable(RUN_ID)
    if not ids:
        return pd.DataFrame(), {}
    signs = member_signs_ic(RUN_ID, ids, dead_band=0.005)
    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    R = R.dropna(axis=1, how="all")
    return R, signs


def _project_residual(B: np.ndarray, v: np.ndarray) -> np.ndarray:
    G = B.T @ B + 1e-8 * np.eye(B.shape[1])
    try:
        G_inv = np.linalg.pinv(G)
    except Exception:
        return v
    coef = G_inv @ (B.T @ v)
    return v - B @ coef


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    R, _ = _load_pool()
    if R.shape[1] == 0:
        return []

    filtered = _filter_candidates(R)
    if len(filtered) < 3:
        sh_all = {a: _sharpe(R[a].dropna().values) for a in R.columns}
        filtered = sorted(sh_all, key=lambda k: sh_all[k], reverse=True)[:30]

    sub = R[filtered]
    common = sub.dropna()
    if len(common) < 60:
        common = sub.fillna(0.0)
    if len(common) < 30 or common.shape[1] < 2:
        sh_all = {a: _sharpe(R[a].dropna().values) for a in R.columns}
        ordered_fb = sorted(sh_all, key=lambda k: sh_all[k], reverse=True)
        return ordered_fb[: min(MAX_MEMBERS, len(ordered_fb))]

    sh_map = {a: _sharpe(common[a].values) for a in common.columns}
    ordered = sorted(common.columns.tolist(), key=lambda a: sh_map[a], reverse=True)

    chosen = [ordered[0]]
    rest = ordered[1:]

    while len(chosen) < MAX_MEMBERS and rest:
        B = common[chosen].values
        best_a = None
        best_sh = -np.inf
        for c in rest:
            v = common[c].values
            resid = _project_residual(B, v)
            rsh = _sharpe(resid)
            if rsh > best_sh:
                best_sh = rsh
                best_a = c
        if best_a is None or best_sh < MIN_RESID_SHARPE:
            break
        chosen.append(best_a)
        rest = [x for x in rest if x != best_a]

    if len(chosen) < 2:
        chosen = ordered[: min(MAX_MEMBERS, len(ordered))]
    if len(chosen) < 2:
        chosen = list(R.columns[: min(MAX_MEMBERS, R.shape[1])])
    return chosen


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    if not member_ids:
        return {}

    signs = member_signs_ic(RUN_ID, member_ids, dead_band=0.005)
    R = load_member_is_returns(RUN_ID, member_ids, signs=signs)
    R = R.dropna(axis=1, how="all")
    actual = [a for a in member_ids if a in R.columns]

    if len(actual) < 2:
        n = max(len(member_ids), 1)
        flat = {a: 1.0 / n for a in member_ids}
        flat = normalize_coefficients(flat, "l1")
        return {
            a: flat[a] * float(signs.get(a, 1)) * TARGET_GROSS * GROSS_BOOST
            for a in member_ids
        }

    common = R[actual].dropna()
    if len(common) < 60:
        common = R[actual].fillna(0.0)

    weights: dict[str, float] = {}
    basis: list[str] = []
    for a in actual:
        v = common[a].values
        if not basis:
            rsh = _sharpe(v)
        else:
            B = common[basis].values
            resid = _project_residual(B, v)
            rsh = _sharpe(resid)
        weights[a] = max(float(rsh), 0.10)
        basis.append(a)

    for a in member_ids:
        if a not in weights:
            weights[a] = 0.0

    abs_w = {a: abs(weights[a]) for a in member_ids}
    total = sum(abs_w.values())
    if total <= 0.0:
        n = len(member_ids)
        norm = {a: 1.0 / n for a in member_ids}
    else:
        norm = normalize_coefficients(abs_w, "l1")

    out = {
        a: float(norm[a]) * float(signs.get(a, 1)) * TARGET_GROSS * GROSS_BOOST
        for a in member_ids
    }
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
```
