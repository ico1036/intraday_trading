"""
Eigenvalue-clipped Tikhonov tangency on year-stable, low-drawdown
concentrated members with Sharpe-tilt mixing.

Method: Tikhonov-regularized covariance inverse via explicit condition
number cap (Tikhonov & Arsenin 1977) — eigenvalues clipped to
[lambda_max/kappa, lambda_max] before inversion, directly bounding
cond(Sigma_inv). Selection uses per-year IS Sharpe stability
(Lopez de Prado 2018, regime-conditional robustness) plus a max-drawdown
ceiling. Combination = (1 - alpha) * tangency (Markowitz 1952 /
Britten-Jones 1999 closed-form) + alpha * Sharpe-proportional weights
(convex shrinkage toward a robust prior, mitigating small-sample
tangency fragility). Sign-aligned to IC sign before optimization;
coefficients re-scaled to target mean row-L1 of ~0.7.
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
    select_all_alphas,
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_045_tikhonov_tangency_yearstable_dd20_top8_s"
COMPOSITION_NOTE = "tikhonov_tangency_yearstable_dd20_top8_sharpemix_l1_07"

RUN_ID = "run_2026_05_c"
TOP_K = 8
DD_MAX = 0.20
DEDUP_RHO = 0.82
KAPPA = 20.0
SHARPE_MIX = 0.30
TARGET_L1 = 0.70
MIN_YEAR_OBS = 20


def _ensure_dt_index(R: pd.DataFrame) -> pd.DataFrame:
    if isinstance(R.index, pd.DatetimeIndex):
        return R
    idx = pd.to_datetime(R.index, errors="coerce")
    R2 = R.copy()
    R2.index = idx
    return R2[~R2.index.isna()]


def _year_stable_cols(R: pd.DataFrame) -> list[str]:
    R = _ensure_dt_index(R)
    if R.empty:
        return []
    years = R.index.year
    uniq = np.unique(years)
    keep = []
    for col in R.columns:
        ok = True
        for y in uniq:
            sub = R.loc[years == y, col].dropna()
            if len(sub) < MIN_YEAR_OBS:
                ok = False
                break
            sd = float(sub.std(ddof=1))
            if not np.isfinite(sd) or sd <= 0:
                ok = False
                break
            if float(sub.mean()) / sd <= 0:
                ok = False
                break
        if ok:
            keep.append(col)
    return keep


def _max_drawdown(series: pd.Series) -> float:
    s = series.dropna()
    if s.empty:
        return 1.0
    eq = (1.0 + s).cumprod()
    peak = eq.cummax()
    dd = eq / peak - 1.0
    return float(-dd.min())


def _safe_sharpes(R: pd.DataFrame) -> pd.Series:
    mu = R.mean()
    sd = R.std(ddof=1)
    sd = sd.where(sd > 1e-12, np.nan)
    return (mu / sd).dropna()


def _filter_pool(R: pd.DataFrame) -> list[str]:
    if R.empty or R.shape[1] < 2:
        return list(R.columns)
    stable = _year_stable_cols(R)
    if len(stable) < 4:
        sh = _safe_sharpes(R)
        stable = sh[sh > 0].sort_values(ascending=False).index.tolist()
        if len(stable) < 4:
            stable = list(R.columns)
    R2 = R[stable]
    dd_ok = [c for c in R2.columns if _max_drawdown(R2[c]) < DD_MAX]
    if len(dd_ok) < 4:
        dd_pairs = [(c, _max_drawdown(R2[c])) for c in R2.columns]
        dd_pairs.sort(key=lambda x: x[1])
        dd_ok = [c for c, _ in dd_pairs[: max(8, min(len(R2.columns), 16))]]
    R3 = R2[dd_ok]
    sh = _safe_sharpes(R3)
    sh = sh[sh > 0].sort_values(ascending=False)
    if sh.empty:
        return list(R3.columns)[:TOP_K]
    cand = sh.head(min(3 * TOP_K, len(sh))).index.tolist()
    metric = {c: float(sh[c]) for c in cand}
    try:
        deduped = correlation_dedup(R3[cand], DEDUP_RHO, keep_metric=metric)
    except Exception:
        deduped = cand
    if not deduped:
        deduped = cand
    deduped = sorted(deduped, key=lambda c: -metric.get(c, 0.0))
    return deduped[:TOP_K]


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    try:
        ids = select_all_alphas(RUN_ID)
        if not ids:
            return []
        signs = member_signs_ic(RUN_ID, ids)
        R = load_member_is_returns(RUN_ID, ids, signs=signs)
        chosen = _filter_pool(R)
        if len(chosen) < 2 and not R.empty:
            sh = _safe_sharpes(R).sort_values(ascending=False)
            chosen = sh.head(TOP_K).index.tolist()
        return chosen
    except Exception:
        if isinstance(alpha_index, pd.DataFrame) and "is_sharpe" in alpha_index.columns:
            return (
                alpha_index.sort_values("is_sharpe", ascending=False)["alpha_id"]
                .head(TOP_K)
                .tolist()
            )
        return []


def _tikhonov_clipped_inv(Sigma: np.ndarray, kappa: float) -> np.ndarray:
    S = 0.5 * (Sigma + Sigma.T)
    w, V = sla.eigh(S)
    lam_max = float(w.max())
    if not np.isfinite(lam_max) or lam_max <= 0:
        n = S.shape[0]
        return np.eye(n)
    lam_floor = lam_max / kappa
    w_clip = np.clip(w, lam_floor, lam_max)
    return (V * (1.0 / w_clip)) @ V.T


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    n_in = max(len(member_ids), 1)
    try:
        if len(member_ids) < 2:
            return {m: TARGET_L1 / n_in for m in member_ids}
        signs = member_signs_ic(RUN_ID, member_ids)
        for m in member_ids:
            signs.setdefault(m, 1)
        R = load_member_is_returns(RUN_ID, member_ids, signs=signs)
        if R.empty:
            return {m: TARGET_L1 / n_in for m in member_ids}
        cols = [c for c in member_ids if c in R.columns]
        if len(cols) < 2:
            return {m: TARGET_L1 / n_in for m in member_ids}
        R = R[cols].fillna(0.0)
        if R.shape[0] < 30:
            base = {c: 1.0 / len(cols) for c in cols}
            base = apply_signs(base, signs)
            base = normalize_coefficients(base, "l1")
            out = {k: v * TARGET_L1 for k, v in base.items()}
            for m in member_ids:
                out.setdefault(m, 0.0)
            return out
        X = R.values
        mu = X.mean(axis=0)
        Xc = X - mu[None, :]
        T = X.shape[0]
        Sigma = (Xc.T @ Xc) / max(T - 1, 1)
        Sinv = _tikhonov_clipped_inv(Sigma, KAPPA)
        w_tan = Sinv @ mu
        if not np.all(np.isfinite(w_tan)):
            w_tan = np.zeros_like(mu)
        sd = X.std(axis=0, ddof=1)
        sd = np.where(sd > 1e-12, sd, 1e-12)
        sh = np.maximum(mu / sd, 0.0)
        if sh.sum() <= 0:
            sh = np.ones_like(sh)
        w_sh = sh / sh.sum()
        tan_abs = float(np.sum(np.abs(w_tan)))
        if tan_abs <= 1e-12:
            w_tan = w_sh.copy()
            tan_abs = float(np.sum(np.abs(w_tan)))
        w_tan = w_tan / max(tan_abs, 1e-12)
        w_sh = w_sh / max(float(np.sum(np.abs(w_sh))), 1e-12)
        w_mix = (1.0 - SHARPE_MIX) * w_tan + SHARPE_MIX * w_sh
        coef = {c: float(v) for c, v in zip(cols, w_mix.tolist())}
        coef = apply_signs(coef, signs)
        coef = normalize_coefficients(coef, "l1")
        coef = {k: float(v) * TARGET_L1 for k, v in coef.items()}
        for m in member_ids:
            coef.setdefault(m, 0.0)
        return coef
    except Exception:
        return {m: TARGET_L1 / n_in for m in member_ids}


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