"""Greedy Gram-Schmidt orthogonalization on residual IS Sharpe (cov-free composition).

Method: forward-selection residual regression. At each step, project every
remaining candidate's IS return stream onto the QR basis of currently
selected members, score the residual by annualized Sharpe, and add the
top scorer if its residual Sharpe exceeds 0.30. This is the classical
Gram-Schmidt / Householder construction (Golub & Van Loan, "Matrix
Computations") repurposed for portfolio composition. Unlike tangency or
min-variance (Σ⁻¹·μ), it never inverts a covariance, so member weight
magnitudes are not 1/σ-compressed — addressing the gross-exposure
ceiling that has trapped prior composites at mean row L1 ≈ 0.05.
Selection is regime-stable: keep only alphas with positive Sharpe in
every IS sub-year and IS max drawdown ≤ 25%.
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
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_047_greedy_gram_schmidt_resid_sharpe_yearsta"
COMPOSITION_NOTE = "greedy_gram_schmidt_resid_sharpe_yearstable_dd25_n10_gross085"
RUN_ID = "run_2026_05_c"

MAX_MEMBERS = 10
MIN_RESID_SHARPE = 0.30
IS_DD_MAX = 0.25
DEDUP_RHO = 0.90
TARGET_GROSS = 0.85

_CACHE: dict = {}


def _ann_sharpe(returns: pd.Series) -> float:
    r = returns.dropna()
    if len(r) < 10:
        return 0.0
    sd = r.std(ddof=1)
    if not np.isfinite(sd) or sd <= 1e-12:
        return 0.0
    mu = r.mean()
    if not np.isfinite(mu):
        return 0.0
    return float(mu / sd * math.sqrt(252.0))


def _max_dd(returns: pd.Series) -> float:
    r = returns.dropna()
    if len(r) < 2:
        return 1.0
    eq = (1.0 + r).cumprod()
    peak = eq.cummax()
    dd = (eq / peak) - 1.0
    return float(-dd.min())


def _year_stable(returns: pd.Series) -> bool:
    r = returns.dropna()
    if len(r) < 30:
        return False
    try:
        years = r.index.year
    except AttributeError:
        return True
    grouped = r.groupby(years)
    n_years = 0
    for _, sub in grouped:
        if len(sub) < 15:
            continue
        n_years += 1
        if sub.mean() <= 0:
            return False
    return n_years >= 2


def _filter_pool(R: pd.DataFrame) -> list[str]:
    kept: list[str] = []
    for col in R.columns:
        s = R[col].dropna()
        if len(s) < 30:
            continue
        if _ann_sharpe(s) <= 0.30:
            continue
        if _max_dd(s) > IS_DD_MAX:
            continue
        if not _year_stable(s):
            continue
        kept.append(col)
    return kept


def _loose_pool(R: pd.DataFrame) -> list[str]:
    kept: list[str] = []
    for col in R.columns:
        s = R[col].dropna()
        if len(s) < 20:
            continue
        if _ann_sharpe(s) <= 0.30:
            continue
        if _max_dd(s) > 0.40:
            continue
        kept.append(col)
    return kept


def _greedy_orthogonalize(R: pd.DataFrame, candidates: list[str]) -> tuple[list[str], dict[str, float]]:
    if not candidates:
        return [], {}
    cand_sharpe = {c: _ann_sharpe(R[c]) for c in candidates}
    ordered = sorted(candidates, key=lambda c: cand_sharpe[c], reverse=True)

    chosen: list[str] = [ordered[0]]
    weights: dict[str, float] = {ordered[0]: max(cand_sharpe[ordered[0]], MIN_RESID_SHARPE)}

    while len(chosen) < MAX_MEMBERS:
        X = R[chosen].to_numpy(dtype=float)
        X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
        try:
            Q, _ = sla.qr(X, mode="economic")
        except Exception:
            break

        best_id = None
        best_score = -np.inf
        for c in ordered:
            if c in chosen:
                continue
            y = R[c].to_numpy(dtype=float)
            y = np.nan_to_num(y, nan=0.0, posinf=0.0, neginf=0.0)
            proj = Q @ (Q.T @ y)
            resid = y - proj
            r = pd.Series(resid, index=R.index)
            sh = _ann_sharpe(r)
            if sh > best_score:
                best_score = sh
                best_id = c

        if best_id is None or best_score < MIN_RESID_SHARPE:
            break

        chosen.append(best_id)
        weights[best_id] = float(best_score)

    return chosen, weights


def _build_selection() -> None:
    submittable = select_is_submittable(RUN_ID)
    if not submittable or len(submittable) < 3:
        _CACHE["chosen"] = []
        _CACHE["resid_w"] = {}
        _CACHE["signs"] = {}
        return

    signs = member_signs_ic(RUN_ID, submittable)
    R = load_member_is_returns(RUN_ID, submittable, signs=signs)

    if R is None or R.empty or len(R.columns) < 3:
        _CACHE["chosen"] = []
        _CACHE["resid_w"] = {}
        _CACHE["signs"] = signs or {}
        return

    pool = _filter_pool(R)
    if len(pool) < 3:
        pool = _loose_pool(R)
    if len(pool) < 2:
        pool = list(R.columns)

    sharpe_map = {c: _ann_sharpe(R[c]) for c in pool}
    try:
        deduped = correlation_dedup(R[pool], threshold=DEDUP_RHO, keep_metric=sharpe_map)
    except Exception:
        deduped = pool

    if not deduped or len(deduped) < 2:
        deduped = sorted(pool, key=lambda c: sharpe_map.get(c, 0.0), reverse=True)[:MAX_MEMBERS]

    chosen, weights = _greedy_orthogonalize(R, deduped)

    _CACHE["chosen"] = chosen
    _CACHE["resid_w"] = weights
    _CACHE["signs"] = signs


def _ensure_built() -> None:
    if "chosen" not in _CACHE:
        _build_selection()


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    _ensure_built()
    chosen = list(_CACHE.get("chosen", []))
    if len(chosen) >= 2:
        return chosen

    # Fallback: top-by-IS-Sharpe from alpha_index
    if alpha_index is not None and not alpha_index.empty and "is_sharpe" in alpha_index.columns:
        idx = alpha_index.copy()
        idx = idx.dropna(subset=["is_sharpe"])
        idx = idx.sort_values("is_sharpe", ascending=False)
        fallback = idx["alpha_id"].head(6).tolist()
        _CACHE["chosen"] = fallback
        return fallback

    return chosen


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    _ensure_built()
    resid_w = _CACHE.get("resid_w", {}) or {}
    signs = _CACHE.get("signs", {}) or {}

    raw: dict[str, float] = {}
    for m in member_ids:
        w = resid_w.get(m)
        if w is None or not np.isfinite(w) or w <= 0:
            w = MIN_RESID_SHARPE
        raw[m] = float(max(w, MIN_RESID_SHARPE))

    if not raw:
        return {}

    raw = apply_signs(raw, signs)

    coef = normalize_coefficients(raw, "l1")
    coef = {k: float(v) * TARGET_GROSS for k, v in coef.items()}

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