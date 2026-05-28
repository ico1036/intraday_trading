"""Recency-biased composite: EWMA covariance (RiskMetrics, J.P.Morgan 1996) with
exponential half-life ~69 days, time-decayed Sharpe selection on top-8 dedup'd at
|rho|=0.85, tangency on ridge-shrunk EWMA Sigma. Thesis: IS-tail regime is closer
to OS start than IS-head, so weighting recent returns prefers alphas still 'in form'
at the IS/OS boundary."""
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
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_030_ewma_riskmetrics_recency_sharpe_top8_tan"
COMPOSITION_NOTE = "ewma_riskmetrics_recency_sharpe_top8_tangency_ridge_gross070"

RUN_ID = "run_2026_05_c"
LAMBDA_EWMA = 0.99           # half-life ~69 daily bars
TOP_K = 8
CORR_THRESH = 0.85
GROSS_TARGET = 0.70
SHRINK_ALPHA = 0.10          # Sigma shrinkage toward mean-diag identity


def _ewma_weights(T: int, lam: float) -> np.ndarray:
    if T <= 0:
        return np.ones(1)
    idx = np.arange(T)
    w = lam ** (T - 1 - idx)   # newest = 1, oldest = lam^(T-1)
    s = w.sum()
    return w / s if s > 0 else np.ones(T) / T


def _ewma_mean_cov(R: pd.DataFrame, lam: float):
    X = R.fillna(0.0).to_numpy(dtype=float)
    T = X.shape[0]
    w = _ewma_weights(T, lam)
    mu = (w[:, None] * X).sum(axis=0)
    Xc = X - mu
    Sigma = (Xc * w[:, None]).T @ Xc
    return mu, Sigma


def _recency_sharpe(mu: np.ndarray, Sigma: np.ndarray) -> np.ndarray:
    sd = np.sqrt(np.maximum(np.diag(Sigma), 1e-12))
    rs = mu / sd
    return np.where(np.isfinite(rs), rs, -1e9)


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    ids = select_is_submittable(RUN_ID)
    if not ids or len(ids) < 2:
        ids = [str(a) for a in alpha_index["alpha_id"].tolist()]
    signs = member_signs_ic(RUN_ID, ids)
    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    cols = list(R.columns)
    if len(cols) < 2:
        return cols if len(cols) >= 2 else (cols + ids[:2])[:2]

    mu, Sigma = _ewma_mean_cov(R, LAMBDA_EWMA)
    rs = _recency_sharpe(mu, Sigma)
    rs_dict = {a: float(v) for a, v in zip(cols, rs)}

    try:
        kept = correlation_dedup(R, threshold=CORR_THRESH, keep_metric=rs_dict)
    except Exception:
        kept = cols
    if not kept:
        kept = cols

    kept_sorted = sorted(kept, key=lambda a: rs_dict.get(a, -1e9), reverse=True)
    top = kept_sorted[:TOP_K]
    if len(top) < 2:
        top = sorted(cols, key=lambda a: rs_dict.get(a, -1e9), reverse=True)[: max(2, TOP_K)]
    return top


def _equal_fallback(member_ids: list[str], signs: dict) -> dict:
    n = max(1, len(member_ids))
    c_eq = {a: 1.0 / n for a in member_ids}
    c_eq = normalize_coefficients(c_eq, "l1")
    c_scaled = {a: GROSS_TARGET * v for a, v in c_eq.items()}
    return apply_signs(c_scaled, signs)


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    signs = member_signs_ic(RUN_ID, member_ids)
    R = load_member_is_returns(RUN_ID, member_ids, signs=signs)
    cols = list(R.columns)
    if len(cols) < 2:
        return _equal_fallback(member_ids, signs)

    mu, Sigma = _ewma_mean_cov(R, LAMBDA_EWMA)
    n = Sigma.shape[0]
    diag_mean = float(np.mean(np.diag(Sigma)))
    if not np.isfinite(diag_mean) or diag_mean <= 0:
        diag_mean = 1e-8
    Sigma_reg = (1.0 - SHRINK_ALPHA) * Sigma + SHRINK_ALPHA * diag_mean * np.eye(n)

    try:
        w = sla.solve(Sigma_reg, mu, assume_a="pos")
    except Exception:
        try:
            w = sla.pinvh(Sigma_reg) @ mu
        except Exception:
            w = mu / np.maximum(np.diag(Sigma_reg), 1e-12)

    w = np.where(np.isfinite(w), w, 0.0)
    if not np.any(np.abs(w) > 0):
        return _equal_fallback(member_ids, signs)

    c_dict = {a: float(v) for a, v in zip(cols, w)}
    for a in member_ids:
        c_dict.setdefault(a, 0.0)

    c_norm = normalize_coefficients(c_dict, "l1")
    c_scaled = {a: GROSS_TARGET * float(v) for a, v in c_norm.items()}
    return apply_signs(c_scaled, signs)


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