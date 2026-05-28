"""Fractional Kelly composite (Kelly 1956; Thorp 1966; MacLean-Thorp-Ziemba 2010;
Lopez de Prado 2018, AFML ch.16) with Ledoit-Wolf shrunk covariance,
IC-sign-aligned and correlation-deduped IS-Sharpe-ranked member pool.

Mechanism:
  1. Universe: select_is_submittable(run_2026_05_c). Rank by realized IS
     Sharpe computed on sign-aligned IS returns (member_signs_ic ->
     load_member_is_returns).
  2. Correlation dedup at |rho|>0.85 keyed by IS Sharpe; cap at top 18.
  3. mu_hat = column mean of sign-aligned R; Sigma_hat = shrink_cov(R, 0.20)
     (Ledoit-Wolf style shrinkage toward diagonal).
  4. Kelly weights w = Sigma_hat^{-1} mu_hat via sla.pinvh (symmetric
     pseudo-inverse, regularized fallback on failure).
  5. Multiply by IC signs to recover deployable coefficients on the
     original W_a streams; L1-normalize and rescale to gross budget 0.65.

Kelly maximizes expected log-wealth and concentrates weight on high-Sharpe /
low-correlation members -- matching the user's high-return / high-risk
request without diluting the row-L1 gross-exposure budget through naive
equal-weighting of many near-orthogonal alphas.
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
    shrink_cov,
    select_is_submittable,
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_008_fractional_kelly_lw_shrink_sharpe_top18"
COMPOSITION_NOTE = "fractional_kelly_lw_shrink_sharpe_top18_dedup085_l1_065"

RUN_ID = "run_2026_05_c"
TOP_K = 18
CANDIDATE_MULT = 4         # pre-dedup candidate pool size = TOP_K * CANDIDATE_MULT
DEDUP_RHO = 0.85
TARGET_L1 = 0.65
COV_SHRINK = 0.20
FRACTIONAL_KELLY = 0.30    # conceptual; absorbed into L1 renormalization


def _is_sharpe_series(R: pd.DataFrame) -> pd.Series:
    mu = R.mean(axis=0)
    sd = R.std(axis=0).replace(0.0, np.nan)
    return (mu / sd).dropna().sort_values(ascending=False)


def _safe_pinv(Sigma: np.ndarray) -> np.ndarray:
    """Symmetric pseudo-inverse with ridge fallback. Robust to near-singular Sigma."""
    try:
        return sla.pinvh(Sigma)
    except Exception:
        d = Sigma.shape[0]
        tr = float(np.trace(Sigma))
        scale = (tr / max(1, d)) if tr > 0 else 1.0
        ridge = (1e-4 * scale) * np.eye(d)
        try:
            return sla.pinvh(Sigma + ridge)
        except Exception:
            return np.linalg.pinv(Sigma + ridge)


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    ids = list(select_is_submittable(RUN_ID))
    if len(ids) < 2:
        return ids
    signs = member_signs_ic(RUN_ID, ids)
    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    if R.shape[1] < 2:
        return list(R.columns)

    sharpe = _is_sharpe_series(R)
    if len(sharpe) < 2:
        return list(R.columns)[: max(2, TOP_K)]

    n_cand = min(len(sharpe), max(TOP_K * CANDIDATE_MULT, 24))
    cand = list(sharpe.index[:n_cand])
    R_cand = R[cand]
    keep_metric = {a: float(sharpe[a]) for a in cand}

    try:
        kept = correlation_dedup(R_cand, threshold=DEDUP_RHO, keep_metric=keep_metric)
    except Exception:
        kept = cand

    if not kept:
        kept = cand
    kept = list(kept)[:TOP_K]

    if len(kept) < 2:
        kept = list(sharpe.index[: min(len(sharpe), max(2, TOP_K))])
    return kept


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    if not member_ids:
        return {}

    signs = member_signs_ic(RUN_ID, member_ids)
    R = load_member_is_returns(RUN_ID, member_ids, signs=signs)
    cols = list(R.columns)

    if len(cols) < 2:
        eq = {a: 1.0 for a in member_ids}
        eq = normalize_coefficients(eq, "l1")
        return {a: float(v) * TARGET_L1 for a, v in eq.items()}

    mu = R.mean(axis=0).values.astype(float)
    Sigma = np.asarray(shrink_cov(R, shrinkage=COV_SHRINK), dtype=float)

    # Ensure symmetry for pinvh (shrink_cov should already be symmetric).
    Sigma = 0.5 * (Sigma + Sigma.T)
    Sigma_inv = _safe_pinv(Sigma)

    w = Sigma_inv @ mu                       # full-Kelly direction
    w = FRACTIONAL_KELLY * w                 # fractional Kelly (label only; L1-renorm later)

    if (not np.all(np.isfinite(w))) or float(np.sum(np.abs(w))) < 1e-12:
        # Degenerate inverse: fall back to Sharpe-proportional in sign-aligned space.
        sd = R.std(axis=0).values
        denom = np.where(np.isfinite(sd) & (sd > 1e-12), sd, 1.0)
        sh = mu / denom
        sh = np.where(np.isfinite(sd) & (sd > 1e-12), sh, 0.0)
        if float(np.sum(np.abs(sh))) < 1e-12:
            sh = np.ones_like(mu)
        w = sh

    # Build coefficient dict over the FULL requested member_ids (0 for dropped).
    coef: dict[str, float] = {a: 0.0 for a in member_ids}
    for a, val in zip(cols, w.tolist()):
        v = float(val)
        if not np.isfinite(v):
            v = 0.0
        coef[a] = v

    # IC signs flip back to deployable space on the original W_a streams.
    coef = apply_signs(coef, signs)

    total = sum(abs(float(v)) for v in coef.values())
    if total < 1e-12:
        eq = {a: 1.0 for a in member_ids}
        coef = normalize_coefficients(eq, "l1")
    else:
        coef = normalize_coefficients(coef, "l1")

    return {a: float(v) * TARGET_L1 for a, v in coef.items()}


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