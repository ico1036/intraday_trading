Looking at the empirical evidence: cov-based optimizers consistently underweight (mean row L1 ≈ 0.05 ⇒ OS Sharpe ≤ 0.84), prior "anti-bias" rules went OS-negative, and Gram-Schmidt failed 9/9. The user's hint asks for high-return / high-risk concentration; the data says n=6-10 with year-stability + DD-discipline is the sweet spot.

**Approach (idea family NOT in tried list — cov-FREE greedy rank composite):**

1. **Selection (regime-aware):**
   - Sign-align via `member_signs_ic` (deploy native sign).
   - Per-year IS Sharpe stability filter (Sharpe>0 in every IS year — survives 2022 bear, 2023 chop, 2024 pre-halving).
   - IS max drawdown < 25% (less tail-luck).
   - `correlation_dedup` at ρ=0.85, keep by IS Sharpe.
   - Greedy `0.5·rank(IS_Sharpe) + 0.5·rank(mean|corr| with picks)` to n=7.

2. **Weighting (no Σ inversion at all):**
   - Positive-Sharpe-proportional → L1-normalize via `normalize_coefficients`.
   - **Mandatory** gross-exposure rescale to target mean row L1 ≈ 0.65 via member return-vol proxy (the documented escape from the 1/σ-weighting trap).
   - `apply_signs` to return native-space coefficients.

References: Lopez de Prado (2016) HRP (correlation-distance diversification, no inversion); Choueifaty (2008) max-diversification ratio (rank-based proxy here). The rank-greedy heuristic is HRP-spirit but cov-free.

```python COMPOSITE_FILE
"""Cov-free greedy correlation-rank + Sharpe-rank composite with regime-stable
selection (HRP-spirit diversification a la Lopez de Prado 2016; rank-based
proxy for Choueifaty 2008 max-diversification, no covariance inversion).

Selection pipeline (IS-only, regime-aware):
  1. Sign-align with member_signs_ic.
  2. Per-year IS Sharpe stability (>0 in every IS year) -> regime robust.
  3. IS max-drawdown < 25%.
  4. correlation_dedup at rho=0.85, keep by IS Sharpe.
  5. Greedy add by 0.5*rank(IS_Sharpe_desc) + 0.5*rank(mean|corr|_with_picks_asc)
     until n=7 members.

Weighting (cov-free):
  - Positive-IS-Sharpe-proportional, L1-normalised via normalize_coefficients.
  - Rescaled to mean gross exposure ~0.65 (the documented fix for the
    1/sigma underweighting trap).
  - apply_signs returns native-sign coefficients for the runner.
"""
from __future__ import annotations

import argparse
import math

import numpy as np
import pandas as pd

from intraday.composites._runner import build_and_backtest
from intraday.composites._optim_helpers import (
    apply_signs,
    correlation_dedup,
    load_member_is_returns,
    member_signs_ic,
    normalize_coefficients,
    select_all_alphas,
    select_is_submittable,
)

COMPOSITE_ID = "auto_065"
COMPOSITION_NOTE = "covfree_greedy_corrank_sharperank_yearstab_dd25_top7_gross065"

RUN_ID = "run_2026_05_c"
TARGET_N = 7
TARGET_GROSS = 0.65
RHO_THRESHOLD = 0.85
DD_LIMIT = -0.25
TRADING_DAYS = 252
MIN_YEAR_OBS = 10


def _annual_sharpe(s: pd.Series) -> float:
    s = s.dropna()
    if len(s) < 5:
        return 0.0
    sd = float(s.std())
    if sd < 1e-12:
        return 0.0
    return float(s.mean() / sd * math.sqrt(TRADING_DAYS))


def _max_drawdown(s: pd.Series) -> float:
    s = s.dropna()
    if len(s) == 0:
        return 0.0
    cum = (1.0 + s).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak.replace(0.0, np.nan)
    val = dd.min()
    if pd.isna(val):
        return 0.0
    return float(val)


def _years_of(index) -> "np.ndarray | None":
    try:
        di = pd.DatetimeIndex(index)
        return np.asarray(di.year)
    except Exception:
        return None


def _selection_pipeline(run_id: str) -> list[str]:
    ids_all = list(select_is_submittable(run_id))
    if len(ids_all) < 5:
        ids_all = list(select_all_alphas(run_id))
    if not ids_all:
        return []

    try:
        signs = member_signs_ic(run_id, ids_all)
    except Exception:
        signs = {a: 1 for a in ids_all}

    try:
        R = load_member_is_returns(run_id, ids_all, signs=signs)
    except Exception:
        R = pd.DataFrame()
    if R.empty or R.shape[1] < 2:
        return list(R.columns)[: min(R.shape[1], TARGET_N)] if R.shape[1] else ids_all[:2]

    cols = list(R.columns)

    # 1) per-year stability
    years_arr = _years_of(R.index)
    if years_arr is not None and len(set(years_arr)) >= 2:
        stable: list[str] = []
        df = R.copy()
        df["__year__"] = years_arr
        for c in cols:
            sub = df[[c, "__year__"]].dropna()
            if sub.empty:
                continue
            ok = True
            yrs_seen = 0
            for _, grp in sub.groupby("__year__")[c]:
                if len(grp) < MIN_YEAR_OBS:
                    continue
                yrs_seen += 1
                if _annual_sharpe(grp) <= 0.0:
                    ok = False
                    break
            if ok and yrs_seen >= 1:
                stable.append(c)
        if len(stable) < 5:
            stable = cols[:]
    else:
        stable = cols[:]

    # 2) drawdown discipline
    dd_ok = [c for c in stable if _max_drawdown(R[c]) > DD_LIMIT]
    if len(dd_ok) < 5:
        dd_ok = stable

    # 3) IS Sharpe ranking metric for dedup + greedy
    sharpe_map = {c: _annual_sharpe(R[c]) for c in dd_ok}

    # 4) correlation dedup
    R_sub = R[dd_ok].copy()
    try:
        kept = list(correlation_dedup(R_sub, threshold=RHO_THRESHOLD, keep_metric=sharpe_map))
    except Exception:
        kept = list(dd_ok)
    kept = [k for k in kept if k in sharpe_map]
    if len(kept) < 2:
        kept = sorted(dd_ok, key=lambda x: -sharpe_map.get(x, -1e9))[: max(5, min(len(dd_ok), TARGET_N))]
    if len(kept) < 2:
        return list(R.columns)[:2]

    # 5) greedy rank-blend selection
    sorted_by_sharpe = sorted(kept, key=lambda x: -sharpe_map[x])
    sharpe_rank_map = {a: i for i, a in enumerate(sorted_by_sharpe)}

    selected: list[str] = [sorted_by_sharpe[0]]
    remaining = sorted_by_sharpe[1:]
    target_n = min(TARGET_N, len(sorted_by_sharpe))

    while len(selected) < target_n and remaining:
        mean_abs_corr: dict[str, float] = {}
        for cand in remaining:
            corrs: list[float] = []
            for s in selected:
                try:
                    sub = R[[cand, s]].dropna()
                    if len(sub) < 5:
                        continue
                    c_val = sub.corr().iloc[0, 1]
                    if not np.isnan(c_val):
                        corrs.append(abs(float(c_val)))
                except Exception:
                    pass
            mean_abs_corr[cand] = float(np.mean(corrs)) if corrs else 0.0
        ortho_sorted = sorted(remaining, key=lambda x: mean_abs_corr[x])
        ortho_rank_map = {a: i for i, a in enumerate(ortho_sorted)}

        scored = sorted(
            remaining,
            key=lambda x: 0.5 * sharpe_rank_map[x] + 0.5 * ortho_rank_map[x],
        )
        best = scored[0]
        selected.append(best)
        remaining.remove(best)

    return selected


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    selected = _selection_pipeline(RUN_ID)
    if len(selected) >= 2:
        return selected
    # robust fallback
    ids = list(select_is_submittable(RUN_ID))[:5]
    if len(ids) < 2:
        ids = list(select_all_alphas(RUN_ID))[:5]
    return ids


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    member_ids = list(member_ids)
    if not member_ids:
        return {}

    try:
        signs = member_signs_ic(RUN_ID, member_ids)
    except Exception:
        signs = {m: 1 for m in member_ids}

    try:
        R = load_member_is_returns(RUN_ID, member_ids, signs=signs)
    except Exception:
        R = pd.DataFrame()

    avail = [m for m in member_ids if m in R.columns]

    if len(avail) < 1:
        n = max(len(member_ids), 1)
        eq = {m: 1.0 / n for m in member_ids}
        try:
            return apply_signs(eq, signs)
        except Exception:
            return eq

    sharpes: dict[str, float] = {}
    for c in avail:
        sh = _annual_sharpe(R[c])
        sharpes[c] = max(sh, 0.0)
    s_total = sum(sharpes.values())
    if s_total <= 1e-12:
        raw: dict[str, float] = {m: 1.0 for m in avail}
    else:
        raw = {m: sharpes[m] for m in avail}

    # ensure every requested id has an entry
    for m in member_ids:
        raw.setdefault(m, 0.0)

    # L1-normalise to sum |c| = 1
    try:
        coef = dict(normalize_coefficients(raw, "l1"))
    except Exception:
        denom = sum(abs(v) for v in raw.values()) or 1.0
        coef = {k: v / denom for k, v in raw.items()}

    # gross-exposure rescale to target mean row L1 ~= TARGET_GROSS
    sigma = {m: float(R[m].std()) for m in avail}
    est_gross = sum(abs(coef.get(m, 0.0)) * sigma.get(m, 0.0) for m in avail)
    if est_gross > 1e-9 and np.isfinite(est_gross):
        scale = TARGET_GROSS / est_gross
    else:
        # degenerate proxy: aggressive uniform up-scale (cov-free escape)
        scale = 8.0
    # sanity clamp on scale to avoid runaway amplification
    scale = float(np.clip(scale, 1.0, 50.0))

    coef = {k: float(v * scale) for k, v in coef.items()}

    try:
        coef = apply_signs(coef, signs)
    except Exception:
        coef = {k: float(v) * float(signs.get(k, 1)) for k, v in coef.items()}

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
