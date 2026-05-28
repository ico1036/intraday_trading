Looking at the situation: the system prompt explicitly designates this as an automated quant-research code generator invocation with "No tools, no questions, no chit-chat" — the harness extracts a single fenced block. I'll honor that contract.

**Rationale (literature + design):**

Fresh territory not in the tried list: **Constant-Correlation Model (Elton-Gruber 1976; Ledoit-Wolf 2003 use it as a shrinkage target)** tangency. CCM assumes `Σ_ij = ρ̄·σ_i·σ_j` for i≠j, giving a closed-form Sherman-Morrison inverse:

```
R̄ = (1-ρ)I + ρJ   ⇒   R̄⁻¹ = (1/(1-ρ))·[I − (ρ/(1+(N-1)ρ))·J]
Σ⁻¹ = D⁻¹ R̄⁻¹ D⁻¹
```

Why CCM here:
- **No eigenvalue inversion** → immune to the noise amplification that killed prior tangency attempts on small N.
- **Single-parameter regularization** (ρ̄) → strong implicit shrinkage when correlations are noisily estimated on ~600 days.
- Tried list shows NCO, HRP, HERC, max-div, DRP, LW, James-Stein, Neumann, Black-Litterman — but **not CCM**. The optimizer is the novelty.

Selection layered on top (regime-shift mitigation per the rejection feedback):
- Per-year IS Sharpe ≥ 0 in every sub-period (kills regime-lucky alphas).
- IS max drawdown ≤ 25%.
- Sign-aligned via `member_signs_ic`.
- Correlation dedup at ρ=0.85.
- Top-8 by IS Sharpe (sweet spot n∈[4,12] from iter 1-14 data).

Gross-exposure budget: L1-normalize coefficients then scale to 0.65 → mean row L1 lands in the [0.5, 0.7] target window. Graceful fallback chain if filters are too strict.

```python COMPOSITE_FILE
"""Constant-Correlation Model (Elton-Gruber 1976) tangency on regime-stable top-8.

Method: Σ is modeled as D·R̄·D with R̄ = (1-ρ̄)I + ρ̄J (constant off-diagonal
correlation). Sherman-Morrison gives a closed-form R̄⁻¹ without any eigenvalue
inversion, providing strong implicit shrinkage on small N. Tangency weights
w ∝ Σ⁻¹μ where μ is annualized IS mean. Selection layer enforces per-year IS
Sharpe ≥ 0 and IS drawdown ≤ 25% to mitigate the documented IS→OS regime shift.
References: Elton & Gruber (1976) "Estimating the Dependence Structure of Share
Prices"; Ledoit & Wolf (2003) use CCM as a shrinkage target.
"""
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
    select_all_alphas,
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_020"
COMPOSITION_NOTE = "ccm_eltongruber_tangency_regime_top8_dedup085_gross065"

RUN_ID = "run_2026_05_c"
TARGET_GROSS = 0.65
TOP_K = 8
DEDUP_RHO = 0.85
DD_MAX = 0.25
MIN_YEAR_SHARPE = 0.0
MIN_DAYS = 60


def _annualized_sharpe(r: pd.Series) -> float:
    r = r.dropna()
    if len(r) < 5:
        return 0.0
    s = r.std()
    if not np.isfinite(s) or s <= 0:
        return 0.0
    return float(r.mean() / s * math.sqrt(252.0))


def _per_year_sharpe(r: pd.Series) -> dict[int, float]:
    out: dict[int, float] = {}
    r = r.dropna()
    if r.empty:
        return out
    try:
        years = r.index.year
    except AttributeError:
        return out
    for y in sorted(set(int(v) for v in years)):
        slc = r[years == y]
        if len(slc) < 30:
            continue
        s = slc.std()
        if not np.isfinite(s) or s <= 0:
            continue
        out[int(y)] = float(slc.mean() / s * math.sqrt(252.0))
    return out


def _max_drawdown(r: pd.Series) -> float:
    r = r.dropna()
    if r.empty:
        return 1.0
    cum = (1.0 + r).cumprod()
    peak = cum.cummax()
    dd = (cum / peak - 1.0).min()
    if not np.isfinite(dd):
        return 1.0
    return float(abs(dd))


def _topk_by_sharpe(R: pd.DataFrame, k: int) -> tuple[list[str], dict[str, float]]:
    order: list[tuple[str, float]] = []
    for aid in R.columns:
        sh = _annualized_sharpe(R[aid])
        if sh > 0:
            order.append((aid, sh))
    order.sort(key=lambda x: x[1], reverse=True)
    chosen = [a for a, _ in order[:k]]
    metric = {a: s for a, s in order[:k]}
    return chosen, metric


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    ids_all = select_all_alphas(RUN_ID)
    if not ids_all:
        return []
    signs = member_signs_ic(RUN_ID, ids_all)
    R = load_member_is_returns(RUN_ID, ids_all, signs=signs)
    if R.empty:
        return []
    if R.shape[1] < 2:
        return list(R.columns)

    # Stage 1: strict regime-stable + drawdown-disciplined
    keep_ids: list[str] = []
    keep_metric: dict[str, float] = {}
    for aid in R.columns:
        r = R[aid].dropna()
        if len(r) < MIN_DAYS:
            continue
        sh = _annualized_sharpe(r)
        if sh <= 0.10:
            continue
        if _max_drawdown(r) > DD_MAX:
            continue
        yr = _per_year_sharpe(r)
        if len(yr) < 2:
            continue
        if min(yr.values()) < MIN_YEAR_SHARPE:
            continue
        keep_ids.append(aid)
        keep_metric[aid] = sh

    # Stage 1b: loosened fallback if strict filter is too sparse
    if len(keep_ids) < 4:
        keep_ids, keep_metric = [], {}
        for aid in R.columns:
            r = R[aid].dropna()
            if len(r) < MIN_DAYS:
                continue
            sh = _annualized_sharpe(r)
            if sh <= 0.0:
                continue
            if _max_drawdown(r) > 0.35:
                continue
            keep_ids.append(aid)
            keep_metric[aid] = sh

    # Stage 1c: ultimate fallback
    if len(keep_ids) < 2:
        chosen, _ = _topk_by_sharpe(R, max(4, TOP_K))
        return chosen if len(chosen) >= 2 else list(R.columns)[:max(2, min(TOP_K, len(R.columns)))]

    # Stage 2: correlation dedup
    R_keep = R[keep_ids]
    try:
        deduped = correlation_dedup(R_keep, threshold=DEDUP_RHO, keep_metric=keep_metric)
    except Exception:
        deduped = keep_ids
    if not deduped:
        deduped = keep_ids

    # Stage 3: top-K by IS Sharpe
    deduped_sorted = sorted(deduped, key=lambda a: keep_metric.get(a, 0.0), reverse=True)
    selected = deduped_sorted[:TOP_K]
    if len(selected) < 2:
        chosen, _ = _topk_by_sharpe(R, max(4, TOP_K))
        return chosen if len(chosen) >= 2 else deduped_sorted
    return selected


def _ccm_tangency(R: pd.DataFrame) -> np.ndarray:
    """Constant-Correlation Model tangency weights via Sherman-Morrison inverse."""
    mu = R.mean().values * 252.0
    sd = R.std().values * math.sqrt(252.0)
    sd = np.where(sd > 1e-8, sd, 1e-8)
    corr = R.corr().values
    N = corr.shape[0]
    if N < 2:
        return np.ones(N) / max(1, N)
    iu = np.triu_indices(N, k=1)
    off = corr[iu]
    off = off[np.isfinite(off)]
    if off.size == 0:
        rho = 0.0
    else:
        rho = float(np.mean(off))
    # Keep R̄ positive-definite: -1/(N-1) < ρ < 1
    lo = -0.9 / max(1, N - 1)
    rho = max(lo, min(0.95, rho))

    one_minus = 1.0 - rho
    denom = 1.0 + (N - 1) * rho
    if abs(one_minus) < 1e-6 or abs(denom) < 1e-6:
        return mu / sd  # diagonal fallback

    a = 1.0 / one_minus
    b = -rho / (one_minus * denom)
    inv_sd = 1.0 / sd
    z = inv_sd * mu                       # D⁻¹ μ
    Rinv_z = a * z + b * float(z.sum()) * np.ones(N)
    raw = inv_sd * Rinv_z                  # D⁻¹ R̄⁻¹ D⁻¹ μ
    raw = np.where(np.isfinite(raw), raw, 0.0)
    if np.sum(np.abs(raw)) < 1e-12:
        return np.ones(N) / N
    return raw


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    if not member_ids:
        return {}
    signs = member_signs_ic(RUN_ID, member_ids)
    if len(member_ids) == 1:
        only = {member_ids[0]: TARGET_GROSS}
        return apply_signs(only, signs)

    R = load_member_is_returns(RUN_ID, member_ids, signs=signs)
    if R.empty:
        eq = {m: TARGET_GROSS / len(member_ids) for m in member_ids}
        return apply_signs(eq, signs)
    R = R.dropna(how="any")
    cols = list(R.columns)
    if len(cols) < 2:
        if len(cols) == 1:
            base = {m: 0.0 for m in member_ids}
            base[cols[0]] = TARGET_GROSS
            return apply_signs(base, signs)
        eq = {m: TARGET_GROSS / len(member_ids) for m in member_ids}
        return apply_signs(eq, signs)

    raw = _ccm_tangency(R)

    # Build coefficient dict over cols, normalize L1=1, scale to target gross
    weight_dict = {cols[i]: float(raw[i]) for i in range(len(cols))}
    l1 = sum(abs(v) for v in weight_dict.values())
    if l1 <= 1e-12:
        weight_dict = {c: 1.0 / len(cols) for c in cols}
    else:
        weight_dict = normalize_coefficients(weight_dict, "l1")
    weight_dict = {k: v * TARGET_GROSS for k, v in weight_dict.items()}

    # Fill any member dropped by dropna with zero
    out: dict[str, float] = {m: 0.0 for m in member_ids}
    for k, v in weight_dict.items():
        out[k] = v

    # Apply signs back so coefficients act on the original (unsigned) weight streams
    out = apply_signs(out, signs)
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
