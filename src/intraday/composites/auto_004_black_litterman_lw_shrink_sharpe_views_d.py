"""Black-Litterman alpha pooling with Ledoit-Wolf shrinkage (He & Litterman 1999; Meucci 2010).

Prior is a 1/N equilibrium over correlation-deduped IS-submittable members; each member's
IS daily mean return is an absolute view (P=I, Q=mu_IS) with He-Litterman default uncertainty
Omega = diag(P*tau*Sigma*P'). Posterior mean is fed to a regularized mean-variance solve
against a Ledoit-Wolf shrunk covariance. Coefficients are returned to raw-sign space via
IC-derived signs, per-member capped, and rescaled to a controlled gross-exposure budget.
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
    shrink_cov,
    select_is_submittable,
    select_all_alphas,
    member_is_sharpe,
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_004_black_litterman_lw_shrink_sharpe_views_d"
COMPOSITION_NOTE = "black_litterman_lw_shrink_sharpe_views_dedup085_top25"

RUN_ID = "run_2026_05_c"
TARGET_K = 25
DEDUP_RHO = 0.85
GROSS_TARGET = 0.65
RISK_AVERSION = 2.5
TAU = 0.05
CAP_ABS = 0.20


def _as_series(x) -> pd.Series:
    if isinstance(x, pd.Series):
        return x
    if isinstance(x, dict):
        return pd.Series(x)
    return pd.Series(x)


def _kept_ids(kept) -> list[str]:
    if isinstance(kept, pd.DataFrame):
        return list(kept.columns)
    if isinstance(kept, pd.Series):
        return list(kept.index)
    return list(kept)


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    ids = select_is_submittable(RUN_ID)
    if ids is None or len(ids) < 4:
        ids = select_all_alphas(RUN_ID)
    ids = list(ids)

    sharpe = _as_series(member_is_sharpe(RUN_ID, ids)).dropna()
    sharpe = sharpe.sort_values(ascending=False)
    if sharpe.empty:
        return ids[: min(TARGET_K, len(ids))]

    ranked = sharpe.index.tolist()
    signs = member_signs_ic(RUN_ID, ranked)
    R = load_member_is_returns(RUN_ID, ranked, signs=signs)
    R = R.dropna(axis=1, how="all")
    common = [a for a in ranked if a in R.columns]
    if len(common) < 2:
        return ranked[: min(TARGET_K, len(ranked))]
    R = R[common]

    try:
        kept = correlation_dedup(R, threshold=DEDUP_RHO, rank_by=sharpe.loc[common])
    except TypeError:
        try:
            kept = correlation_dedup(R, DEDUP_RHO)
        except TypeError:
            kept = correlation_dedup(R)
    kept_set = set(_kept_ids(kept))
    deduped = [a for a in common if a in kept_set]

    chosen = deduped[:TARGET_K] if len(deduped) >= 2 else common[:TARGET_K]
    if len(chosen) < 2:
        chosen = common[: max(2, TARGET_K)]
    return chosen


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    ids = list(member_ids)
    if len(ids) < 2:
        n = max(len(ids), 1)
        return {a: GROSS_TARGET / n for a in ids}

    signs = member_signs_ic(RUN_ID, ids)
    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    R = R.reindex(columns=ids).dropna(how="all").fillna(0.0)
    use_ids = [a for a in ids if a in R.columns and float(R[a].abs().sum()) > 0.0]
    if len(use_ids) < 2:
        n = max(len(ids), 1)
        return {a: GROSS_TARGET / n for a in ids}
    R = R[use_ids]
    N = len(use_ids)

    mu = R.mean(axis=0).values.astype(float)

    Sigma_obj = shrink_cov(R)
    Sigma = Sigma_obj.values if isinstance(Sigma_obj, pd.DataFrame) else np.asarray(Sigma_obj, dtype=float)
    Sigma = 0.5 * (Sigma + Sigma.T)
    trS = float(np.trace(Sigma))
    ridge = (trS / N) * 1e-4 if trS > 0 else 1e-8
    Sigma = Sigma + ridge * np.eye(N)

    w_prior = np.full(N, 1.0 / N)
    pi = RISK_AVERSION * (Sigma @ w_prior)

    P = np.eye(N)
    Q = mu
    Omega = np.diag(np.diag(P @ (TAU * Sigma) @ P.T)) + 1e-10 * np.eye(N)

    tS_inv = sla.pinvh(TAU * Sigma)
    Om_inv = sla.pinvh(Omega)
    A = tS_inv + P.T @ Om_inv @ P
    b = tS_inv @ pi + P.T @ Om_inv @ Q
    mu_post = sla.solve(A, b, assume_a="sym")

    w = sla.solve(RISK_AVERSION * Sigma, mu_post, assume_a="sym")

    sign_vec = np.array([float(signs.get(a, 1.0)) for a in use_ids], dtype=float)
    sign_vec = np.where(sign_vec == 0.0, 1.0, sign_vec)
    w_raw = w * sign_vec

    w_raw = np.clip(w_raw, -CAP_ABS, CAP_ABS)

    s = pd.Series(w_raw, index=use_ids)
    if float(s.abs().sum()) <= 1e-12:
        s = pd.Series(sign_vec, index=use_ids) / N

    c = normalize_coefficients(s, "l1")
    if isinstance(c, dict):
        c = pd.Series(c)
    if not isinstance(c, pd.Series):
        c = pd.Series(np.asarray(c), index=use_ids)
    c = c.astype(float) * GROSS_TARGET

    out: dict[str, float] = {}
    for a in ids:
        v = c.get(a, 0.0)
        out[a] = float(v) if pd.notna(v) else 0.0
    return out


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