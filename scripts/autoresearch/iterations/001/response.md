**Reasoning — Iteration 1 design**

The user's hint asks for a high-return/high-risk combination with Neumann-series eigenvalue-divergence suppression. The mathematical setup: a truncated Neumann expansion `Σ⁻¹ ≈ α·Σ_{k=0}^{K}(I−αΣ)^k` with `α = 1/(1.05·λ_max(Σ))` converges fast in the large-eigenvalue (signal) directions but stays bounded away from `1/λ` in the small-eigenvalue (noise) directions. That is exactly the "divergence suppression" property: full Σ⁻¹ would amplify noise modes by 1/λ_small, the K-truncated operator caps that amplification at `α·(K+1)`. With K=5 and α≈1/λ_max we get noise-mode gains capped at ~6/λ_max — a clean RMT-flavoured shrinkage without computing eigendecompositions.

For "high-return / high-risk focus" I apply this regularized inverse to the IS mean-return vector μ to get a tangency-direction coefficient `c = Σ̂⁻¹·μ`, rather than to `𝟙` (min-var). Tangency emphasises high-Sharpe members; min-var would dilute toward equal weighting on uncorrelated junk.

Pipeline:
1. Pull SUBMITTABLE alphas for `run_2026_05_c`, rank by IS Sharpe, keep top 60.
2. Sign-align via `member_signs_ic` so each member contributes in its deployable direction; load IS returns.
3. Greedy IS-Sharpe-ordered correlation dedup at |ρ|>0.85 (Lopez de Prado's near-clone removal heuristic).
4. Compute sample Σ with tiny ridge (1e-6·tr/N) for numerical safety.
5. Power-iterate λ_max(Σ); build Neumann inverse with K=5.
6. `c = Σ̂_neumann⁻¹ · μ`, re-multiply by IC signs (since the runner sees raw weight streams, not flipped ones), `l1`-normalize, then scale by 0.75 so pre-row-L1 gross ≈ 0.75 — well inside the [0.3, 0.9] mean-row-L1 budget.

Citation: Neumann-series regularised inverse for the precision matrix (cf. Lopez de Prado, *Machine Learning for Asset Managers*, ch. 2 on detoning/denoising — the Neumann truncation is equivalent in spirit to Marchenko-Pastur eigenvalue clipping but matrix-free).

```python COMPOSITE_FILE
"""Tangency-portfolio composite via truncated Neumann-series Σ⁻¹ with
eigenvalue-divergence suppression (K=5). Matrix-free analogue of
Marchenko-Pastur denoising in the spirit of Lopez de Prado (MLAM ch. 2):
the K-truncated Neumann inverse converges fast in large-eigenvalue
directions and stays bounded in noise directions, capping the 1/λ blow-up
that pollutes raw min-var / tangency weights. Applied to IS mean returns
to obtain a high-Sharpe-focused tangency direction; high-IS-Sharpe
pre-filter + IC-sign alignment + ρ=0.85 dedup keep the active set lean."""
from __future__ import annotations

import argparse
import numpy as np
import pandas as pd

from intraday.composites._runner import build_and_backtest
from intraday.composites._optim_helpers import (
    member_signs_ic,
    select_is_submittable,
    select_all_alphas,
    member_is_sharpe,
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_001"
COMPOSITION_NOTE = "neumann_K5_tangency_top60_dedup085_gross075"

RUN_ID = "run_2026_05_c"
TOP_K = 60
DEDUP_RHO = 0.85
NEUMANN_K = 5
TARGET_GROSS = 0.75
RIDGE_EPS = 1e-6


def _greedy_corr_dedup(R: pd.DataFrame, sharpe: dict, rho: float) -> list[str]:
    cols = [c for c in R.columns if R[c].abs().sum() > 0.0]
    if len(cols) <= 1:
        return cols
    cols.sort(key=lambda a: -float(sharpe.get(a, -np.inf)))
    sub = R[cols].fillna(0.0)
    corr = sub.corr().abs().fillna(0.0).to_numpy()
    kept: list[int] = [0]
    for i in range(1, len(cols)):
        if all(corr[i, j] <= rho for j in kept):
            kept.append(i)
    return [cols[i] for i in kept]


def _power_iter_lambda_max(M: np.ndarray, iters: int = 50) -> float:
    n = M.shape[0]
    rng = np.random.default_rng(20260526)
    x = rng.standard_normal(n)
    nrm = np.linalg.norm(x)
    if nrm < 1e-12:
        return 1.0
    x = x / nrm
    lam = 1.0
    for _ in range(iters):
        y = M @ x
        ny = np.linalg.norm(y)
        if ny < 1e-15:
            return max(lam, 1e-12)
        lam = ny
        x = y / ny
    return float(lam)


def _neumann_inverse(Sigma: np.ndarray, K: int) -> np.ndarray:
    n = Sigma.shape[0]
    lam_max = _power_iter_lambda_max(Sigma)
    alpha = 1.0 / (1.05 * lam_max + 1e-12)
    I = np.eye(n)
    M = I - alpha * Sigma            # spectral radius < 1 by construction
    acc = np.eye(n)
    Mp = np.eye(n)
    for _ in range(K):
        Mp = Mp @ M
        acc = acc + Mp
    return alpha * acc


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    ids = select_is_submittable(RUN_ID)
    if ids is None or len(ids) < 2:
        ids = select_all_alphas(RUN_ID)
    ids = list(dict.fromkeys(ids))
    if len(ids) < 2:
        return ids
    sharpe = member_is_sharpe(RUN_ID, ids) or {}
    ranked = sorted(ids, key=lambda a: -float(sharpe.get(a, -np.inf)))
    top = ranked[: max(TOP_K, 2)]
    signs = member_signs_ic(RUN_ID, top) or {}
    R = load_member_is_returns(RUN_ID, top, signs=signs)
    if R is None or R.shape[1] < 2:
        return top[:2]
    R = R.dropna(axis=1, how="all").fillna(0.0)
    if R.shape[1] < 2:
        return top[:2]
    kept = _greedy_corr_dedup(R, sharpe, DEDUP_RHO)
    if len(kept) < 2:
        kept = list(R.columns[:2])
    # Cap at 30 to keep typical-member-weight magnitudes meaningful.
    return kept[:30]


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    member_ids = list(member_ids)
    n = len(member_ids)
    if n == 0:
        return {}
    signs = member_signs_ic(RUN_ID, member_ids) or {}
    sgn_vec = np.array([float(signs.get(m, 1.0)) for m in member_ids], dtype=np.float64)

    R = load_member_is_returns(RUN_ID, member_ids, signs=signs)
    if R is None or R.shape[0] < 8 or R.shape[1] < 2:
        c = np.ones(n, dtype=np.float64)
    else:
        R = R.reindex(columns=member_ids).fillna(0.0)
        X = R.to_numpy(dtype=np.float64)
        Sigma = np.cov(X, rowvar=False)
        if Sigma.ndim == 0:
            Sigma = np.array([[float(Sigma)]], dtype=np.float64)
        Sigma = 0.5 * (Sigma + Sigma.T)
        tr_mean = float(np.trace(Sigma)) / max(Sigma.shape[0], 1) + 1e-12
        Sigma = Sigma + RIDGE_EPS * tr_mean * np.eye(Sigma.shape[0])
        Sinv = _neumann_inverse(Sigma, NEUMANN_K)
        mu = X.mean(axis=0)
        c = Sinv @ mu
        if not np.all(np.isfinite(c)) or float(np.linalg.norm(c)) < 1e-12:
            c = np.ones(n, dtype=np.float64)

    # Suppress negatives in the regularised basis: a negative tangency
    # coefficient means the member harms IS Sharpe under the model — drop it
    # rather than carry it short in the deployed stack.
    c = np.where(c < 0.0, 0.0, c)
    if float(np.sum(c)) < 1e-12:
        c = np.ones(n, dtype=np.float64)

    # Deploy in raw-weight basis: multiply by IC sign.
    c = c * sgn_vec

    cn = np.asarray(normalize_coefficients(c, "l1"), dtype=np.float64)
    if not np.all(np.isfinite(cn)) or float(np.sum(np.abs(cn))) < 1e-12:
        cn = sgn_vec / max(float(np.sum(np.abs(sgn_vec))), 1.0)
    cn = cn * TARGET_GROSS
    return {mid: float(cn[i]) for i, mid in enumerate(member_ids)}


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
