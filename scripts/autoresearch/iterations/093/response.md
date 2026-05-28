I'll generate iteration 93 as the harness expects: a single fenced `COMPOSITE_FILE` block. Note: the trailing plan-mode reminder conflicts with the explicit task instruction ("No tools, no questions, no chit-chat. Free-form rationale is allowed BEFORE the fenced block"); honoring the task-specific contract that is the entire purpose of this invocation.

**Rationale.** Prior iterations have shown the central failure is regime change (IS 2022-2024 → OS 2024-2026) plus chronic gross-exposure underuse (composite mean row L1 ≈ 0.05 while individual top alphas hit 1.0+). The cov-based optimizers (tangency / min-var / Neumann / NCO / DRP / max-div) all produce `w ∝ Σ⁻¹·μ`, which is naturally 1/σ-weighted and never scales up. The user's exploit-near-winners pattern is converging on: n∈[5,8] + year-stability + DD discipline + dedup + post-scale.

I'll take a **cov-free** angle this iteration — explicitly avoiding the failed-9/9 Gram-Schmidt route — and instead do **Black-Litterman empirical-Bayes alpha-pooling** (Idzorek/Meucci flavour): treat the cross-sectional mean IS-Sharpe as the equilibrium prior, treat each alpha's own IS-Sharpe as a noisy view, posterior = credibility-weighted shrinkage `(1−λ)·sh + λ·grand`. This is statistically motivated (Stein-type shrinkage toward the grand mean reduces selection variance), and unlike the prior errored auto_004, I:

1. Avoid LW shrinkage entirely (cov-free) — no matrix inversion to fail.
2. Apply selection filters BEFORE EB weighting: per-year stability (positive Sharpe in every IS calendar year, captures regime robustness across the LUNA/FTX/2023-chop/2024-rally micro-regimes), DD < 25% discipline, and ρ-dedup at 0.85.
3. Concentrate on top-K=6 (the documented sweet spot: auto_002 n=6, auto_003 n=10 lead).
4. Mandatory gross rescale at the end: L1-normalize then multiply by 8× to push effective gross into the [0.3, 0.9] band the runner needs.

Sign alignment via `member_signs_ic` is applied symmetrically on both the scoring R (so EB-Sharpe reflects the deployable side) and the coefficient dict (so the submitted weights flip IC<0 members back to the deployable orientation).

Idea family is fresh: no prior iter combines (EB-Bayes shrinkage) × (year-stability) × (DD-discipline) × (cov-free Sharpe-proportional weighting) × (post-scale-to-native-gross).

```python COMPOSITE_FILE
"""Black-Litterman empirical-Bayes alpha-pooling with year-stability and drawdown filters, correlation dedup, cov-free Sharpe-proportional top-K weighting, and post-scale to native gross exposure."""
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

COMPOSITE_ID = "auto_093"
COMPOSITION_NOTE = "bl_eb_shrink_yearstable_dd25_dedup085_topk6_covfree_gross8x"

RUN_ID = "run_2026_05_c"
TOP_K = 6
DD_MAX = 0.25
DEDUP_RHO = 0.85
EB_LAMBDA = 0.4
GROSS_SCALE = 8.0


def _yearly_stability(R: pd.DataFrame) -> dict:
    idx = R.index
    if not isinstance(idx, pd.DatetimeIndex):
        idx = pd.to_datetime(idx, errors="coerce")
    R = R.copy()
    R.index = idx
    R = R.loc[~R.index.isna()]
    years = R.index.year
    out: dict = {}
    for col in R.columns:
        per_year = R[col].groupby(years).mean()
        if len(per_year) < 2:
            out[col] = False
            continue
        out[col] = bool((per_year > 0).all())
    return out


def _max_drawdown(R: pd.DataFrame) -> dict:
    out: dict = {}
    for col in R.columns:
        x = R[col].fillna(0.0).values
        if len(x) == 0:
            out[col] = 0.0
            continue
        eq = np.cumsum(x)
        peak = np.maximum.accumulate(eq)
        dd = eq - peak
        out[col] = float(-dd.min())
    return out


def _is_sharpe(R: pd.DataFrame) -> pd.Series:
    mu = R.mean()
    sd = R.std(ddof=0).replace(0.0, np.nan)
    return (mu / sd) * math.sqrt(252.0)


def select_members(alpha_index: pd.DataFrame) -> list:
    ids = select_is_submittable(RUN_ID)
    if len(ids) < 4:
        ids = select_all_alphas(RUN_ID)
    if len(ids) < 2:
        ids = [str(a) for a in alpha_index["alpha_id"].astype(str).tolist()]

    signs = member_signs_ic(RUN_ID, ids)
    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    if R.shape[1] < 2:
        return list(R.columns)

    stable = _yearly_stability(R)
    keep_stable = [c for c in R.columns if stable.get(c, False)]
    if len(keep_stable) >= 4:
        R = R[keep_stable]

    dd = _max_drawdown(R)
    keep_dd = [c for c in R.columns if dd.get(c, 1.0) < DD_MAX]
    if len(keep_dd) >= 4:
        R = R[keep_dd]

    sh = _is_sharpe(R).dropna()
    if len(sh) < 2:
        cols = list(R.columns)[:TOP_K]
        return cols if len(cols) >= 2 else list(R.columns)

    grand = float(sh.mean())
    eb = (1.0 - EB_LAMBDA) * sh + EB_LAMBDA * grand
    R_eb = R[eb.index]

    try:
        deduped = correlation_dedup(R_eb, DEDUP_RHO, keep_metric=eb.to_dict())
    except Exception:
        deduped = list(eb.sort_values(ascending=False).head(2 * TOP_K).index)

    if len(deduped) < 2:
        deduped = list(eb.sort_values(ascending=False).head(TOP_K).index)

    eb_sub = eb.reindex(deduped).dropna()
    top = list(eb_sub.sort_values(ascending=False).head(TOP_K).index)
    if len(top) < 2:
        top = list(sh.sort_values(ascending=False).head(max(2, TOP_K)).index)
    return top


def member_weights(member_ids: list, alpha_index: pd.DataFrame) -> dict:
    signs = member_signs_ic(RUN_ID, member_ids)
    R = load_member_is_returns(RUN_ID, member_ids, signs=signs)
    loaded = [m for m in member_ids if m in R.columns]

    if not loaded:
        coef = {m: 1.0 for m in member_ids}
        coef = normalize_coefficients(coef, "l1")
        return {k: float(v) * GROSS_SCALE for k, v in coef.items()}

    R = R[loaded]
    sh = _is_sharpe(R).fillna(0.0)
    grand = float(sh.mean()) if len(sh) else 0.0
    eb = (1.0 - EB_LAMBDA) * sh + EB_LAMBDA * grand
    eb = eb.clip(lower=0.05)

    coef = {m: float(eb.get(m, 0.05)) for m in loaded}
    for m in member_ids:
        if m not in coef:
            coef[m] = 0.0

    coef = apply_signs(coef, signs)
    coef = normalize_coefficients(coef, "l1")
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
