"""Neumann-series MinVar on year-robust concentrated top-5 IS-Sharpe alphas.

Method: Truncated-Neumann inverse of Ledoit-Wolf-shrunk covariance for a
pure minimum-variance combination (w ∝ Σ⁻¹·𝟙, no mean term — avoids
mean-estimate error in the IS→OS transfer). Σ⁻¹ ≈ α·Σ_{k=0}^{K=5}(I−αΣ)^k
with α = 1.5/λ_max(Σ), λ_max from power iteration (50 steps). Selection
defends against regime change: per-year IS-Sharpe stability (positive in
every IS sub-year), max IS drawdown < 25%, correlation dedup at
|ρ|≤0.85, then top-5 by IS-Sharpe. Sign-alignment via IC dead-band.
Mean row L1 targeted at ≈0.7 of the budget for adequate gross exposure.
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
    select_is_submittable,
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_025_neumann_minvar_year_robust_top5_dd25_ded"
COMPOSITION_NOTE = "neumann_minvar_year_robust_top5_dd25_dedup085_sign_ic"
RUN_ID = "run_2026_05_c"

_TARGET_GROSS = 0.70
_DD_FLOOR = -0.25
_DEDUP_RHO = 0.85
_TOP_K = 5
_NEUMANN_K = 5


def _annualized_sharpe(r: pd.Series) -> float:
    s = r.dropna()
    if len(s) < 20:
        return float("-inf")
    sd = float(s.std(ddof=0))
    if sd <= 1e-12:
        return float("-inf")
    return float(s.mean() / sd) * math.sqrt(252.0)


def _year_stable(r: pd.Series, min_years: int = 2) -> bool:
    s = r.dropna()
    if s.empty:
        return False
    idx = pd.to_datetime(s.index, errors="coerce")
    df = pd.Series(s.values, index=idx).dropna()
    if df.empty:
        return False
    by_year = df.groupby(df.index.year)
    n_years = 0
    n_pos = 0
    for _, g in by_year:
        if len(g) < 30:
            continue
        n_years += 1
        sd = float(g.std(ddof=0))
        if sd <= 1e-12:
            continue
        mu = float(g.mean())
        if mu / sd > 0.0:
            n_pos += 1
    if n_years < min_years:
        # not enough yearly evidence; do not reject solely on this basis
        return True
    return n_pos == n_years


def _max_drawdown(r: pd.Series) -> float:
    s = r.dropna()
    if s.empty:
        return 0.0
    equity = (1.0 + s).cumprod()
    peak = equity.cummax()
    dd = (equity / peak) - 1.0
    return float(dd.min())


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    ids = list(select_is_submittable(RUN_ID))
    if len(ids) < _TOP_K:
        ids = [str(x) for x in alpha_index["alpha_id"].tolist()]
    signs = member_signs_ic(RUN_ID, ids)
    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    if R is None or R.shape[1] < 2:
        return ids[: max(2, min(len(ids), _TOP_K))]

    sharpe_map: dict[str, float] = {}
    for col in R.columns:
        sharpe_map[col] = _annualized_sharpe(R[col])

    # year stability
    keep = [c for c in R.columns if _year_stable(R[c])]
    if len(keep) < _TOP_K:
        keep = list(R.columns)

    # drawdown discipline
    keep_dd = [c for c in keep if _max_drawdown(R[c]) > _DD_FLOOR]
    if len(keep_dd) < _TOP_K:
        keep_dd = keep

    # correlation dedup, ranking by IS sharpe
    R_sub = R[keep_dd]
    try:
        deduped = list(
            correlation_dedup(R_sub, threshold=_DEDUP_RHO, keep_metric=sharpe_map)
        )
    except Exception:
        deduped = list(R_sub.columns)
    if len(deduped) < 2:
        deduped = list(R_sub.columns)

    deduped_sorted = sorted(
        deduped, key=lambda c: sharpe_map.get(c, float("-inf")), reverse=True
    )
    chosen = deduped_sorted[:_TOP_K]
    if len(chosen) < 2:
        # final fallback: top-2 by raw sharpe across full R
        all_sorted = sorted(
            R.columns, key=lambda c: sharpe_map.get(c, float("-inf")), reverse=True
        )
        chosen = list(all_sorted[: max(2, _TOP_K)])
    return chosen


def _power_lambda_max(M: np.ndarray, iters: int = 50) -> float:
    n = M.shape[0]
    rng = np.random.default_rng(0)
    v = rng.standard_normal(n)
    nrm = np.linalg.norm(v)
    if nrm <= 0:
        return 1.0
    v = v / nrm
    for _ in range(iters):
        v = M @ v
        nrm = np.linalg.norm(v)
        if nrm <= 1e-18:
            return 1.0
        v = v / nrm
    return float(v @ (M @ v))


def _neumann_inverse(Sigma: np.ndarray, K: int = 5) -> np.ndarray:
    n = Sigma.shape[0]
    lam_max = _power_lambda_max(Sigma, iters=60)
    if not np.isfinite(lam_max) or lam_max <= 0:
        lam_max = float(np.trace(Sigma) / max(1, n))
    if lam_max <= 0:
        lam_max = 1.0
    # alpha chosen so ‖I−αΣ‖_op < 1 for positive-definite Σ; 1.5/λ_max
    # works because eigenvalues of (I−αΣ) lie in (1−1.5, 1) ⊂ (−0.5, 1).
    alpha = 1.5 / (lam_max + 1e-12)
    I = np.eye(n)
    M = I - alpha * Sigma
    acc = np.zeros_like(Sigma)
    term = I.copy()
    for _ in range(K + 1):
        acc = acc + term
        term = term @ M
    return alpha * acc


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    signs = member_signs_ic(RUN_ID, member_ids)
    R = load_member_is_returns(RUN_ID, member_ids, signs=signs)

    if R is None or R.shape[1] < 2:
        eq = 1.0 / max(1, len(member_ids))
        coef = {m: eq for m in member_ids}
        coef = normalize_coefficients(coef, "l1")
        coef = {k: v * _TARGET_GROSS for k, v in coef.items()}
        for m in member_ids:
            coef.setdefault(m, 0.0)
        return apply_signs(coef, signs)

    cols = list(R.columns)
    X = R[cols].fillna(0.0).to_numpy(dtype=float)
    T, N = X.shape

    if T < 30 or N < 2:
        eq = 1.0 / max(1, N)
        coef = {c: eq for c in cols}
        coef = normalize_coefficients(coef, "l1")
        coef = {k: v * _TARGET_GROSS for k, v in coef.items()}
        for m in member_ids:
            coef.setdefault(m, 0.0)
        return apply_signs(coef, signs)

    mu = X.mean(axis=0, keepdims=True)
    Xc = X - mu
    S = (Xc.T @ Xc) / max(1, T - 1)

    # Diagonal-target shrinkage (Ledoit-Wolf flavour with fixed intensity).
    target = np.diag(np.diag(S))
    shrink = 0.20
    Sigma = (1.0 - shrink) * S + shrink * target
    # tiny ridge for numerical stability in Neumann iteration
    Sigma = Sigma + 1e-6 * np.eye(N)

    Sinv = _neumann_inverse(Sigma, K=_NEUMANN_K)
    ones = np.ones(N)
    w_raw = Sinv @ ones

    if not np.all(np.isfinite(w_raw)):
        w_raw = ones / N

    # If MinVar weights are pathological (all-near-zero or wildly negative),
    # fall back to inverse-variance.
    if float(np.sum(np.abs(w_raw))) <= 1e-10 or (w_raw < 0).sum() > N // 2:
        inv_var = 1.0 / (np.diag(S) + 1e-12)
        w_raw = inv_var

    coef = {cols[i]: float(w_raw[i]) for i in range(N)}
    coef = normalize_coefficients(coef, "l1")
    coef = {k: v * _TARGET_GROSS for k, v in coef.items()}

    for m in member_ids:
        coef.setdefault(m, 0.0)

    return apply_signs(coef, signs)


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