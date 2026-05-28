Looking at the spec, iteration 111 has clear constraints:

1. **Avoid the 1/σ-weighting trap**: every prior tangency/min-var attempt collapsed to mean row L1 ≈ 0.05. The spec mandates cov-FREE composition this iteration.
2. **Skip Gram-Schmidt** (0/9 success). The other two cov-free options remain.
3. **Regime-shift dominates**: per-year IS Sharpe stability + DD discipline + concentrated n∈[5,8] is the only filter combo with positive evidence.
4. **Coefficient post-scaling is mandatory** to escape the 0.05 row-L1 ceiling.

Idea family already covered: cluster-centroid + equal-weight is loosely covered by `auto_013_stability_ir_cluster_median_repr_eqweigh`. The **correlation-rank + Sharpe-rank greedy composite score** (Choueifaty 2008 diversification motivation; rank-based to avoid scale sensitivity in the mixing) is genuinely untried.

Recipe for iter 111: regime-aware filter (positive yearly Sharpe in every IS sub-year ∧ max IS DD > −25% ∧ IS Sharpe > 0.4) → correlation dedup at ρ=0.85 → greedy add by `0.5·rank_sharpe + 0.5·rank_orthogonal_to_picked` → top-7 → 1/N + sign-aware → normalize_coefficients L1 → vol-proxy post-scale to target gross ≈ 0.65 with multiplier clamped to [5, 30].

```python COMPOSITE_FILE
"""Cov-free composite: correlation-rank + Sharpe-rank greedy with regime-aware filtering.

Method: Top-K assembly using a rank-aggregation score that balances IS Sharpe (exploit) and
orthogonality to already-picked members (explore), per the spec's cov-FREE menu
("Correlation-rank + Sharpe-rank composite score"). Member-pool filter is regime-aware:
positive per-calendar-year IS Sharpe across all IS sub-years (Lopez de Prado, 2018,
regime-conditional CV) and max IS drawdown deeper than -25% disqualified (Calmar-style
discipline). Diversification-ratio motivation: Choueifaty & Coignard (2008). Final
1/N over the picked set, sign-aligned via IC dead-band (member_signs_ic), normalized to
Sigma|c|=1, then post-scaled using daily-return-vol proxy to target mean row L1 ~= 0.65
(the spec's mandatory gross-exposure fix that escapes the row-L1~=0.05 ceiling all prior
covariance-based optimizers fell into).
"""
from __future__ import annotations
import argparse
import numpy as np
import pandas as pd

from intraday.composites._runner import build_and_backtest
from intraday.composites._optim_helpers import (
    correlation_dedup,
    member_signs_ic,
    apply_signs,
    select_all_alphas,
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_111"
COMPOSITION_NOTE = "corrrank_sharperank_yrstable_dd25_top7_gross065"

RUN_ID = "run_2026_05_c"
TARGET_N = 7
DD_FLOOR = -0.25
SHARPE_FLOOR = 0.4
DEDUP_RHO = 0.85
TARGET_GROSS = 0.65
SCALE_MIN = 5.0
SCALE_MAX = 30.0


def _max_drawdown(s: pd.Series) -> float:
    s = s.dropna()
    if len(s) < 10:
        return -1.0
    cum = (1.0 + s).cumprod()
    peak = cum.cummax()
    dd = (cum / peak - 1.0).min()
    return float(dd)


def _per_year_min_sharpe(R: pd.DataFrame) -> pd.Series:
    R2 = R.copy()
    try:
        R2.index = pd.to_datetime(R2.index)
    except Exception:
        return pd.Series(1.0, index=R.columns)
    years = sorted(set(R2.index.year))
    cols = {}
    for y in years:
        sub = R2[R2.index.year == y]
        if len(sub) < 20:
            continue
        sd = sub.std().replace(0, np.nan)
        ysh = sub.mean() / sd
        cols[y] = ysh
    if len(cols) < 2:
        return pd.Series(1.0, index=R.columns)
    per_year = pd.DataFrame(cols)
    return per_year.min(axis=1)


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    all_ids = select_all_alphas(RUN_ID)
    if len(all_ids) < 2:
        return list(all_ids)
    signs = member_signs_ic(RUN_ID, all_ids)
    R = load_member_is_returns(RUN_ID, all_ids, signs=signs)
    cols = list(R.columns)
    if len(cols) < 2:
        return cols

    sd_all = R.std().replace(0, np.nan)
    sharpe = (R.mean() / sd_all) * np.sqrt(252.0)
    sharpe = sharpe.dropna()

    min_yr = _per_year_min_sharpe(R).reindex(sharpe.index)
    dds = pd.Series({c: _max_drawdown(R[c]) for c in sharpe.index})

    mask_full = (
        (min_yr.fillna(-1.0) > 0.0)
        & (dds.fillna(-1.0) > DD_FLOOR)
        & (sharpe > SHARPE_FLOOR)
    )
    eligible = sharpe.index[mask_full].tolist()

    if len(eligible) < TARGET_N:
        mask_relax = (
            (dds.reindex(sharpe.index).fillna(-1.0) > DD_FLOOR)
            & (sharpe > SHARPE_FLOOR)
        )
        eligible = sharpe.index[mask_relax].tolist()
    if len(eligible) < TARGET_N:
        eligible = sharpe[sharpe > 0.3].sort_values(ascending=False).head(40).index.tolist()
    if len(eligible) < TARGET_N:
        eligible = sharpe.sort_values(ascending=False).head(40).index.tolist()
    if len(eligible) < 3:
        return sorted(sharpe.sort_values(ascending=False).head(5).index.tolist())

    try:
        keep_metric = {a: float(sharpe.loc[a]) for a in eligible}
        deduped = correlation_dedup(R[eligible], threshold=DEDUP_RHO, keep_metric=keep_metric)
    except Exception:
        deduped = list(eligible)
    if len(deduped) < 3:
        deduped = list(eligible)

    R_d = R[deduped]
    corr = R_d.corr().abs().fillna(0.0)
    sh = sharpe.loc[deduped]

    picked: list[str] = [sh.idxmax()]
    pool = [c for c in deduped if c not in picked]
    while len(picked) < TARGET_N and pool:
        sh_pool = sh.loc[pool]
        rank_sharpe = sh_pool.rank(ascending=False, method="min")
        mean_corr = corr.loc[pool, picked].mean(axis=1)
        rank_orth = mean_corr.rank(ascending=True, method="min")
        score = 0.5 * rank_sharpe + 0.5 * rank_orth
        best = score.idxmin()
        picked.append(best)
        pool.remove(best)

    if len(picked) < 2:
        picked = sorted(sharpe.sort_values(ascending=False).head(5).index.tolist())
    return picked


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    if not member_ids:
        return {}
    signs = member_signs_ic(RUN_ID, member_ids)
    R = load_member_is_returns(RUN_ID, member_ids, signs=signs)
    members = [m for m in member_ids if m in R.columns]
    if len(members) < 2:
        members = list(member_ids)

    n = len(members)
    coef = {m: 1.0 / float(n) for m in members}
    sgn = {m: int(signs.get(m, 1)) for m in members}
    coef = apply_signs(coef, sgn)
    coef = normalize_coefficients(coef, "l1")

    try:
        R_mem = R[[m for m in members if m in R.columns]]
        sigma_a = R_mem.std()
        arr = np.array([abs(float(coef.get(m, 0.0))) for m in members], dtype=float)
        sigmas = np.array([float(sigma_a.get(m, 0.01)) for m in members], dtype=float)
        est_gross = float((arr * sigmas).sum())
    except Exception:
        est_gross = 0.0

    if est_gross > 1e-8:
        scale = TARGET_GROSS / est_gross
    else:
        scale = 10.0
    scale = float(min(max(scale, SCALE_MIN), SCALE_MAX))
    coef = {k: float(v) * scale for k, v in coef.items()}
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
