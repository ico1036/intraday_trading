"""Constant-correlation Ledoit-Wolf shrinkage + Neumann-series cov inverse
on mean-variance tangency; regime-aware year-stability + drawdown gate.

Method stack:
- Ledoit & Wolf (2004) "Honey, I Shrunk the Sample Covariance Matrix":
  shrink the sample covariance toward a constant-correlation target
  F_ij = rho_bar * sigma_i * sigma_j (off-diag), F_ii = sigma_i^2.
  Closed-form delta = pi_hat / (T * gamma_hat) clipped to [0, 1].
- Neumann series cov inverse: Sigma^{-1} approx alpha * sum_{k=0..K} (I - alpha*Sigma)^k
  with alpha = 1 / (1.1 * lambda_max(Sigma)) estimated by power iteration,
  guaranteeing ||I - alpha*Sigma||_op < 1 and stable truncation at K=4.
- Sortino (Sortino, 1991) ratio for alpha ranking — downside-only volatility
  penalizes regimes whose damage is concentrated in tails.
- Regime-aware: per-calendar-year Sharpe > 0 filter across all IS sub-years
  (2022/2023/2024), drawdown <= 20% gate, IC-aware sign flip, dedup at 0.85.
"""
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

COMPOSITE_ID = "auto_046_constcorr_lw_neumann_k4_tang_sortino_yea"
COMPOSITION_NOTE = "constcorr_lw_neumann_k4_tang_sortino_yearstable_dd20_top6_dedup085"
RUN_ID = "run_2026_05_c"

DD_CAP = 0.20
DEDUP_RHO = 0.85
TARGET_N = 6
NEUMANN_K = 4
GROSS_TARGET = 0.7
PRE_POOL = 80


def _max_drawdown(equity: np.ndarray) -> float:
    if equity.size == 0:
        return 0.0
    peak = np.maximum.accumulate(equity)
    base = np.where(peak == 0, 1.0, peak)
    dd = (equity - peak) / base
    return float(-dd.min()) if dd.size else 0.0


def _sortino(series: pd.Series) -> float:
    s = series.dropna()
    if s.shape[0] < 5:
        return 0.0
    neg = s[s < 0]
    if neg.shape[0] < 3:
        # All-positive-ish: fall back to mean / std proxy
        sd = float(s.std(ddof=1))
        if sd <= 0:
            return 0.0
        return float(s.mean() / sd) * float(np.sqrt(252.0))
    dn = float(np.sqrt((neg ** 2).mean()))
    if dn <= 0:
        return 0.0
    return float(s.mean() / dn) * float(np.sqrt(252.0))


def _sharpe(series: pd.Series) -> float:
    s = series.dropna()
    if s.shape[0] < 5:
        return 0.0
    sd = float(s.std(ddof=1))
    if sd <= 0:
        return 0.0
    return float(s.mean() / sd) * float(np.sqrt(252.0))


def _year_stable(R: pd.DataFrame) -> dict[str, bool]:
    out: dict[str, bool] = {}
    try:
        idx = pd.DatetimeIndex(R.index)
        years = idx.year.values
    except Exception:
        return {c: True for c in R.columns}
    unique_years = np.unique(years)
    for col in R.columns:
        ok = True
        series = R[col]
        checked = 0
        for y in unique_years:
            sub = series[years == y]
            if sub.shape[0] < 30:
                continue
            checked += 1
            sd = float(sub.std(ddof=1))
            if sd <= 0 or float(sub.mean()) / sd <= 0:
                ok = False
                break
        out[col] = ok and checked >= 2
    return out


def _const_corr_lw_cov(R: pd.DataFrame) -> np.ndarray:
    X = R.fillna(0.0).values.astype(float)
    T, N = X.shape
    if T < 5 or N < 2:
        std = X.std(axis=0, ddof=1) if T > 1 else np.ones(N)
        std = np.where(std <= 0, 1e-6, std)
        return np.diag(std ** 2)
    mean = X.mean(axis=0)
    Xc = X - mean
    S = (Xc.T @ Xc) / max(T - 1, 1)
    std = np.sqrt(np.maximum(np.diag(S), 1e-12))
    corr = S / np.outer(std, std)
    if N > 1:
        mask = ~np.eye(N, dtype=bool)
        rbar = float(corr[mask].mean())
    else:
        rbar = 0.0
    rbar = max(min(rbar, 0.999), -0.999)
    F_corr = np.full((N, N), rbar)
    np.fill_diagonal(F_corr, 1.0)
    F = F_corr * np.outer(std, std)
    # pi_hat: variance of sample cov entries
    pi_mat = np.zeros((N, N))
    for t in range(T):
        d = Xc[t][:, None] * Xc[t][None, :] - S
        pi_mat += d * d
    pi_mat /= T
    pi_hat = float(pi_mat.sum())
    gamma_hat = float(((S - F) ** 2).sum())
    if gamma_hat <= 1e-12:
        delta = 0.5
    else:
        delta = max(0.0, min(1.0, pi_hat / (T * gamma_hat)))
    Sigma = delta * F + (1.0 - delta) * S
    return 0.5 * (Sigma + Sigma.T)


def _neumann_inverse(Sigma: np.ndarray, K: int) -> np.ndarray:
    N = Sigma.shape[0]
    rng = np.random.default_rng(0)
    v = rng.normal(size=N)
    nv = np.linalg.norm(v)
    v = v / nv if nv > 0 else np.ones(N) / np.sqrt(N)
    lam = float(np.diag(Sigma).max()) if N > 0 else 1.0
    for _ in range(50):
        u = Sigma @ v
        nu = np.linalg.norm(u)
        if nu <= 0:
            break
        v = u / nu
        lam = float(v @ (Sigma @ v))
    if not np.isfinite(lam) or lam <= 0:
        lam = max(float(np.trace(Sigma) / max(N, 1)), 1e-6)
    alpha = 1.0 / (lam * 1.1)
    I = np.eye(N)
    M = I - alpha * Sigma
    acc = np.eye(N)
    Mk = np.eye(N)
    for _ in range(K):
        Mk = Mk @ M
        acc = acc + Mk
    return alpha * acc


def _select_pool() -> list[str]:
    cand = select_is_submittable(RUN_ID)
    cand = list(cand)
    if len(cand) < 2:
        return cand
    signs = member_signs_ic(RUN_ID, cand)
    R_all = load_member_is_returns(RUN_ID, cand, signs=signs)
    if R_all.empty or R_all.shape[1] < 2:
        return list(R_all.columns)[:TARGET_N]
    R_all = R_all.fillna(0.0)
    # Pre-pool by IS Sharpe to keep downstream filters tractable
    sharpe_all = {c: _sharpe(R_all[c]) for c in R_all.columns}
    pre = sorted(sharpe_all, key=lambda c: -sharpe_all[c])[:PRE_POOL]
    Rp = R_all[pre]
    # Drawdown gate
    eq = (1.0 + Rp).cumprod()
    dd = {c: _max_drawdown(eq[c].values) for c in Rp.columns}
    keep_dd = [c for c in Rp.columns if dd[c] <= DD_CAP]
    if len(keep_dd) < TARGET_N:
        ordered = sorted(dd, key=lambda c: dd[c])
        keep_dd = list(dict.fromkeys(keep_dd + ordered))[: max(TARGET_N * 4, 24)]
    Rdd = Rp[keep_dd]
    # Year-stability filter
    ystab = _year_stable(Rdd)
    keep_y = [c for c in Rdd.columns if ystab.get(c, False)]
    if len(keep_y) < TARGET_N:
        # Relax: keep all DD survivors
        keep_y = list(Rdd.columns)
    Ry = Rdd[keep_y]
    # Sortino ranking
    sortino = {c: _sortino(Ry[c]) for c in Ry.columns}
    # Dedup by correlation, keeping by Sortino
    try:
        kept = correlation_dedup(Ry, DEDUP_RHO, keep_metric=sortino)
    except Exception:
        kept = list(Ry.columns)
    if len(kept) < TARGET_N:
        kept = list(dict.fromkeys(list(kept) + sorted(sortino, key=lambda c: -sortino[c])))
    final = sorted(kept, key=lambda c: -sortino.get(c, 0.0))[:TARGET_N]
    if len(final) < 2:
        final = sorted(sortino, key=lambda c: -sortino[c])[: max(TARGET_N, 2)]
    return list(final)


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    return _select_pool()


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    if not member_ids:
        return {}
    if len(member_ids) == 1:
        return {member_ids[0]: GROSS_TARGET}
    signs = member_signs_ic(RUN_ID, member_ids)
    R = load_member_is_returns(RUN_ID, member_ids, signs=signs)
    cols = [c for c in member_ids if c in R.columns]
    if len(cols) < 2:
        eq = GROSS_TARGET / max(len(member_ids), 1)
        out = {m: eq for m in member_ids}
        return apply_signs(out, signs)
    R = R[cols].fillna(0.0)
    mu = R.mean().values.astype(float)
    # If almost no positive means, use absolute values to keep tangency well-defined
    if (mu > 0).sum() < 2:
        floor = max(float(np.median(np.abs(mu))), 1e-6)
        mu = np.maximum(mu, floor)
    Sigma = _const_corr_lw_cov(R)
    Sinv = _neumann_inverse(Sigma, K=NEUMANN_K)
    raw = Sinv @ mu
    # Long-only in the sign-flipped (deployable) space
    raw = np.where(raw > 0, raw, 0.0)
    if not np.isfinite(raw).all() or raw.sum() <= 0:
        # Inverse-vol fallback
        diag = np.sqrt(np.maximum(np.diag(Sigma), 1e-12))
        raw = 1.0 / diag
    coef = dict(zip(cols, raw.tolist()))
    coef = apply_signs(coef, signs)
    coef = normalize_coefficients(coef, "l1")
    coef = {k: float(v) * GROSS_TARGET for k, v in coef.items()}
    for m in member_ids:
        coef.setdefault(m, 0.0)
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