Looking at the iteration 44 prompt, I need to:
- Pick a fresh idea family not in the tried list (already tried: neumann_k5, NCO+MP+detone, HERC, BL, DRP, MaxDiv, CVaR, Kelly, HRP, James-Stein, CSCV, antibias, stability-IR, bootstrap-ERC, PBO+Spinu, PC1-resid, regime-year-stable, semivariance, hedge-macro, CCM, STARR, Calmar...).
- Honor leaderboard pattern: n=5-8, per-year stability, DD<25%, Neumann/MP cov inverse, ρ≈0.85 dedup.
- Honor user's explicit ask: high-return/high-risk + Neumann-series suppression.

**Method:** Stationary **block-bootstrap of the Sharpe ratio** (Lopez de Prado, *Advances in Financial Machine Learning*, 2018) as a non-IID-robust ranking metric — distinct from the prior CSCV / Michaud / vanilla-IS-Sharpe attempts because it uses *bootstrapped median Sharpe over block-resampled paths*, which empirically downweights alphas whose IS Sharpe is driven by a few clustered tail days (a common 2022 LUNA / 2024 ETF artifact). Combined with:
- per-tertile Sharpe positivity (regime-conditional robustness, Bai-Ng spirit)
- max-DD < 22% discipline
- correlation dedup ρ=0.85
- **truncated Neumann series cov inverse K=5** with Tikhonov nugget — Σ⁻¹ ≈ α Σₖ(I−αΣ)ᵏ with α=1/(1.5·λ_max(Σ)) estimated via power iteration, suppressing noisy high-eigenmode inversion
- tangency w ∝ Σ⁻¹μ on top-6 survivors, non-negativity-clipped to enforce the user-requested high-return tilt (any negative tangency weight on a sign-aligned member is a hedge that dilutes return — clip it).

```python COMPOSITE_FILE
"""Block-bootstrap robust Sharpe (Lopez de Prado AFML 2018) + per-tertile
regime stability + drawdown discipline + truncated Neumann-series cov inverse
(K=5) tangency on top-6 survivors. High-return tilt via non-negative clip on
deployable-basis tangency weights."""

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
    select_all_alphas,
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_044"
COMPOSITION_NOTE = "blockboot_sharpe_tertile_stable_dd22_neumann_k5_tangency_top6"

RUN_ID = "run_2026_05_c"
TOP_K = 6
DD_LIMIT = 0.22
DEDUP_RHO = 0.85
NEUMANN_K = 5
N_BOOT = 120
BLOCK = 10
SEED = 20260526


def _sharpe(r: np.ndarray) -> float:
    if len(r) < 2:
        return 0.0
    s = float(np.std(r, ddof=1))
    if not np.isfinite(s) or s <= 1e-12:
        return 0.0
    return float(np.mean(r) / s * np.sqrt(252.0))


def _max_dd(r: np.ndarray) -> float:
    if len(r) == 0:
        return 1.0
    eq = np.cumprod(1.0 + r)
    peak = np.maximum.accumulate(eq)
    safe = np.where(peak > 0, peak, 1.0)
    return float(np.max((peak - eq) / safe))


def _tertile_sharpes(r: np.ndarray) -> list[float]:
    n = len(r)
    if n < 12:
        return []
    p1, p2 = n // 3, 2 * n // 3
    out = []
    for sl in (r[:p1], r[p1:p2], r[p2:]):
        if len(sl) >= 4:
            out.append(_sharpe(sl))
    return out


def _block_boot_sharpe(r: np.ndarray, rng: np.random.Generator) -> float:
    T = len(r)
    if T < BLOCK * 4:
        return _sharpe(r)
    n_blocks = max(1, T // BLOCK)
    vals = np.empty(N_BOOT)
    arange_block = np.arange(BLOCK)
    for i in range(N_BOOT):
        starts = rng.integers(0, T - BLOCK + 1, n_blocks)
        idx = (starts[:, None] + arange_block[None, :]).ravel()
        vals[i] = _sharpe(r[idx])
    return float(np.median(vals))


def _filter_pool(R: pd.DataFrame) -> list[str]:
    keep = []
    for col in R.columns:
        r = R[col].dropna().values
        if len(r) < 30:
            continue
        ts = _tertile_sharpes(r)
        if not ts or min(ts) <= 0.0:
            continue
        if _max_dd(r) >= DD_LIMIT:
            continue
        keep.append(col)
    return keep


def _select_top(R: pd.DataFrame) -> list[str]:
    surv = _filter_pool(R)
    if len(surv) < TOP_K:
        relaxed = []
        for col in R.columns:
            r = R[col].dropna().values
            if len(r) < 30:
                continue
            ts = _tertile_sharpes(r)
            if ts and min(ts) > 0.0:
                relaxed.append(col)
        surv = relaxed if len(relaxed) >= TOP_K else list(R.columns)

    rng = np.random.default_rng(SEED)
    rs: dict[str, float] = {}
    for c in surv:
        rs[c] = _block_boot_sharpe(R[c].dropna().values, rng)

    cand = sorted(surv, key=lambda c: rs.get(c, 0.0), reverse=True)[:30]
    if len(cand) < 2:
        return cand[:max(2, len(cand))]
    deduped = correlation_dedup(R[cand], DEDUP_RHO, keep_metric=rs)
    if not deduped:
        deduped = cand
    final = sorted(deduped, key=lambda c: rs.get(c, 0.0), reverse=True)[:TOP_K]
    if len(final) < 2:
        final = sorted(surv, key=lambda c: rs.get(c, 0.0), reverse=True)[:max(2, TOP_K)]
    return final


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    ids = select_is_submittable(RUN_ID)
    if not ids or len(ids) < TOP_K:
        ids = select_all_alphas(RUN_ID)
    signs = member_signs_ic(RUN_ID, ids, dead_band=0.005)
    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    R = R.dropna(axis=1, how="all")
    if R.shape[1] < TOP_K:
        cols = list(R.columns)
        return cols[:max(2, len(cols))] if len(cols) >= 2 else cols
    return _select_top(R)


def _neumann_inv(Sigma: np.ndarray, K: int) -> np.ndarray:
    n = Sigma.shape[0]
    v = np.ones(n) / np.sqrt(n)
    for _ in range(40):
        u = Sigma @ v
        nrm = float(np.linalg.norm(u))
        if nrm < 1e-14:
            break
        v = u / nrm
    lam_max = float(v @ Sigma @ v)
    if not np.isfinite(lam_max) or lam_max <= 1e-12:
        return np.eye(n)
    alpha = 1.0 / (1.5 * lam_max)
    I = np.eye(n)
    M = I - alpha * Sigma
    acc = np.zeros_like(Sigma)
    Mk = I.copy()
    for _ in range(K + 1):
        acc = acc + Mk
        Mk = Mk @ M
    return alpha * acc


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    signs_full = member_signs_ic(RUN_ID, member_ids, dead_band=0.005)
    signs = {c: int(signs_full.get(c, 1)) for c in member_ids}
    R = load_member_is_returns(RUN_ID, member_ids, signs=signs)
    cols = [c for c in member_ids if c in R.columns]
    if len(cols) < 2:
        coef_dep = {c: 1.0 / max(1, len(cols)) for c in cols}
        coef = apply_signs(coef_dep, {c: signs.get(c, 1) for c in cols})
        return normalize_coefficients(coef, "l1")
    R = R[cols].dropna(axis=0, how="any")
    n = len(cols)
    if R.shape[0] < 30:
        coef_dep = {c: 1.0 / n for c in cols}
        coef = apply_signs(coef_dep, {c: signs.get(c, 1) for c in cols})
        return normalize_coefficients(coef, "l1")

    Sigma = R.cov().values * 252.0
    mu = R.mean().values * 252.0
    tr = float(np.trace(Sigma))
    tau = max(1e-6, 1e-3 * tr / max(1, n))
    Sigma_reg = Sigma + tau * np.eye(n)
    Sinv = _neumann_inv(Sigma_reg, NEUMANN_K)
    w = Sinv @ mu
    if not np.isfinite(w).all():
        w = np.maximum(mu, 0.0)
    # high-return tilt: clip negative tangency weights (hedging members dilute
    # the return objective once mu is already sign-aligned positive)
    w = np.where(w < 0, 0.0, w)
    if w.sum() <= 1e-12:
        w = np.maximum(mu, 0.0)
        if w.sum() <= 1e-12:
            w = np.ones(n)

    coef_dep = {cols[i]: float(w[i]) for i in range(n)}
    coef = apply_signs(coef_dep, {c: signs.get(c, 1) for c in cols})
    return normalize_coefficients(coef, "l1")


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
