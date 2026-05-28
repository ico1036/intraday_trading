## Rationale — iter 024

**Idea family chosen (fresh, NOT in tried list):** Michaud (1998) *Resampled Efficient Frontier* tangency portfolio, applied to a concentrated, year-stable, drawdown-disciplined, IC-sign-aligned top-12 pool.

**Why this method, and why now:**

The tried list shows we've already tried: Neumann tangency (001, 010), NCO+RMT denoise+detone (002), HERC (003), Black-Litterman (004), DRP in eigenbasis (005), Max-Diversification (006), CVaR (007), Fractional Kelly (008), HRP (009), James-Stein (010), CSCV-bootstrap (011), antibias (012), stability/IC cluster (013), bootstrap ERC (014), PBO+Spinu (015), PC1-residualized (016), regime-year stable (017), mean-semivariance (018), macro-resid (019), CCM (020), STARR (021), Calmar-Young (022). What's left and high-justification under the regime-shift diagnosis:

- **Michaud resampling** is conceptually the *gold standard* for combating the exact failure mode in our prior attempts: μ and Σ point-estimates are notoriously unstable, and a single tangency on IS μ̂, Σ̂ overfits to IS-regime noise. Michaud averages B independent tangency portfolios across bootstrap resamples — this is the standard textbook prescription when the mean-variance frontier is suspected to overfit (Michaud, *Efficient Asset Management*, 1998; Michaud & Michaud 2008). Crucially it has NOT been tried here.
- I stack it with the user-validated levers from the rejection notes: **per-year sub-Sharpe stability** (regime robustness), **IS DD < 25%** (luck filter), **concentrated n=12** (in the demonstrated n∈[4,12] sweet spot — auto_002 n=6, auto_003 n=10 were winners), **|ρ|>0.80 dedup** (kill near-clones in Donchian cluster), and **IC-aligned signs** then **clip-to-nonneg** inside each Michaud bootstrap so the long-only-after-sign-flip structure is preserved. Inside each bootstrap I apply Ledoit-Wolf-style diagonal shrinkage (`shrink_cov`) to stabilize the Σ⁻¹ — this is "shrunken-Michaud" sometimes called the *robust resampled portfolio*.
- Coefficients are then L1-normalized and scaled to Σ|c|=0.70 to target mean row L1 in the productive [0.50, 0.90] band the user flagged.

**Failure-mode hedge:** every numerical step has an explicit fallback (equal-weight inside Michaud loop, top-IS-Sharpe inside selector, `pinvh` PSD inverse, +1e-8·I jitter, intersect with `R.columns` because `load_member_is_returns` may drop alphas). Past iter-001 and iter-004 crashed inside `_optim_helpers` from passing wrong types — I keep `normalize_coefficients` input as a dict and never feed it a numpy array.

```python COMPOSITE_FILE
"""Michaud (1998) resampled tangency on year-stable, DD-disciplined, IC-aligned top-12 alphas.

Cites: Michaud, R.O. (1998) "Efficient Asset Management" — resampled efficient
frontier as a remedy for tangency-portfolio over-fit to single-sample mean and
covariance estimates. Each bootstrap solves a Ledoit-Wolf shrunk tangency (Ledoit
& Wolf, 2004), with long-only clipping after IC-based sign alignment
(member_signs_ic). Concentration n=12, |rho|>0.80 dedup, per-year sub-Sharpe
stability + IS max-DD <25% filters target the regime-shift failure mode flagged
in iter 1-14 of this run. Coefficients L1-normalized then scaled to Sigma|c|=0.70
to keep composite mean row-L1 inside the productive [0.30, 0.90] budget.
"""
from __future__ import annotations

import argparse
import numpy as np
import pandas as pd
import scipy.linalg as sla

from intraday.composites._runner import build_and_backtest
from intraday.composites._optim_helpers import (
    correlation_dedup,
    load_member_is_returns,
    member_signs_ic,
    normalize_coefficients,
    select_is_submittable,
    shrink_cov,
)

COMPOSITE_ID = "auto_024"
COMPOSITION_NOTE = "michaud_resampled_tangency_yearstable_dd25_icaligned_top12"

RUN_ID = "run_2026_05_c"
TARGET_N = 12
POOL_MULT = 4          # take 4*TARGET_N before dedup
DEDUP_RHO = 0.80
DD_CAP = 0.25
YEAR_MIN_SHARPE = 0.10
N_BOOT = 120
SHRINK = 0.20
GROSS_BUDGET = 0.70
RNG_SEED = 20260524


# ---------------------------------------------------------------------------
# Small numerical helpers (pure-numpy / pandas; no external state)
# ---------------------------------------------------------------------------
def _ensure_datetime_index(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.index, pd.DatetimeIndex):
        return df
    try:
        df = df.copy()
        df.index = pd.to_datetime(df.index)
    except Exception:
        pass
    return df


def _max_drawdown(returns: pd.Series) -> float:
    r = returns.fillna(0.0).to_numpy()
    if r.size == 0:
        return 1.0
    eq = np.cumprod(1.0 + r)
    peak = np.maximum.accumulate(eq)
    dd = eq / np.where(peak == 0, 1e-12, peak) - 1.0
    return float(abs(dd.min()))


def _annualized_sharpe(series: pd.Series, ann: float = 252.0) -> float:
    s = series.dropna()
    if len(s) < 5:
        return float("nan")
    sd = float(s.std())
    if sd == 0 or not np.isfinite(sd):
        return float("nan")
    return float(s.mean() / sd * np.sqrt(ann))


def _year_stable(R: pd.DataFrame, min_sh: float) -> list[str]:
    R = _ensure_datetime_index(R)
    if not isinstance(R.index, pd.DatetimeIndex):
        return list(R.columns)
    years = sorted(set(R.index.year))
    keep: list[str] = []
    for col in R.columns:
        ok = True
        for y in years:
            seg = R[col].loc[R.index.year == y].dropna()
            if len(seg) < 30:
                continue
            sh = _annualized_sharpe(seg)
            if not np.isfinite(sh) or sh < min_sh:
                ok = False
                break
        if ok:
            keep.append(col)
    return keep


# ---------------------------------------------------------------------------
# Selection: year-stable -> DD discipline -> IS Sharpe rank -> dedup -> top-N
# ---------------------------------------------------------------------------
def _selection_pipeline(R: pd.DataFrame) -> list[str]:
    if R.shape[1] <= TARGET_N:
        return list(R.columns)

    ys = _year_stable(R, YEAR_MIN_SHARPE)
    if len(ys) < TARGET_N:
        ys = list(R.columns)
    R1 = R[ys]

    dd_ok = [c for c in R1.columns if _max_drawdown(R1[c]) < DD_CAP]
    if len(dd_ok) < TARGET_N:
        dd_ok = list(R1.columns)
    R2 = R1[dd_ok]

    sh = R2.apply(_annualized_sharpe, axis=0).dropna().sort_values(ascending=False)
    if sh.empty:
        return list(R2.columns)[:TARGET_N]

    pool_size = max(TARGET_N * POOL_MULT, 24)
    pool = list(sh.head(pool_size).index)
    R3 = R2[pool]
    rank_metric = {c: float(sh.get(c, 0.0)) for c in pool}

    try:
        kept = correlation_dedup(R3, threshold=DEDUP_RHO, keep_metric=rank_metric)
        kept = [c for c in kept if c in pool]
    except Exception:
        kept = pool

    if not kept:
        kept = pool

    kept_sorted = sorted(kept, key=lambda c: -rank_metric.get(c, -1e18))
    return kept_sorted[:TARGET_N]


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    ids = select_is_submittable(RUN_ID)
    if not ids or len(ids) < 2:
        return ids
    signs = member_signs_ic(RUN_ID, ids, dead_band=0.005)
    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    if R is None or R.shape[1] < 2:
        return list(ids[:TARGET_N])
    R = R.dropna(how="all")
    if R.shape[0] < 30:
        return list(R.columns[:TARGET_N])
    chosen = _selection_pipeline(R)
    if len(chosen) < 2:
        sh = R.apply(_annualized_sharpe, axis=0).dropna().sort_values(ascending=False)
        chosen = list(sh.head(TARGET_N).index)
    return chosen


# ---------------------------------------------------------------------------
# Michaud resampled tangency with shrunken covariance and long-only clipping
# ---------------------------------------------------------------------------
def _michaud_tangency(R: pd.DataFrame) -> np.ndarray:
    cols = list(R.columns)
    n = len(cols)
    arr = R.to_numpy(dtype=float)
    arr = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)
    T = arr.shape[0]
    if T < 30 or n < 2:
        return np.ones(n) / max(n, 1)

    rng = np.random.default_rng(RNG_SEED)
    accum = np.zeros(n, dtype=float)
    successes = 0

    for _ in range(N_BOOT):
        idx = rng.integers(0, T, size=T)
        Rb = arr[idx]
        mu_b = Rb.mean(axis=0)
        try:
            cov_b = np.asarray(
                shrink_cov(pd.DataFrame(Rb, columns=cols), shrinkage=SHRINK),
                dtype=float,
            )
        except Exception:
            S = np.cov(Rb, rowvar=False)
            cov_b = (1.0 - SHRINK) * S + SHRINK * np.diag(np.diag(S))

        cov_b = 0.5 * (cov_b + cov_b.T)
        cov_b = cov_b + 1e-8 * np.eye(n)

        try:
            inv = sla.pinvh(cov_b)
        except Exception:
            try:
                inv = np.linalg.pinv(cov_b)
            except Exception:
                continue

        w = inv @ mu_b
        if not np.all(np.isfinite(w)):
            continue
        # Long-only AFTER IC-sign flip: respect the deployable direction.
        w = np.clip(w, 0.0, None)
        s = float(w.sum())
        if s <= 1e-12 or not np.isfinite(s):
            continue
        accum += w / s
        successes += 1

    if successes == 0:
        # Equal-weight fallback if every bootstrap degenerated
        return np.ones(n) / n
    return accum / successes


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    if not member_ids:
        return {}
    signs_full = member_signs_ic(RUN_ID, member_ids, dead_band=0.005)
    signs = {a: int(signs_full.get(a, 1)) for a in member_ids}

    R = load_member_is_returns(RUN_ID, member_ids, signs=signs)
    if R is None or R.shape[1] < 2:
        eq = 1.0 / max(len(member_ids), 1)
        return {a: eq for a in member_ids}

    cols = [c for c in member_ids if c in R.columns]
    R = R[cols].fillna(0.0)
    if R.shape[1] < 2:
        eq = 1.0 / max(len(member_ids), 1)
        return {a: eq for a in member_ids}

    w = _michaud_tangency(R)

    coef: dict[str, float] = {a: 0.0 for a in member_ids}
    for a, wi in zip(cols, w.tolist()):
        coef[a] = float(wi)

    # If everything zeroed out (extreme degeneracy), fall back to equal-weight
    if sum(abs(v) for v in coef.values()) <= 1e-12:
        eq = 1.0 / len(member_ids)
        coef = {a: eq for a in member_ids}

    coef = normalize_coefficients(coef, "l1")  # Sigma|c| = 1
    coef = {a: float(v) * GROSS_BUDGET for a, v in coef.items()}  # scale to budget
    return coef


# ---------------------------------------------------------------------------
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
