I'll go with an angle not yet in the tried list: **Empirical-Bayes (James-Stein-style) shrinkage of per-alpha Sharpe estimates toward the pool mean as the expected-return signal, combined with a Neumann-series truncated covariance inverse (K=4) for the tangency step**, applied on a concentrated top-6 set that survives a strict per-year IS-Sharpe-positivity gate, a 20% max-drawdown discipline, and a ρ=0.80 correlation dedup.

Mechanism + literature:
- **Empirical-Bayes Sharpe shrinkage** (Efron-Morris 1973; Jorion 1986 for mean-variance applications) treats each alpha's IS-Sharpe as a noisy estimate of a latent true Sharpe drawn from a pool prior. The shrinkage factor `τ²/(τ²+σ²_noise)` is computed from cross-sectional variance vs. per-alpha sampling variance (~1/T). This counters the inflation that pure top-IS-Sharpe selection suffers from — it's a *post-selection* attenuation that should help OS generalization without resorting to the failed "anti-bias" rules.
- **Neumann-series inverse** `Σ⁻¹ ≈ α·Σₖ₌₀..K (I−αΣ)^k` with α = 0.95/λ_max(Σ), K=4. Truncation acts as an implicit eigenvalue regularizer (suppresses the most ill-conditioned modes), avoiding the brittleness of full inversion on a small-T cov matrix. This is the user-requested "Neumann eigenvalue-divergence suppression" angle but combined with a richer signal than raw Sharpe.
- **Year-stability gate** (every IS sub-year Sharpe > 0) + **20% max-DD** + **ρ=0.80 dedup** match the recurring top-of-leaderboard ingredients, with K=4 (distinct from auto_001's K=5 and auto_010's K=6) and a deliberately smaller N=6 (concentration over diversification).
- **Sign alignment via IC** through `member_signs_ic`, with `apply_signs` after tangency to project deployable coefficients back to the underlying alpha frame.
- Coefficient post-scaling targets mean row L1 ≈ 0.7 (`normalize_coefficients` → ×0.7) to stay in the [0.30, 0.90] return-bearing range.

```python COMPOSITE_FILE
"""Empirical-Bayes Sharpe shrinkage (Efron-Morris / James-Stein) + Neumann-series
tangency (K=4) on a concentrated top-6 set with per-year IS-Sharpe-positivity
stability gate, max-DD<20% discipline, and rho=0.80 correlation dedup.
"""
from __future__ import annotations

import argparse
import numpy as np
import pandas as pd
import scipy.linalg as sla

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

COMPOSITE_ID = "auto_039"
COMPOSITION_NOTE = "eb_sharpe_shrink_neumann_k4_top6_yearstable_dd20_dedup080"

RUN_ID = "run_2026_05_c"
N_FINAL = 6
PREFILTER_TOP = 80
MIN_IS_SHARPE = 0.40
DD_MAX = 0.20
RHO_DEDUP = 0.80
NEUMANN_K = 4
SCALE_TARGET = 0.70


def _per_year_min_sharpe(r: pd.Series) -> float:
    r = r.dropna()
    if len(r) < 30:
        return float("nan")
    idx = r.index
    if not isinstance(idx, pd.DatetimeIndex):
        try:
            idx = pd.to_datetime(idx)
            r = pd.Series(r.values, index=idx)
        except Exception:
            return float("nan")
    years = r.index.year
    mins = []
    for y in np.unique(years):
        ry = r[years == y]
        if len(ry) < 10:
            continue
        sd = float(ry.std(ddof=0))
        if sd <= 0:
            return -1e9
        mins.append(float(ry.mean()) / sd * np.sqrt(252.0))
    if not mins:
        return float("nan")
    return float(np.min(mins))


def _max_drawdown(r: pd.Series) -> float:
    r = r.fillna(0.0)
    if len(r) == 0:
        return 0.0
    cum = (1.0 + r).cumprod()
    peak = cum.cummax()
    dd = (cum / peak) - 1.0
    return float(dd.min())


def _annualized_sharpe(r: pd.Series) -> float:
    r = r.dropna()
    if len(r) < 5:
        return 0.0
    sd = float(r.std(ddof=0))
    if sd <= 0:
        return 0.0
    return float(r.mean()) / sd * np.sqrt(252.0)


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    ids = select_is_submittable(RUN_ID)
    if not ids or len(ids) < 5:
        ids = select_all_alphas(RUN_ID)
    if not ids:
        return []

    df = alpha_index.copy()
    if "alpha_id" in df.columns:
        df = df.set_index("alpha_id")
    common = df.index.intersection(pd.Index(ids))
    df = df.loc[common].dropna(subset=["is_sharpe"])
    df = df[df["is_sharpe"] > MIN_IS_SHARPE]

    if len(df) < 5:
        # Last-resort fallback: take whatever top-5 we can find
        df = alpha_index.copy()
        if "alpha_id" in df.columns:
            df = df.set_index("alpha_id")
        df = df.dropna(subset=["is_sharpe"]).sort_values("is_sharpe", ascending=False)
        return df.head(5).index.tolist()

    top_ids = df.sort_values("is_sharpe", ascending=False).head(PREFILTER_TOP).index.tolist()

    signs = member_signs_ic(RUN_ID, top_ids)
    R = load_member_is_returns(RUN_ID, top_ids, signs=signs)

    if R is None or len(R) == 0 or R.shape[1] < 3:
        return df.sort_values("is_sharpe", ascending=False).head(5).index.tolist()

    survivors: list[str] = []
    sharpe_keep: dict[str, float] = {}
    for aid in R.columns:
        r = R[aid].dropna()
        if len(r) < 100:
            continue
        ymin = _per_year_min_sharpe(r)
        if not np.isfinite(ymin) or ymin <= 0.0:
            continue
        mdd = _max_drawdown(r)
        if mdd < -DD_MAX:
            continue
        survivors.append(aid)
        if aid in df.index:
            sharpe_keep[aid] = float(df.loc[aid, "is_sharpe"])
        else:
            sharpe_keep[aid] = _annualized_sharpe(r)

    if len(survivors) < 3:
        survivors = []
        sharpe_keep = {}
        for aid in R.columns:
            r = R[aid].dropna()
            if len(r) < 100:
                continue
            ymin = _per_year_min_sharpe(r)
            if not np.isfinite(ymin) or ymin <= -0.2:
                continue
            survivors.append(aid)
            sharpe_keep[aid] = (
                float(df.loc[aid, "is_sharpe"]) if aid in df.index else _annualized_sharpe(r)
            )

    if len(survivors) < 2:
        return df.sort_values("is_sharpe", ascending=False).head(5).index.tolist()

    R_surv = R[survivors]
    try:
        kept = correlation_dedup(R_surv, threshold=RHO_DEDUP, keep_metric=sharpe_keep)
    except Exception:
        kept = list(survivors)

    if not kept:
        kept = list(survivors)

    kept_sorted = sorted(kept, key=lambda a: sharpe_keep.get(a, 0.0), reverse=True)
    final = kept_sorted[:N_FINAL]

    if len(final) < 2:
        return df.sort_values("is_sharpe", ascending=False).head(5).index.tolist()

    return final


def _neumann_inverse(Sigma: np.ndarray, K: int) -> np.ndarray:
    """Truncated Neumann-series approximation to Sigma^{-1}.
    Sinv = alpha * sum_{k=0..K} (I - alpha*Sigma)^k,  alpha = 0.95 / lam_max(Sigma).
    """
    n = Sigma.shape[0]
    try:
        eigvals = np.linalg.eigvalsh(Sigma)
        lam_max = float(eigvals[-1])
        if not np.isfinite(lam_max) or lam_max <= 0:
            raise ValueError("nonpositive or non-finite lam_max")
        alpha = 0.95 / lam_max
        I = np.eye(n)
        M = I - alpha * Sigma
        Sinv = alpha * I.copy()
        Mk = I.copy()
        for _ in range(K):
            Mk = Mk @ M
            Sinv = Sinv + alpha * Mk
        return Sinv
    except Exception:
        try:
            return sla.pinvh(Sigma)
        except Exception:
            return np.linalg.pinv(Sigma)


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    if not member_ids:
        return {}

    signs = member_signs_ic(RUN_ID, member_ids)
    R = load_member_is_returns(RUN_ID, member_ids, signs=signs)

    if R is None or len(R) == 0 or R.shape[1] < 2:
        eq = 1.0 / max(1, len(member_ids))
        coef = {a: eq for a in member_ids}
        coef = apply_signs(coef, signs)
        coef = normalize_coefficients(coef, "l1")
        return {a: float(v) * SCALE_TARGET for a, v in coef.items()}

    cols = list(R.columns)
    n = len(cols)
    T = len(R)

    mean_r = R.mean()
    std_r = R.std(ddof=0).replace(0, np.nan)
    raw_sharpe = (mean_r / std_r * np.sqrt(252.0)).fillna(0.0)

    # Empirical-Bayes / James-Stein shrinkage of Sharpe toward pool mean.
    # Sharpe-estimator variance ~ (1 + 0.5*SR^2)/T; annualized ~ 252/T  as a coarse upper bound.
    pool_mean = float(raw_sharpe.mean())
    pool_var = float(raw_sharpe.var(ddof=0)) if n > 1 else 0.0
    noise_var = 252.0 / max(T, 1)
    if pool_var > 0:
        shrink = noise_var / (noise_var + pool_var)
        shrink = float(np.clip(shrink, 0.0, 1.0))
    else:
        shrink = 0.5
    sharpe_eb = (1.0 - shrink) * raw_sharpe + shrink * pool_mean
    sharpe_eb = sharpe_eb.clip(lower=0.0)  # deploy long on sign-aligned axis only

    # Covariance with light Tikhonov-style diagonal jitter for stability.
    Rv = R[cols].fillna(0.0).values
    if Rv.shape[0] < 2:
        Sigma = np.eye(n)
    else:
        Sigma = np.cov(Rv, rowvar=False)
    if Sigma.ndim == 0:
        Sigma = np.array([[float(Sigma)]])
    diag_mean = float(np.mean(np.diag(Sigma))) if Sigma.size else 1.0
    Sigma = Sigma + np.eye(Sigma.shape[0]) * max(1e-10, 1e-3 * diag_mean)

    Sinv = _neumann_inverse(Sigma, NEUMANN_K)

    mu = sharpe_eb.reindex(cols).fillna(0.0).values
    raw_w = Sinv @ mu
    raw_w = np.where(np.isfinite(raw_w), raw_w, 0.0)
    raw_w = np.where(raw_w < 0.0, 0.0, raw_w)

    if raw_w.sum() <= 0:
        # Fall back to inverse-variance long-only weighting on the aligned set.
        vol = np.sqrt(np.maximum(np.diag(Sigma), 1e-12))
        raw_w = 1.0 / vol

    coef = {a: float(w) for a, w in zip(cols, raw_w)}
    for a in member_ids:
        if a not in coef:
            coef[a] = 0.0

    coef = apply_signs(coef, signs)
    coef = normalize_coefficients(coef, "l1")
    coef = {a: float(v) * SCALE_TARGET for a, v in coef.items()}
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
