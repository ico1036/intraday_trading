"""Drawdown-disciplined regime-stable top-8 with Marchenko-Pastur denoised
Neumann-series tangency (Lopez de Prado 2019 MP eigenvalue clipping +
truncated Neumann inverse K=4 for divergence suppression on MinVol)."""
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
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_034_dd_disc_yearstable_top8_mp_denoise_neuma"
COMPOSITION_NOTE = "dd_disc_yearstable_top8_mp_denoise_neumann_tangency_k4"

RUN_ID = "run_2026_05_c"
TOP_K = 8
MAX_DD_LIMIT = 0.25
DEDUP_THRESHOLD = 0.85
NEUMANN_K = 4
TARGET_GROSS = 0.65


def _max_drawdown(returns: pd.Series) -> float:
    eq = (1.0 + returns.fillna(0.0)).cumprod()
    dd = eq / eq.cummax() - 1.0
    return float(-dd.min())


def _per_year_positive(R: pd.DataFrame) -> list[str]:
    idx = pd.to_datetime(R.index)
    years = sorted({int(d.year) for d in idx})
    if len(years) < 2:
        return list(R.columns)
    keep: list[str] = []
    for col in R.columns:
        s = R[col].values
        ok = True
        for y in years:
            mask = np.array([int(d.year) == y for d in idx])
            if mask.sum() < 20:
                continue
            chunk = s[mask]
            chunk = chunk[~np.isnan(chunk)]
            if chunk.size == 0 or float(chunk.mean()) <= 0.0:
                ok = False
                break
        if ok:
            keep.append(col)
    return keep


def _mp_denoise(cov: np.ndarray, T: int) -> np.ndarray:
    N = cov.shape[0]
    if N < 2 or T <= N + 1:
        return cov
    std = np.sqrt(np.clip(np.diag(cov), 1e-18, None))
    corr = cov / np.outer(std, std)
    corr = (corr + corr.T) / 2.0
    try:
        evals, evecs = sla.eigh(corr)
    except Exception:
        return cov
    q = float(T) / float(N)
    lam_plus = (1.0 + 1.0 / math.sqrt(q)) ** 2
    bulk = evals < lam_plus
    if bulk.any() and (~bulk).any():
        bulk_mean = float(evals[bulk].mean())
        evals = np.where(bulk, bulk_mean, evals)
    elif bulk.all():
        evals = np.full_like(evals, float(evals.mean()))
    corr_dn = (evecs * evals) @ evecs.T
    corr_dn = (corr_dn + corr_dn.T) / 2.0
    cov_dn = corr_dn * np.outer(std, std)
    return cov_dn


def _neumann_inverse(cov: np.ndarray, k: int) -> np.ndarray:
    N = cov.shape[0]
    rng = np.random.default_rng(0)
    v = rng.standard_normal(N)
    v /= (np.linalg.norm(v) + 1e-12)
    for _ in range(50):
        v = cov @ v
        nrm = np.linalg.norm(v) + 1e-12
        v = v / nrm
    lam_max = float(v @ cov @ v) + 1e-12
    alpha = 1.0 / lam_max
    I = np.eye(N)
    M = I - alpha * cov
    term = I.copy()
    acc = np.zeros_like(cov)
    for _ in range(k + 1):
        acc = acc + term
        term = term @ M
    return alpha * acc


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    ids = select_is_submittable(RUN_ID)
    if not ids or len(ids) < 2:
        if "alpha_id" in alpha_index.columns:
            ids = [str(a) for a in alpha_index["alpha_id"].tolist()]
    if len(ids) < 2:
        return ids
    signs = member_signs_ic(RUN_ID, ids)
    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    if R is None or R.shape[1] < 2:
        return list(R.columns) if R is not None else ids[:2]

    dd_survivors = [c for c in R.columns if _max_drawdown(R[c]) < MAX_DD_LIMIT]
    if len(dd_survivors) >= max(2, TOP_K // 2):
        R = R[dd_survivors]

    stable = _per_year_positive(R)
    if len(stable) >= max(2, TOP_K // 2):
        R = R[stable]

    mean_r = R.mean()
    std_r = R.std().replace(0.0, np.nan)
    sharpe = (mean_r / std_r * math.sqrt(252)).fillna(0.0)
    keep_metric = {str(k): float(v) for k, v in sharpe.to_dict().items()}

    try:
        kept = correlation_dedup(R, DEDUP_THRESHOLD, keep_metric=keep_metric)
    except Exception:
        kept = list(R.columns)
    if not kept or len(kept) < 2:
        kept = list(R.columns)

    ranked = sorted(kept, key=lambda a: -float(sharpe.get(a, 0.0)))
    chosen = ranked[:TOP_K]
    if len(chosen) < 2:
        chosen = ranked[:2] if len(ranked) >= 2 else ranked
    return chosen


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    n = len(member_ids)
    signs = member_signs_ic(RUN_ID, member_ids)
    sign_dict = {a: int(signs.get(a, 1)) for a in member_ids}

    R = load_member_is_returns(RUN_ID, member_ids, signs=signs)
    cols = [c for c in member_ids if (R is not None and c in R.columns)]
    if len(cols) < 2:
        base = {a: 1.0 / max(1, n) for a in member_ids}
        base = apply_signs(base, sign_dict)
        base = normalize_coefficients(base, "l1")
        return {a: float(v) * TARGET_GROSS for a, v in base.items()}

    M = R[cols].dropna(how="all").fillna(0.0)
    mu = M.mean().values.astype(float)
    cov = np.cov(M.values, rowvar=False).astype(float)
    cov = (cov + cov.T) / 2.0
    cov = cov + 1e-8 * np.eye(cov.shape[0])

    cov_dn = _mp_denoise(cov, T=int(M.shape[0]))
    try:
        inv_approx = _neumann_inverse(cov_dn, NEUMANN_K)
        w = inv_approx @ mu
        if not np.isfinite(w).all() or np.allclose(w, 0.0):
            raise ValueError("neumann produced degenerate w")
    except Exception:
        try:
            w = sla.pinvh(cov_dn) @ mu
        except Exception:
            w = mu.copy()
        if not np.isfinite(w).all() or np.allclose(w, 0.0):
            w = np.ones_like(mu)

    coef = {a: 0.0 for a in member_ids}
    for a, v in zip(cols, w):
        coef[a] = float(v)

    coef = apply_signs(coef, sign_dict)
    coef = normalize_coefficients(coef, "l1")
    return {a: float(v) * TARGET_GROSS for a, v in coef.items()}


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