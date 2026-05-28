"""Gerber-statistic robust covariance + Neumann-series MinVol-suppressed tangency on year-stable, drawdown-disciplined top-K alphas.

Cites: Gerber, Markowitz, Pujara (2022) 'The Gerber Statistic: A Robust Co-Movement Measure for Portfolio Optimization' (Journal of Portfolio Management) — count-based correlation insensitive to outliers in heavy-tailed return distributions. Cites: Neumann-series inverse Sigma^-1 ~ alpha * sum_{k=0}^K (I - alpha*Sigma)^k with alpha = 0.9 / lambda_max(Sigma) (power iteration), truncated at K=5 to suppress high-noise eigenmodes — the user's explicit MinVol-divergence-suppression hint.
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
    apply_signs,
    select_is_submittable,
    select_all_alphas,
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_043_gerber_robust_cov_neumann_k5_tangency_ye"
COMPOSITION_NOTE = "gerber_robust_cov_neumann_k5_tangency_yearstable_dd20_top6"

RUN_ID = "run_2026_05_c"
K_MEMBERS = 6
DD_THRESHOLD = 0.20
DEDUP_RHO = 0.82
NEUMANN_K = 5
GERBER_H = 0.5
TARGET_GROSS_L1 = 0.70


def _max_drawdown(equity: np.ndarray) -> float:
    if equity.size == 0:
        return 1.0
    peaks = np.maximum.accumulate(equity)
    safe = np.where(peaks > 0, peaks, 1.0)
    dd = (peaks - equity) / safe
    return float(np.nanmax(dd))


def _per_year_sharpe(r: pd.Series) -> dict:
    out: dict = {}
    for yr, grp in r.groupby(r.index.year):
        if len(grp) < 30:
            continue
        sd = grp.std()
        out[int(yr)] = float(grp.mean() / sd * math.sqrt(252)) if sd > 0 else 0.0
    return out


def _year_stable(r: pd.Series, min_years: int = 2) -> bool:
    yr_sh = _per_year_sharpe(r)
    if len(yr_sh) < min_years:
        return False
    return all(v > 0.0 for v in yr_sh.values())


def _dd_ok(r: pd.Series, threshold: float) -> bool:
    eq = (1.0 + r.fillna(0.0)).cumprod().values
    return _max_drawdown(eq) < threshold


def _gerber_cov(R: pd.DataFrame, H: float = 0.5) -> np.ndarray:
    X = R.fillna(0.0).values
    sds = X.std(axis=0)
    sds = np.where(sds > 0, sds, 1e-9)
    thr = H * sds
    pos = (X > thr).astype(np.int16)
    neg = (X < -thr).astype(np.int16)
    n_uu = pos.T @ pos
    n_dd = neg.T @ neg
    n_ud = pos.T @ neg
    n_du = neg.T @ pos
    num = n_uu + n_dd - n_ud - n_du
    den = n_uu + n_dd + n_ud + n_du
    den_safe = np.where(den > 0, den, 1)
    G = np.where(den > 0, num / den_safe, 0.0).astype(float)
    np.fill_diagonal(G, 1.0)
    w, V = sla.eigh(G)
    w = np.clip(w, 1e-6, None)
    G_psd = (V * w) @ V.T
    d = np.sqrt(np.maximum(np.diag(G_psd), 1e-9))
    G_psd = G_psd / d[:, None] / d[None, :]
    np.fill_diagonal(G_psd, 1.0)
    D = np.diag(sds)
    S = D @ G_psd @ D
    S = 0.5 * (S + S.T)
    return S


def _spectral_radius(S: np.ndarray, iters: int = 40) -> float:
    n = S.shape[0]
    rng = np.random.default_rng(0)
    v = rng.standard_normal(n)
    v /= np.linalg.norm(v) + 1e-12
    lam = float(np.trace(S) / max(n, 1))
    for _ in range(iters):
        u = S @ v
        nrm = np.linalg.norm(u)
        if nrm < 1e-15:
            break
        v = u / nrm
        lam = float(v @ (S @ v))
    return max(lam, 1e-9)


def _neumann_inverse(S: np.ndarray, K: int = 5) -> np.ndarray:
    n = S.shape[0]
    lam_max = _spectral_radius(S)
    alpha = 0.9 / lam_max
    I = np.eye(n)
    M = I - alpha * S
    acc = np.zeros_like(S)
    term = I.copy()
    for _ in range(K + 1):
        acc = acc + term
        term = term @ M
    return alpha * acc


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    candidates = select_is_submittable(RUN_ID)
    if len(candidates) < 4:
        candidates = select_all_alphas(RUN_ID)
    if len(candidates) < 2:
        return list(candidates)
    signs = member_signs_ic(RUN_ID, candidates)
    R_full = load_member_is_returns(RUN_ID, candidates, signs=signs)
    if R_full.empty or R_full.shape[1] < 2:
        return list(R_full.columns[:K_MEMBERS]) if not R_full.empty else list(candidates[:K_MEMBERS])
    kept: list[str] = []
    sharpe_map: dict = {}
    for col in R_full.columns:
        r = R_full[col].dropna()
        if len(r) < 60:
            continue
        if not _year_stable(r, min_years=2):
            continue
        if not _dd_ok(r, DD_THRESHOLD):
            continue
        sd = r.std()
        sh = float(r.mean() / sd * math.sqrt(252)) if sd > 0 else 0.0
        if sh <= 0:
            continue
        sharpe_map[col] = sh
        kept.append(col)
    if len(kept) < max(4, K_MEMBERS):
        sds = R_full.std()
        means = R_full.mean()
        sh_all = (means / sds.replace(0, np.nan)) * math.sqrt(252)
        sh_all = sh_all.dropna()
        sharpe_map = {k: float(v) for k, v in sh_all.items()}
        kept = sorted(sharpe_map, key=lambda x: -sharpe_map[x])[: max(20, K_MEMBERS * 3)]
    if len(kept) < 2:
        return kept
    R_kept = R_full[kept]
    try:
        deduped = correlation_dedup(R_kept, threshold=DEDUP_RHO, keep_metric=sharpe_map)
    except Exception:
        deduped = kept
    if not deduped:
        deduped = kept
    deduped_sorted = sorted(deduped, key=lambda x: -sharpe_map.get(x, 0.0))
    chosen = deduped_sorted[:K_MEMBERS]
    if len(chosen) < 2:
        extras = [a for a in deduped_sorted if a not in chosen]
        chosen = (chosen + extras)[:max(2, K_MEMBERS)]
    return chosen


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    if not member_ids:
        return {}
    signs = member_signs_ic(RUN_ID, member_ids)
    R = load_member_is_returns(RUN_ID, member_ids, signs=signs)
    ids = list(R.columns)
    if len(ids) < 2:
        eq = {a: 1.0 / max(len(member_ids), 1) for a in member_ids}
        eq = normalize_coefficients(eq, "l1")
        eq = {k: float(v) * TARGET_GROSS_L1 for k, v in eq.items()}
        return apply_signs(eq, signs)

    R_clean = R.fillna(0.0)
    S = _gerber_cov(R_clean, H=GERBER_H)
    tikh = 1e-4 * max(float(np.trace(S)) / S.shape[0], 1e-9)
    S = S + tikh * np.eye(S.shape[0])

    try:
        S_inv = _neumann_inverse(S, K=NEUMANN_K)
    except Exception:
        S_inv = sla.pinvh(S)

    sds = R_clean.std().values
    sds_safe = np.where(sds > 0, sds, 1e-9)
    sharpes = R_clean.mean().values / sds_safe * math.sqrt(252)
    mu = np.clip(sharpes, 0.0, None)
    if mu.sum() <= 1e-9:
        mu = np.ones_like(mu)

    w = S_inv @ mu
    if not np.isfinite(w).all():
        w = mu.copy()
    w = np.clip(w, 0.0, None)
    if w.sum() <= 1e-9:
        w = np.ones_like(w)

    c_arr = w / w.sum()
    coef = {a: float(v) for a, v in zip(ids, c_arr.tolist())}
    coef = normalize_coefficients(coef, "l1")
    coef = {k: float(v) * TARGET_GROSS_L1 for k, v in coef.items()}

    for a in member_ids:
        coef.setdefault(a, 0.0)

    coef = apply_signs(coef, signs)

    for a in member_ids:
        coef.setdefault(a, 0.0)
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