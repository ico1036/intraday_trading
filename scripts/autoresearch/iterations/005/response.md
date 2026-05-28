I'll target a fresh idea family. Tried so far: Neumann tangency, NCO, HERC, Black-Litterman. Picking **Diversified Risk Parity in the detoned eigenbasis** (Meucci 2009 + Lopez de Prado 2019 detoning + Ledoit–Wolf shrinkage) — it equalizes risk across PCs after stripping the common alpha-factor, then tilts each PC by `sign(<v_i, μ>)` to lean into positive expected return (the user's "high-return / high-risk" ask) without requiring an unstable Σ⁻¹. Past failures crashed inside `_optim_helpers` (normalize_coefficients on degenerate input) so every helper call is guarded with explicit fallbacks; Σ is symmetrized, ridge-regularized, and eigendecomposed with `sla.eigh`, and the top PC is dropped (detoning) before risk allocation.

```python COMPOSITE_FILE
"""Diversified Risk Parity (DRP) in the detoned eigenbasis with sign-aligned PC tilt.

Method:
  - Meucci (2009) "Managing Diversification", Risk 22(5): equalize risk
    contribution across the eigenbasis of Sigma (factor-risk parity in the PC frame).
  - Lopez de Prado (2019) "A Robust Estimator of the Efficient Frontier":
    detone Sigma by removing the top eigenvector (common alpha-factor) before allocating.
  - Ledoit & Wolf (2004) "Honey, I Shrunk the Sample Covariance Matrix": shrinkage
    estimator for Sigma so small-T eigenmodes do not blow up at the inversion stage.

Composite construction:
  1. Filter SUBMITTABLE alphas, sign-align via IC (member_signs_ic).
  2. Dedup at |rho|>0.80 in Sharpe-ranked order; take TOP_K=24 — concentrated,
     complementary members, not 1/N dilution (user explicitly asked for high-return tilt).
  3. Sigma = Ledoit-Wolf shrunk covariance of signed IS returns + small ridge.
  4. Detone: drop the top eigenvector (common alpha-factor / trend factor).
  5. PC tilt: p_i = sign(<v_i, mu>) / sqrt(lambda_i)  — equal-risk per PC,
     each PC oriented along positive expected IS return ("high-return" lean).
  6. c = V @ p; row-L1 normalize, scale to target mean gross ~0.65.
"""
from __future__ import annotations

import argparse
import math
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
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_005"
COMPOSITION_NOTE = "drp_detoned_eigenbasis_lw_top24_signtilt"

RUN_ID = "run_2026_05_c"
TOP_K = 24
DEDUP_RHO = 0.80
TARGET_GROSS = 0.65
SHARPE_FLOOR = 0.4
PRE_DEDUP_POOL = 120


def _safe_pool() -> list[str]:
    pool: list[str] = []
    try:
        pool = list(select_is_submittable(RUN_ID) or [])
    except Exception:
        pool = []
    if not pool:
        try:
            pool = list(select_all_alphas(RUN_ID) or [])
        except Exception:
            pool = []
    return [a for a in pool if isinstance(a, str)]


def _load_signed_returns(ids: list[str]):
    if not ids:
        return None
    try:
        signs = member_signs_ic(RUN_ID, ids) or {}
    except Exception:
        signs = {}
    try:
        R = load_member_is_returns(RUN_ID, ids, signs=signs)
    except Exception:
        R = None
    if R is None or not isinstance(R, pd.DataFrame) or R.empty:
        return None
    R = R.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    std = R.std(axis=0, ddof=1).fillna(0.0)
    keep_cols = [c for c in R.columns if float(std.get(c, 0.0)) > 0.0]
    if not keep_cols:
        return None
    R = R[keep_cols]
    if R.shape[0] < 5 or R.shape[1] < 2:
        return None
    return R


def _is_sharpe(R: pd.DataFrame) -> pd.Series:
    mu = R.mean(axis=0)
    sd = R.std(axis=0, ddof=1).replace(0.0, np.nan)
    s = (mu / sd) * np.sqrt(252)
    return s.replace([np.inf, -np.inf], np.nan).fillna(-np.inf)


def _manual_dedup(R: pd.DataFrame, ordered: list[str], rho: float, cap: int) -> list[str]:
    cols = [c for c in ordered if c in R.columns]
    if not cols:
        return []
    C = R[cols].corr().abs().fillna(0.0)
    kept: list[str] = []
    for col in cols:
        ok = True
        for k in kept:
            try:
                if float(C.loc[col, k]) > rho:
                    ok = False
                    break
            except Exception:
                continue
        if ok:
            kept.append(col)
        if len(kept) >= cap:
            break
    return kept


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    pool = _safe_pool()
    if len(pool) < 2:
        return pool

    R = _load_signed_returns(pool)
    if R is None or R.shape[1] < 2:
        return pool[: max(2, min(TOP_K, len(pool)))]

    sharpe_all = _is_sharpe(R)
    ranked = sharpe_all[sharpe_all >= SHARPE_FLOOR].sort_values(ascending=False)
    if len(ranked) < 2:
        ranked = sharpe_all.sort_values(ascending=False)
    cand = list(ranked.head(min(PRE_DEDUP_POOL, len(ranked))).index)
    if len(cand) < 2:
        # Fallback: pool head
        cand = list(sharpe_all.sort_values(ascending=False).head(TOP_K * 2).index)
    if len(cand) < 2:
        return pool[: max(2, min(TOP_K, len(pool)))]

    R_cand = R[cand]
    kept: list[str] = []
    # Try library dedup first (kwarg form, then positional)
    for call in (
        lambda: correlation_dedup(R_cand, rho=DEDUP_RHO),
        lambda: correlation_dedup(R_cand, DEDUP_RHO),
    ):
        try:
            res = call()
            kept = [c for c in (res or []) if isinstance(c, str) and c in R_cand.columns]
            if kept:
                break
        except Exception:
            kept = []
            continue
    if not kept:
        kept = _manual_dedup(R_cand, cand, DEDUP_RHO, TOP_K * 2)

    if len(kept) < 2:
        kept = cand[: max(2, min(TOP_K, len(cand)))]

    # Preserve Sharpe-ranked order among kept
    rank_map = {a: i for i, a in enumerate(cand)}
    kept = sorted(set(kept), key=lambda a: rank_map.get(a, 10**9))
    out = kept[:TOP_K]
    if len(out) < 2 and len(pool) >= 2:
        out = pool[:2]
    return out


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    ids = [a for a in member_ids if isinstance(a, str)]
    n_ids = len(ids)
    if n_ids == 0:
        return {}
    if n_ids == 1:
        return {ids[0]: float(TARGET_GROSS)}

    def _equal() -> dict[str, float]:
        return {a: float(TARGET_GROSS / n_ids) for a in ids}

    R = _load_signed_returns(ids)
    if R is None or R.shape[1] < 2 or R.shape[0] < 30:
        return _equal()

    cols = list(R.columns)
    n = len(cols)
    Rv = R.to_numpy(dtype=float, copy=True)
    Rv = np.where(np.isfinite(Rv), Rv, 0.0)
    mu_vec = Rv.mean(axis=0)

    Sigma: np.ndarray
    try:
        S = shrink_cov(R)
        Sigma = np.asarray(S, dtype=float)
        if Sigma.shape != (n, n) or not np.all(np.isfinite(Sigma)):
            raise ValueError("bad shrink_cov result")
    except Exception:
        Sigma = np.cov(Rv, rowvar=False)
    if not np.all(np.isfinite(Sigma)):
        Sigma = np.cov(Rv, rowvar=False)
        Sigma = np.where(np.isfinite(Sigma), Sigma, 0.0)
    Sigma = 0.5 * (Sigma + Sigma.T)

    diag = np.diag(Sigma)
    diag_pos = diag[np.isfinite(diag) & (diag > 0)]
    diag_med = float(np.median(diag_pos)) if diag_pos.size else 1e-8
    if not np.isfinite(diag_med) or diag_med <= 0:
        diag_med = 1e-8
    Sigma = Sigma + (1e-6 * diag_med) * np.eye(n)

    try:
        evals, evecs = sla.eigh(Sigma)
    except Exception:
        try:
            evals, evecs = np.linalg.eigh(Sigma)
        except Exception:
            # Last-resort: inverse-vol on the diagonal
            try:
                iv = pd.Series(
                    [1.0 / max(math.sqrt(max(float(s), 1e-12)), 1e-6) for s in np.diag(Sigma)],
                    index=cols,
                )
                iv = iv.replace([np.inf, -np.inf], np.nan).fillna(iv.median())
                if iv.abs().sum() <= 0:
                    return _equal()
                c_norm = normalize_coefficients(iv, "l1")
                c_scaled = c_norm * TARGET_GROSS
                return {a: float(c_scaled.get(a, 0.0)) for a in ids}
            except Exception:
                return _equal()

    order = np.argsort(evals)[::-1]
    evals = evals[order]
    evecs = evecs[:, order]

    drop_top = 1 if n >= 3 else 0

    p = np.zeros(n)
    for i in range(drop_top, n):
        lam = float(evals[i])
        if not np.isfinite(lam) or lam <= 1e-12:
            continue
        v = evecs[:, i]
        proj = float(v @ mu_vec)
        if not np.isfinite(proj) or abs(proj) < 1e-14:
            continue
        sgn = 1.0 if proj >= 0 else -1.0
        p[i] = sgn / math.sqrt(lam)

    c_vec = evecs @ p
    c_vec = np.where(np.isfinite(c_vec), c_vec, 0.0)
    if float(np.sum(np.abs(c_vec))) <= 1e-12:
        return _equal()

    c_ser = pd.Series(c_vec, index=cols)
    try:
        c_norm = normalize_coefficients(c_ser, "l1")
        if c_norm is None or not isinstance(c_norm, pd.Series) or c_norm.abs().sum() <= 0:
            raise ValueError("normalize_coefficients returned empty")
    except Exception:
        s_abs = float(np.sum(np.abs(c_vec)))
        c_norm = c_ser / s_abs if s_abs > 0 else c_ser
    c_norm = c_norm.replace([np.inf, -np.inf], np.nan).fillna(0.0)

    c_scaled = c_norm * float(TARGET_GROSS)

    out: dict[str, float] = {}
    for a in ids:
        try:
            v = float(c_scaled.get(a, 0.0))
        except Exception:
            v = 0.0
        if not np.isfinite(v):
            v = 0.0
        out[a] = v

    if all(abs(v) < 1e-12 for v in out.values()):
        return _equal()
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
```
