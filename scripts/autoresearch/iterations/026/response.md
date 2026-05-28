**Reasoning**

The user explicitly flagged regime shift (2022-2024 IS → 2024-2026 OS) as the dominant failure mode, with concentrated n ∈ [4, 12] being the empirical sweet spot. Prior attempts touched Neumann, NCO, HRP, HERC, BL, DRP, MaxDiv, MeanCVaR, Kelly, JS, CSCV, ERC, semivariance, Calmar, STARR — but **no attempt has used Michaud's resampled efficient frontier**, which is a textbook remedy for plug-in estimation error in tangency.

**Mechanism:** Michaud & Michaud (2008) showed that bootstrap-averaging the tangency portfolio across resampled return histories reduces the curse of estimation error in μ̂ and Σ̂. Each bootstrap draws a (block-resampled) IS history, computes a Ledoit-Wolf-shrunk tangency, and the final weight is the average. This is mathematically distinct from a single plug-in tangency: it shrinks coefficients toward 1/n as μ-uncertainty grows, but preserves directional structure where the signal is genuine. Combined with **block-bootstrap** (serial dependence) and a **Michaud-style 70/30 RE blend with the plug-in** (Bayes-style anchor), this is a fresh angle.

**Selection layer (regime-aware, per prompt diagnosis):**
- Sign-flip every member via IC (`member_signs_ic`) so the IS returns matrix has positive expected return columns.
- Per-year minimum Sharpe > 0 across each of the 2022/2023/2024 sub-periods — kills lucky-single-regime alphas.
- Max cumulative drawdown < 30% — kills "all-on-one-event" winners.
- Correlation dedup at |ρ| > 0.80 on the survivors.
- Concentrate to the **top 8** by per-year-min Sharpe (sweet spot is n=6-10 per harness data).

**Gross exposure budget:** L1-normalize coefficients then scale by 0.75 to land mean row L1 inside [0.5, 0.9].

**Citations in docstring:** Michaud (1998); Michaud & Michaud (2008); Ledoit & Wolf (2003).

```python COMPOSITE_FILE
"""Michaud (1998, 2008) resampled efficient tangency with Ledoit-Wolf shrinkage and regime-stable per-year-min-Sharpe concentrated selection (n=8)."""
from __future__ import annotations
import argparse
import math
import numpy as np
import pandas as pd
import scipy.linalg as sla

from intraday.composites._runner import build_and_backtest
from intraday.composites._optim_helpers import (
    correlation_dedup,
    member_signs_ic,
    apply_signs,
    shrink_cov,
    select_is_submittable,
    select_all_alphas,
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_026"
COMPOSITION_NOTE = "michaud_resampled_tangency_regime_stable_top8_lw"

RUN_ID = "run_2026_05_c"


def _per_year_min_sharpe(r: pd.Series) -> float:
    """Worst-year annualized Sharpe across distinct calendar years in IS index."""
    if r is None or len(r) == 0:
        return -np.inf
    try:
        idx = pd.to_datetime(r.index)
    except Exception:
        return -np.inf
    yrs = idx.year.values
    mins = np.inf
    seen = 0
    for y in np.unique(yrs):
        rr = r.values[yrs == y]
        rr = rr[np.isfinite(rr)]
        if len(rr) < 30:
            continue
        sd = float(np.std(rr, ddof=1))
        if not np.isfinite(sd) or sd <= 0:
            return -np.inf
        s = (float(np.mean(rr)) / sd) * math.sqrt(252.0)
        if s < mins:
            mins = s
        seen += 1
    if seen == 0:
        return -np.inf
    return float(mins)


def _max_drawdown(r: pd.Series) -> float:
    eq = r.fillna(0.0).cumsum()
    return float(-(eq - eq.cummax()).min())


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    try:
        pool = list(select_is_submittable(RUN_ID))
    except Exception:
        pool = []
    if len(pool) < 5:
        try:
            pool = list(select_all_alphas(RUN_ID))
        except Exception:
            pool = list(alpha_index["alpha_id"].astype(str))

    if len(pool) < 4:
        idx = alpha_index.sort_values("is_sharpe", ascending=False)
        return idx["alpha_id"].astype(str).head(8).tolist()

    try:
        signs = member_signs_ic(RUN_ID, pool)
        R = load_member_is_returns(RUN_ID, pool, signs=signs)
    except Exception:
        idx = alpha_index.sort_values("is_sharpe", ascending=False)
        return idx["alpha_id"].astype(str).head(8).tolist()

    R = R.dropna(axis=1, how="all").dropna(axis=0, how="all")
    if R.shape[1] < 4:
        idx = alpha_index.sort_values("is_sharpe", ascending=False)
        return idx["alpha_id"].astype(str).head(8).tolist()

    py: dict[str, float] = {}
    dd: dict[str, float] = {}
    for c in R.columns:
        py[c] = _per_year_min_sharpe(R[c])
        dd[c] = _max_drawdown(R[c])

    # Tier 1: positive Sharpe every year AND drawdown disciplined
    keep = [c for c in R.columns if py[c] > 0.0 and dd[c] < 0.30]

    # Tier 2 relax if too few survive
    if len(keep) < 6:
        keep = [c for c in R.columns if py[c] > -0.1 and dd[c] < 0.45]
    if len(keep) < 6:
        keep = sorted(R.columns, key=lambda c: py.get(c, -np.inf), reverse=True)[:30]

    sub = R[keep]
    try:
        kept = correlation_dedup(sub, threshold=0.80, keep_metric=py)
    except Exception:
        kept = list(keep)

    kept = [c for c in kept if c in py]
    kept = sorted(kept, key=lambda c: py.get(c, -np.inf), reverse=True)[:8]

    if len(kept) < 3:
        idx = alpha_index.sort_values("is_sharpe", ascending=False)
        return idx["alpha_id"].astype(str).head(8).tolist()
    return list(kept)


def _tangency_direction(mu: np.ndarray, Sigma: np.ndarray) -> np.ndarray:
    """L1-normalized Σ⁻¹μ direction via Hermitian pseudoinverse."""
    n = mu.shape[0]
    try:
        S = Sigma + 1e-6 * np.eye(n)
        Sinv = sla.pinvh(S)
        w = Sinv @ mu
    except Exception:
        w = mu.copy()
    w = np.where(np.isfinite(w), w, 0.0)
    s = float(np.sum(np.abs(w)))
    if s > 0:
        return w / s
    return np.ones(n) / max(1, n)


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    try:
        signs = member_signs_ic(RUN_ID, member_ids)
    except Exception:
        signs = {a: 1 for a in member_ids}

    try:
        R = load_member_is_returns(RUN_ID, member_ids, signs=signs)
    except Exception:
        R = pd.DataFrame()

    R = R.dropna(axis=1, how="all") if not R.empty else R
    avail = list(R.columns) if not R.empty else []
    if len(avail) < 2:
        eq = {a: 1.0 / max(1, len(member_ids)) for a in member_ids}
        c = normalize_coefficients(eq, "l1")
        c = {k: float(v) * 0.6 for k, v in c.items()}
        return apply_signs(c, signs)

    arr = R.fillna(0.0).values  # T x n
    T, n = arr.shape

    # Block bootstrap parameters (preserve serial dependence)
    block = max(5, T // 50)
    rng = np.random.default_rng(20260526)
    B = 120

    W = np.zeros((B, n))
    n_blocks_needed = max(1, T // block + 1)
    for b in range(B):
        starts = rng.integers(0, max(1, T - block + 1), size=n_blocks_needed)
        chunks = [arr[s:s + block] for s in starts]
        boot = np.vstack(chunks)
        if boot.shape[0] > T:
            boot = boot[:T]
        if boot.shape[0] < 10:
            boot = arr
        mu_b = boot.mean(axis=0)
        try:
            Sigma_b = shrink_cov(pd.DataFrame(boot, columns=avail), shrinkage=0.30)
        except Exception:
            Sigma_b = np.cov(boot, rowvar=False) + 0.30 * np.diag(np.var(boot, axis=0))
        W[b] = _tangency_direction(mu_b, Sigma_b)

    w_avg = W.mean(axis=0)

    # Plug-in baseline anchors the Michaud RE estimate (70% bootstrap, 30% plug-in)
    mu_full = arr.mean(axis=0)
    try:
        Sigma_full = shrink_cov(R.fillna(0.0), shrinkage=0.20)
    except Exception:
        Sigma_full = np.cov(arr, rowvar=False) + 0.20 * np.diag(np.var(arr, axis=0))
    w_plug = _tangency_direction(mu_full, Sigma_full)

    w_final = 0.70 * w_avg + 0.30 * w_plug
    w_final = np.where(np.isfinite(w_final), w_final, 0.0)
    if not np.any(w_final):
        w_final = np.ones(n) / n

    coef = {a: 0.0 for a in member_ids}
    for a, v in zip(avail, w_final.tolist()):
        coef[a] = float(v)

    # L1-normalize to unit aggregate, then scale to target gross-exposure budget
    c = normalize_coefficients(coef, "l1")
    target_gross = 0.75
    c = {k: float(v) * target_gross for k, v in c.items()}

    # Map sign-aligned space back to raw deployable weights
    c = apply_signs(c, signs)
    return c


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
