"""Michaud (1998, 2008) resampled tangency with stationary block bootstrap and Ledoit-Wolf-shrunk covariance.

Cites: Michaud & Michaud (2008), "Estimation Error and Portfolio Optimization:
A Resampling Solution," Journal of Investment Management 6(1).
Block bootstrap: Politis & Romano (1994), "The Stationary Bootstrap," JASA.

Mechanism: resample the IS daily-return matrix B=240 times via block bootstrap
(block length 5 preserves short-term autocorr). On each resample, compute the
Ledoit-Wolf-shrunk sample covariance and a tangency weight vector
`w_b = Σ_b^{-1} μ_blend`, where μ_blend = 0.5·μ_boot + 0.5·μ_full (Stein-style
shrinkage on the mean — pure μ_boot is too noisy with T<1000). Average
unit-L1-normalized w_b across resamples. This is a frequentist regularizer:
members that are tangency-optimal across many sub-samples receive more weight;
members that win only in one particular slice get washed out — the structural
analog of "regime robustness" available without OS data.

Selection: SUBMITTABLE pool → IC-sign alignment → top 3*N candidates by IS Sharpe
→ correlation dedup at ρ=0.85 → top 8 by IS Sharpe. Final coefficients
re-signed and rescaled to mean row L1 ≈ 0.65 (in the [0.5, 0.9] sweet spot).
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

COMPOSITE_ID = "auto_031_michaud_resampled_tangency_stat_block_bo"
COMPOSITION_NOTE = "michaud_resampled_tangency_stat_block_boot_lw020_top8_dedup085_l1_065"
RUN_ID = "run_2026_05_c"

TARGET_N = 8
CAND_MULTIPLIER = 4
DEDUP_RHO = 0.85
N_BOOTSTRAP = 240
BLOCK_LEN = 5
SHRINK_LAMBDA = 0.20
TARGET_L1 = 0.65
MU_BLEND = 0.5
RIDGE_FLOOR = 1e-8
RNG_SEED = 20260526


def _is_sharpe(R: pd.DataFrame) -> dict[str, float]:
    mu = R.mean()
    sd = R.std(ddof=1).replace(0.0, np.nan)
    sh = (mu / sd) * np.sqrt(252.0)
    out: dict[str, float] = {}
    for c in R.columns:
        v = float(sh.get(c, np.nan))
        out[c] = v if np.isfinite(v) else -np.inf
    return out


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    ids = select_is_submittable(RUN_ID)
    if not ids:
        return []
    signs = member_signs_ic(RUN_ID, ids)
    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    R = R.dropna(axis=1, how="all")
    if R.shape[1] < 2:
        return list(R.columns)

    sh = _is_sharpe(R)
    sorted_ids = sorted(R.columns, key=lambda c: sh.get(c, -np.inf), reverse=True)
    cand_n = max(CAND_MULTIPLIER * TARGET_N, 24)
    cand = sorted_ids[:cand_n]
    R_cand = R[cand]
    kept = correlation_dedup(
        R_cand,
        threshold=DEDUP_RHO,
        keep_metric={c: sh.get(c, -np.inf) for c in cand},
    )
    kept_sorted = sorted(kept, key=lambda c: sh.get(c, -np.inf), reverse=True)
    final = kept_sorted[:TARGET_N]
    if len(final) < 2:
        final = sorted_ids[: max(TARGET_N, 4)]
    return final


def _stationary_block_indices(T: int, block: int, rng: np.random.Generator) -> np.ndarray:
    """Politis-Romano stationary bootstrap with mean block length `block`."""
    out = np.empty(T, dtype=np.int64)
    p = 1.0 / max(block, 1)
    i = int(rng.integers(0, T))
    for t in range(T):
        out[t] = i
        if rng.random() < p:
            i = int(rng.integers(0, T))
        else:
            i = (i + 1) % T
    return out


def _shrunk_cov(R_df: pd.DataFrame) -> np.ndarray:
    try:
        S = np.asarray(shrink_cov(R_df, shrinkage=SHRINK_LAMBDA), dtype=float)
    except Exception:
        Rn = R_df.values
        S_sample = np.cov(Rn.T)
        diag = np.diag(np.diag(S_sample))
        S = (1.0 - SHRINK_LAMBDA) * S_sample + SHRINK_LAMBDA * diag
    S = 0.5 * (S + S.T)
    S = S + RIDGE_FLOOR * np.eye(S.shape[0])
    return S


def _resampled_tangency(R: pd.DataFrame, rng: np.random.Generator) -> np.ndarray:
    T, N = R.shape
    R_np = R.values.astype(float)
    mu_full = R_np.mean(axis=0)
    # full-sample inverse for the μ_full leg of the blend
    S_full = _shrunk_cov(R)
    try:
        invS_full = sla.pinvh(S_full)
    except Exception:
        invS_full = np.linalg.pinv(S_full)
    w_full_base = invS_full @ mu_full

    w_avg = np.zeros(N, dtype=float)
    n_kept = 0
    for _ in range(N_BOOTSTRAP):
        idx = _stationary_block_indices(T, BLOCK_LEN, rng)
        Rb_np = R_np[idx]
        if Rb_np.shape[0] < N + 2:
            continue
        Rb_df = pd.DataFrame(Rb_np, columns=R.columns)
        S_b = _shrunk_cov(Rb_df)
        try:
            invS_b = sla.pinvh(S_b)
        except Exception:
            invS_b = np.linalg.pinv(S_b)
        mu_b = Rb_np.mean(axis=0)
        mu_blend = MU_BLEND * mu_b + (1.0 - MU_BLEND) * mu_full
        w_b = invS_b @ mu_blend
        # blend with full-sample baseline weights to dampen single-resample noise
        w_b = MU_BLEND * w_b + (1.0 - MU_BLEND) * w_full_base
        nrm = float(np.sum(np.abs(w_b)))
        if not np.isfinite(nrm) or nrm < 1e-12:
            continue
        w_avg += w_b / nrm
        n_kept += 1

    if n_kept == 0 or np.sum(np.abs(w_avg)) < 1e-12:
        sh = _is_sharpe(R)
        fallback = np.array([max(sh.get(c, 0.0), 0.0) for c in R.columns], dtype=float)
        if fallback.sum() <= 0:
            fallback = np.ones(N, dtype=float)
        return fallback
    return w_avg / max(n_kept, 1)


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    if len(member_ids) < 2:
        return {m: 1.0 for m in member_ids}
    signs = member_signs_ic(RUN_ID, member_ids)
    R = load_member_is_returns(RUN_ID, member_ids, signs=signs)
    R = R.dropna(axis=1, how="all")
    if R.shape[1] < 2:
        n = max(len(member_ids), 1)
        return {m: 1.0 / n for m in member_ids}

    rng = np.random.default_rng(RNG_SEED)
    w = _resampled_tangency(R, rng)
    coef: dict[str, float] = {c: float(w[i]) for i, c in enumerate(R.columns)}
    for m in member_ids:
        if m not in coef:
            coef[m] = 0.0

    # R was computed on sign-flipped streams; runner consumes coefficients on raw
    # weight streams, so multiply back by the IC-sign to recover deployable signs.
    coef_signed = apply_signs(coef, signs)

    coef_l1 = normalize_coefficients(coef_signed, "l1")
    coef_scaled = {k: float(v) * TARGET_L1 for k, v in coef_l1.items()}
    return coef_scaled


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