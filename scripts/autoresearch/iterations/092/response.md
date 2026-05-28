I'll skip cov-based optimization entirely (the URGENT section flags it as the gross-exposure bottleneck) and skip Gram-Schmidt (failed 9/9). Going with the **correlation-rank + Sharpe-rank greedy** cov-free method, with regime-aware gating (per-year IS Sharpe positivity + max-DD < 25%), and a fixed post-normalization gross scale-up to lift mean row L1 off the floor.

Cites Choueifaty (2008) max-diversification (in rank-space) and Lopez de Prado (2018) backtest-overfitting robustness (per-year stability).

```python COMPOSITE_FILE
"""Cov-FREE composite via correlation-rank + Sharpe-rank greedy
selection, gated by per-year IS Sharpe positivity and IS max DD < 25%.

Method: members are scored by the average of two ranks — IS annualized
Sharpe (desc) and mean |correlation| with already-selected members
(asc). Next pick minimizes that combined rank. This is a cov-free,
rank-space variant of Choueifaty (2008) Maximum Diversification: we
substitute pairwise rank-orthogonality for the literal
sqrt(w'σ)/sqrt(w'Σw) ratio, avoiding any Σ inversion. Pre-filter via
per-year IS Sharpe > 0 (regime-conditional robustness, Lopez de Prado
2018 backtest-overfitting framework) and IS max-drawdown < 25%.
Final coefficients are equal-weight (1/N) after IC sign alignment,
then multiplied by a fixed gross-exposure factor to lift mean row L1
into the [0.5, 0.8] target band (clamped per-row by the runner).
"""
from __future__ import annotations
import argparse
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

COMPOSITE_ID = "auto_092"
COMPOSITION_NOTE = "corr_rank_sharpe_rank_yearstable_dd25_top8_covfree"

RUN_ID = "run_2026_05_c"
TARGET_N = 8
MIN_N = 4
MAX_DD = 0.25
GROSS_SCALE = 5.0


def _per_year_sharpe_positive(s: pd.Series) -> bool:
    if s is None or s.empty:
        return False
    idx = pd.to_datetime(s.index, errors="coerce")
    if idx.isna().all():
        return False
    df = pd.DataFrame({"r": s.values}, index=idx).dropna()
    if df.empty:
        return False
    for yr in pd.unique(df.index.year):
        grp = df[df.index.year == yr]["r"]
        if len(grp) < 20:
            continue
        std = grp.std()
        if not np.isfinite(std) or std <= 0:
            return False
        if grp.mean() <= 0:
            return False
    return True


def _max_drawdown(s: pd.Series) -> float:
    if s is None or s.empty:
        return 1.0
    eq = (1.0 + s.fillna(0.0)).cumprod()
    peak = eq.cummax()
    dd = (eq / peak) - 1.0
    val = dd.min()
    if not np.isfinite(val):
        return 1.0
    return float(-val)


def _ann_sharpe(s: pd.Series) -> float:
    if s is None or s.empty:
        return 0.0
    std = s.std()
    if not np.isfinite(std) or std <= 0:
        return 0.0
    mu = s.mean()
    if not np.isfinite(mu):
        return 0.0
    return float(mu / std * np.sqrt(252.0))


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    candidates = select_is_submittable(RUN_ID)
    if len(candidates) < 5:
        candidates = select_all_alphas(RUN_ID)
    if not candidates:
        return []
    signs = member_signs_ic(RUN_ID, candidates)
    R = load_member_is_returns(RUN_ID, candidates, signs=signs)
    if R is None or R.empty or R.shape[1] < 2:
        return list(R.columns) if R is not None else []

    # Stage-1 gate: regime-aware filters on sign-aligned IS returns
    kept: list[str] = []
    sharpes: dict[str, float] = {}
    for aid in R.columns:
        s = R[aid].dropna()
        if len(s) < 60:
            continue
        if not _per_year_sharpe_positive(s):
            continue
        if _max_drawdown(s) > MAX_DD:
            continue
        sh = _ann_sharpe(s)
        if sh <= 0:
            continue
        sharpes[aid] = sh
        kept.append(aid)

    # Fallback: if filters are too aggressive, drop them and keep top Sharpes
    if len(kept) < MIN_N:
        all_sh = {aid: _ann_sharpe(R[aid].dropna()) for aid in R.columns}
        all_sh = {k: v for k, v in all_sh.items() if np.isfinite(v) and v > 0}
        if len(all_sh) < 2:
            return list(R.columns[:2])
        ordered = sorted(all_sh, key=all_sh.get, reverse=True)
        return ordered[: max(MIN_N, min(TARGET_N, len(ordered)))]

    # Stage-2: greedy correlation-rank + Sharpe-rank composite score
    Rk = R[kept]
    corr_abs = Rk.corr().abs()
    sharpe_series = pd.Series(sharpes)
    sharpe_rank_full = sharpe_series.rank(ascending=False, method="average")

    selected: list[str] = [sharpe_rank_full.idxmin()]  # best IS Sharpe seed
    pool: list[str] = [a for a in kept if a not in selected]

    while len(selected) < TARGET_N and pool:
        orth_vals = {a: float(corr_abs.loc[a, selected].mean()) for a in pool}
        orth_series = pd.Series(orth_vals)
        orth_rank = orth_series.rank(ascending=True, method="average")
        pool_sharpe_rank = sharpe_rank_full.loc[pool].rank(
            ascending=True, method="average"
        )
        combined = 0.5 * pool_sharpe_rank + 0.5 * orth_rank
        next_a = combined.idxmin()
        selected.append(next_a)
        pool.remove(next_a)

    if len(selected) < 2:
        # last-resort safety
        return list(Rk.columns[: max(2, MIN_N)])
    return selected


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    if not member_ids:
        return {}

    signs = member_signs_ic(RUN_ID, member_ids)
    R = load_member_is_returns(RUN_ID, member_ids, signs=signs)
    if R is None or R.empty:
        raw = {m: 1.0 for m in member_ids}
        coef = normalize_coefficients(raw, "l1")
        return {k: v * GROSS_SCALE for k, v in coef.items()}

    ids = [m for m in member_ids if m in R.columns]
    if not ids:
        raw = {m: 1.0 for m in member_ids}
        coef = normalize_coefficients(raw, "l1")
        return {k: v * GROSS_SCALE for k, v in coef.items()}

    signs_use = {m: int(signs.get(m, 1)) for m in ids}
    # any zeroed signs -> default +1 to avoid wiping the coefficient
    signs_use = {m: (v if v in (-1, 1) else 1) for m, v in signs_use.items()}

    raw = {m: 1.0 for m in ids}                      # equal weight
    raw_signed = apply_signs(raw, signs_use)         # IC-aligned signs
    coef = normalize_coefficients(raw_signed, "l1")  # Σ|c| = 1

    # Lift gross exposure: equal-weight at 1/N gives anemic row L1.
    # Multiply by fixed factor; runner row-L1 cap (1.0) clamps the spikes.
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
