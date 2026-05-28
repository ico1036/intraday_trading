"""Concentrated tangency on year-stable, drawdown-disciplined top-6 alphas
with truncated Neumann-series covariance inverse (eigenvalue-divergence
suppression, K=3). References: Neumann (1937) matrix inversion series;
Lopez de Prado (2019, MLfAM) low-rank denoising rationale; Grinold-Kahn
IC sign alignment; Markowitz tangency direction w = Sigma^{-1} mu."""
from __future__ import annotations
import argparse
import math
import functools
import numpy as np
import pandas as pd

from intraday.composites._runner import build_and_backtest
from intraday.composites._optim_helpers import (
    correlation_dedup,
    member_signs_ic,
    select_is_submittable,
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_041_neumann_k3_tangency_top6_yearstable_dd22"
COMPOSITION_NOTE = "neumann_k3_tangency_top6_yearstable_dd22_dedup085_concentrated"

RUN_ID = "run_2026_05_c"
TARGET_K = 6
DD_MAX = 0.22
DEDUP_RHO = 0.85
NEUMANN_K = 3
NEUMANN_SAFETY = 0.9
GROSS_TARGET = 0.7
MIN_OBS = 60


def _max_drawdown(returns: pd.Series) -> float:
    s = returns.dropna()
    if len(s) < 5:
        return 1.0
    equity = (1.0 + s).cumprod()
    cummax = equity.cummax().replace(0, np.nan)
    dd = (equity - cummax) / cummax
    mn = dd.min()
    if not np.isfinite(mn):
        return 1.0
    return float(-mn)


def _year_stable(r: pd.Series) -> bool:
    s = r.dropna()
    if len(s) < MIN_OBS:
        return False
    idx = s.index
    if not isinstance(idx, pd.DatetimeIndex):
        try:
            idx = pd.to_datetime(idx)
            s = pd.Series(s.values, index=idx)
        except Exception:
            # if no datetime info, fall through to overall sharpe positivity
            mu = s.mean()
            sd = s.std(ddof=1)
            return bool(sd > 0 and np.isfinite(sd) and mu > 0)
    groups = s.groupby(s.index.year)
    saw_any = False
    for _, sub in groups:
        if len(sub) < 20:
            continue
        mu = sub.mean()
        sd = sub.std(ddof=1)
        if not np.isfinite(sd) or sd <= 0:
            return False
        sh = (mu / sd) * math.sqrt(252.0)
        if sh <= 0.0:
            return False
        saw_any = True
    return saw_any


def _power_iter_lambda_max(M: np.ndarray, iters: int = 60) -> float:
    n = M.shape[0]
    rng = np.random.default_rng(7)
    x = rng.standard_normal(n)
    nx = np.linalg.norm(x)
    if nx < 1e-18:
        return float(np.trace(M) / max(n, 1))
    x = x / nx
    lam = 0.0
    for _ in range(iters):
        y = M @ x
        ny = np.linalg.norm(y)
        if ny < 1e-18:
            break
        x = y / ny
        lam = float(x @ (M @ x))
    if not np.isfinite(lam) or lam <= 0:
        lam = float(np.trace(M) / max(n, 1))
    return max(lam, 1e-12)


def _neumann_inverse(Sigma: np.ndarray, K: int = NEUMANN_K, safety: float = NEUMANN_SAFETY) -> np.ndarray:
    n = Sigma.shape[0]
    lam_max = _power_iter_lambda_max(Sigma)
    alpha = safety / lam_max
    I = np.eye(n)
    M = I - alpha * Sigma
    acc = np.zeros_like(Sigma)
    term = I.copy()
    for _ in range(K + 1):
        acc = acc + term
        term = term @ M
    return alpha * acc


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    ids = select_is_submittable(RUN_ID)
    if not ids:
        ids = []
    if len(ids) < 2:
        return ids
    signs = member_signs_ic(RUN_ID, ids)
    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    if R is None or R.empty or len(R.columns) < 2:
        return ids[:TARGET_K]
    cols = list(R.columns)
    metric: dict[str, float] = {}
    strict: list[str] = []
    relaxed: list[str] = []
    for c in cols:
        s = R[c].dropna()
        if len(s) < MIN_OBS:
            continue
        mu = s.mean()
        sd = s.std(ddof=1)
        if not np.isfinite(sd) or sd <= 0:
            continue
        sharpe = (mu / sd) * math.sqrt(252.0)
        if sharpe <= 0:
            continue
        metric[c] = float(sharpe)
        dd = _max_drawdown(s)
        if dd > DD_MAX:
            continue
        relaxed.append(c)
        if _year_stable(s):
            strict.append(c)
    pool = strict if len(strict) >= 2 else (relaxed if len(relaxed) >= 2 else list(metric.keys()))
    if len(pool) < 2:
        return cols[:TARGET_K]
    R_pool = R[pool]
    try:
        kept = correlation_dedup(R_pool, threshold=DEDUP_RHO, keep_metric=metric)
    except Exception:
        kept = pool
    if not kept:
        kept = pool
    kept_sorted = sorted(kept, key=lambda x: metric.get(x, 0.0), reverse=True)
    chosen = kept_sorted[:TARGET_K]
    if len(chosen) < 2:
        chosen = sorted(pool, key=lambda x: metric.get(x, 0.0), reverse=True)[:TARGET_K]
    return chosen


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    if not member_ids:
        return {}
    if len(member_ids) == 1:
        only = {member_ids[0]: 1.0}
        only = normalize_coefficients(only, "l1")
        return {k: v * GROSS_TARGET for k, v in only.items()}

    signs = member_signs_ic(RUN_ID, member_ids)
    R = load_member_is_returns(RUN_ID, member_ids, signs=signs)

    def _equal_fallback() -> dict[str, float]:
        eq = {m: 1.0 / len(member_ids) for m in member_ids}
        eq = normalize_coefficients(eq, "l1")
        return {m: eq.get(m, 0.0) * GROSS_TARGET for m in member_ids}

    if R is None or R.empty or len(R.columns) < 2:
        return _equal_fallback()

    cols = list(R.columns)
    X_df = R[cols].dropna(how="any")
    if X_df.shape[0] < max(40, 3 * X_df.shape[1]):
        # not enough joint observations for a stable cov — inverse-vol fallback
        sd_full = R[cols].std(ddof=1)
        invvol = {}
        for c in cols:
            v = sd_full.get(c, np.nan)
            invvol[c] = float(1.0 / v) if np.isfinite(v) and v > 0 else 0.0
        if sum(abs(v) for v in invvol.values()) <= 0:
            return _equal_fallback()
        ivn = normalize_coefficients(invvol, "l1")
        out = {m: ivn.get(m, 0.0) * GROSS_TARGET for m in member_ids}
        return out

    X = X_df.values
    mu = X.mean(axis=0)
    Sigma = np.cov(X, rowvar=False, ddof=1)
    n = Sigma.shape[0]
    diag = np.diag(Sigma)
    med_diag = float(np.median(diag)) if np.all(np.isfinite(diag)) and len(diag) else 1e-8
    floor = max(med_diag * 1e-4, 1e-12)
    Sigma = Sigma + np.eye(n) * floor

    try:
        Sinv = _neumann_inverse(Sigma, K=NEUMANN_K, safety=NEUMANN_SAFETY)
        w = Sinv @ mu
        if not np.all(np.isfinite(w)) or np.allclose(w, 0.0):
            raise ValueError("degenerate neumann tangency")
    except Exception:
        try:
            import scipy.linalg as sla
            Sinv = sla.pinvh(Sigma)
            w = Sinv @ mu
            if not np.all(np.isfinite(w)) or np.allclose(w, 0.0):
                raise ValueError("degenerate pinv tangency")
        except Exception:
            # final fallback: inverse-vol on the joint-observation slice
            sd = X_df.std(ddof=1).replace(0, np.nan)
            w = (1.0 / sd).fillna(0.0).values

    # signs already baked into R via member_signs_ic; keep raw direction of w
    raw = {cols[i]: float(w[i]) for i in range(len(cols))}
    if sum(abs(v) for v in raw.values()) <= 0:
        return _equal_fallback()
    norm = normalize_coefficients(raw, "l1")
    out = {m: norm.get(m, 0.0) * GROSS_TARGET for m in member_ids}
    if sum(abs(v) for v in out.values()) <= 0:
        return _equal_fallback()
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