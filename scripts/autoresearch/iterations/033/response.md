Looking at this iteration's context:

- 32 prior attempts cover: Neumann, NCO+MP+detone, HERC, BL, DRP, MaxDiv, CVaR, Kelly, HRP, James-Stein, CSCV, anti-bias, IR-stability, ERC, PBO, PC1-residual, regime-year (auto_017), mean-semivariance, EG-macro-hedge, CCM, STARR, Calmar...
- User hint: high-return / high-risk + Neumann eigenvalue-divergence suppression
- Critical diagnosis: regime shift IS→OS is dominant; n=6-10 sweet spot; mean row-L1 ∈ [0.5, 0.9]; concentrated top picks beat anti-bias

**Fresh idea — Deflated/Probabilistic Sharpe Ratio (Bailey & López de Prado 2012/2014) for selection, combined with Neumann-truncated tangency:**

- PSR penalizes raw Sharpe by negative skew and excess kurtosis: `Ẑ = (SR − SR*)·√(T−1) / √(1 − γ₃·SR + ((γ₄−1)/4)·SR²)`. This is exactly the "lucky-tails get punished" gate that anti-bias filters failed to enforce. Not yet cited in prior 32 iters.
- Layer on year-stable + DD ≤ 25% as regime gates (orthogonal to PSR's higher-moment screen — PSR catches tail-fragility, year-stability catches regime-fragility).
- Combine via Neumann-series Σ⁻¹·μ truncation (K=4) — honors user's hint, suppresses high-noise eigenmodes via `λ < 2/α` cutoff without explicit inversion. Different from LW shrinkage (auto_004/auto_006/auto_010) and MP clipping (auto_002).
- Target n=8, dedup ρ=0.85, gross 0.70 mean-row-L1.

```python COMPOSITE_FILE
"""PSR/DSR-screened top-k with year-stable + DD discipline and Neumann-series tangency.

Cites: Bailey & Lopez de Prado (2012, 2014) -- the Probabilistic / Deflated Sharpe
Ratio. PSR(SR*) = Phi((SR - SR*)*sqrt(T-1) / sqrt(1 - g3*SR + (g4-1)/4 * SR^2)),
so SR is deflated for negative skew and excess kurtosis. We use the Z-score itself
(monotone in PSR) to rank. The user's Neumann hint is implemented as a truncated
operator inverse Sigma^-1 ~ alpha * sum_{k=0..K} (I - alpha*Sigma)^k with alpha
chosen from a power-iteration estimate of lambda_max(Sigma); K=4 keeps the four
dominant inverse-eigenvalue corrections while suppressing high-noise modes that
blow up under naive inversion. Concentrated n=8 keeps mean row L1 in [0.5, 0.9]."""
from __future__ import annotations

import argparse
import numpy as np
import pandas as pd

from intraday.composites._runner import build_and_backtest
from intraday.composites._optim_helpers import (
    correlation_dedup,
    member_signs_ic,
    apply_signs,
    select_is_submittable,
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_033"
COMPOSITION_NOTE = "psr_dsr_yearstable_dd25_neumann_k4_tangency_top8"
RUN_ID = "run_2026_05_c"

TARGET_N = 8
POOL_MULT = 4
DEDUP_RHO = 0.85
MAX_DD = 0.25
MIN_YEARS = 2
NEUMANN_K = 4
DIAG_SHRINK = 0.10
GROSS_TARGET = 0.70


def _psr_z(r: pd.Series) -> float:
    x = r.dropna().to_numpy(dtype=float)
    if x.size < 30:
        return -np.inf
    mu = float(x.mean())
    sd = float(x.std(ddof=1))
    if not np.isfinite(sd) or sd <= 1e-12:
        return -np.inf
    sr = mu / sd
    d = x - mu
    m3 = float((d ** 3).mean())
    m4 = float((d ** 4).mean())
    g3 = m3 / (sd ** 3 + 1e-12)
    g4 = m4 / (sd ** 4 + 1e-12)
    denom = 1.0 - g3 * sr + ((g4 - 1.0) / 4.0) * sr * sr
    if not np.isfinite(denom) or denom <= 1e-9:
        return -np.inf
    return float(sr * np.sqrt(max(1, x.size - 1)) / np.sqrt(denom))


def _year_stable(r: pd.Series) -> bool:
    s = r.dropna()
    if s.empty:
        return False
    idx = s.index
    if not isinstance(idx, pd.DatetimeIndex):
        try:
            idx = pd.to_datetime(idx)
            s = pd.Series(s.to_numpy(), index=idx)
        except Exception:
            return False
    n_years = 0
    for _, chunk in s.groupby(s.index.year):
        if chunk.size < 20:
            continue
        sd = float(chunk.std(ddof=1))
        if not np.isfinite(sd) or sd <= 0:
            return False
        if float(chunk.mean()) / sd <= 0.0:
            return False
        n_years += 1
    return n_years >= MIN_YEARS


def _max_drawdown(r: pd.Series) -> float:
    s = r.dropna()
    if s.empty:
        return 1.0
    eq = (1.0 + s.clip(lower=-0.95)).cumprod()
    peak = eq.cummax()
    dd = eq / peak - 1.0
    return float(-dd.min())


def _neumann_inverse(Sigma: np.ndarray, k: int) -> np.ndarray:
    n = Sigma.shape[0]
    tr = float(np.trace(Sigma)) / max(1, n)
    if not np.isfinite(tr) or tr <= 0:
        tr = 1.0
    S = (1.0 - DIAG_SHRINK) * Sigma + DIAG_SHRINK * tr * np.eye(n)
    v = np.ones(n) / np.sqrt(n)
    lam = 1.0
    for _ in range(60):
        v = S @ v
        nv = float(np.linalg.norm(v))
        if nv <= 1e-12:
            break
        v = v / nv
        lam = float(v @ S @ v)
    if not np.isfinite(lam) or lam <= 0:
        lam = 1.0
    alpha = 1.0 / (lam * 1.05)
    Q = np.eye(n) - alpha * S
    acc = np.eye(n)
    term = np.eye(n)
    for _ in range(k):
        term = term @ Q
        acc = acc + term
    return alpha * acc


def _load_R(ids: list[str]) -> tuple[pd.DataFrame, dict[str, int]]:
    if not ids:
        return pd.DataFrame(), {}
    signs = member_signs_ic(RUN_ID, ids)
    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    return R, signs


def _screen_pool(R: pd.DataFrame) -> dict[str, float]:
    metric: dict[str, float] = {}
    for aid in R.columns:
        r = R[aid]
        if r.dropna().size < 60:
            continue
        if not _year_stable(r):
            continue
        if _max_drawdown(r) > MAX_DD:
            continue
        z = _psr_z(r)
        if not np.isfinite(z):
            continue
        metric[aid] = z
    return metric


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    pool = select_is_submittable(RUN_ID)
    if not pool:
        if "is_sharpe" in alpha_index.columns:
            df = alpha_index.dropna(subset=["is_sharpe"]).sort_values(
                "is_sharpe", ascending=False
            )
            return df["alpha_id"].head(TARGET_N).tolist()
        return alpha_index["alpha_id"].head(TARGET_N).tolist()

    R, _ = _load_R(pool)
    if R.empty:
        return pool[:TARGET_N]

    metric = _screen_pool(R)
    if len(metric) < 2:
        # relax: drop year-stability, keep DD + PSR
        metric = {}
        for aid in R.columns:
            r = R[aid]
            if r.dropna().size < 60:
                continue
            if _max_drawdown(r) > 0.40:
                continue
            z = _psr_z(r)
            if np.isfinite(z):
                metric[aid] = z

    if len(metric) < 2:
        metric = {aid: _psr_z(R[aid]) for aid in R.columns}
        metric = {k: v for k, v in metric.items() if np.isfinite(v)}

    if len(metric) < 2:
        return pool[:TARGET_N]

    ranked = sorted(metric.items(), key=lambda kv: -kv[1])
    pool_size = max(TARGET_N * POOL_MULT, TARGET_N + 4)
    cand = [a for a, _ in ranked[:pool_size]]
    R_sub = R[cand]
    kept = correlation_dedup(R_sub, threshold=DEDUP_RHO, keep_metric=metric)
    if len(kept) < 2:
        kept = cand
    return list(kept)[:TARGET_N]


def member_weights(
    member_ids: list[str], alpha_index: pd.DataFrame
) -> dict[str, float]:
    ids = list(dict.fromkeys(member_ids))
    if len(ids) < 2:
        out = {a: 0.0 for a in ids}
        if ids:
            out[ids[0]] = GROSS_TARGET
        return out

    signs = member_signs_ic(RUN_ID, ids)
    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    R = R.dropna(axis=1, how="all")
    cols = list(R.columns)
    if len(cols) < 2:
        eq = GROSS_TARGET / max(1, len(ids))
        return {a: eq for a in ids}

    X = R.fillna(0.0).to_numpy(dtype=float)
    mu = X.mean(axis=0)
    Sigma = np.cov(X, rowvar=False, ddof=1)
    if not np.all(np.isfinite(Sigma)) or Sigma.shape[0] != len(cols):
        Sigma = np.eye(len(cols))

    inv_approx = _neumann_inverse(Sigma, NEUMANN_K)
    w = inv_approx @ mu

    if not np.all(np.isfinite(w)):
        w = np.ones(len(cols))
    # canonicalize direction; signs already absorbed into R via signs= load
    if float(w.sum()) < 0.0:
        w = -w
    w = np.clip(w, 0.0, None)
    if float(w.sum()) <= 1e-12:
        # PSR-tilt fallback
        z = np.array([max(0.0, _psr_z(R[c])) for c in cols], dtype=float)
        w = z if z.sum() > 0 else np.ones(len(cols))

    coef_aligned = dict(zip(cols, w.tolist()))
    coef_aligned = normalize_coefficients(coef_aligned, "l1")  # sum |c| = 1
    coef_aligned = {k: GROSS_TARGET * v for k, v in coef_aligned.items()}
    coef = apply_signs(coef_aligned, signs)

    for a in ids:
        coef.setdefault(a, 0.0)
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
