"""Probabilistic Sharpe Ratio (Bailey & Lopez de Prado 2012) + year-stability + DD<=25% + Neumann-K4 tangency on top-6 alphas."""
from __future__ import annotations
import argparse
import math
import numpy as np
import pandas as pd

from intraday.composites._runner import build_and_backtest
from intraday.composites._optim_helpers import (
    correlation_dedup,
    member_signs_ic,
    apply_signs,
    select_all_alphas,
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_040_psr_yearstable_dd25_neumann_k4_tangency"
COMPOSITION_NOTE = "psr_yearstable_dd25_neumann_k4_tangency_top6"

RUN_ID = "run_2026_05_c"

# --------------------------------------------------------------------------- #
# Numerical primitives
# --------------------------------------------------------------------------- #

def _annual_sharpe(returns: np.ndarray) -> float:
    if returns.size < 5:
        return 0.0
    sd = float(returns.std(ddof=1))
    if sd < 1e-12:
        return 0.0
    return float(returns.mean() / sd * math.sqrt(252.0))


def _max_drawdown(returns: np.ndarray) -> float:
    """Standard equity-curve max-drawdown as a fraction of peak."""
    if returns.size == 0:
        return 1.0
    eq = np.cumprod(1.0 + returns)
    peak = np.maximum.accumulate(eq)
    dd = (peak - eq) / np.maximum(peak, 1e-12)
    return float(dd.max())


def _norm_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _psr(returns: np.ndarray, sr_benchmark_daily: float = 0.0) -> float:
    """Probabilistic Sharpe Ratio. Returns P(true SR > sr_benchmark) under
    the asymptotic distribution that accounts for skew + kurtosis."""
    n = returns.size
    if n < 20:
        return 0.0
    mu = float(returns.mean())
    sd = float(returns.std(ddof=1))
    if sd < 1e-12:
        return 0.0
    sr = mu / sd
    r = (returns - mu) / sd
    skew = float((r ** 3).mean())
    kurt = float((r ** 4).mean())  # raw 4th moment (= excess + 3 for normal)
    inside = 1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr * sr
    if inside <= 1e-9:
        return 0.0
    denom = math.sqrt(inside)
    z = (sr - sr_benchmark_daily) * math.sqrt(max(1, n - 1)) / denom
    return _norm_cdf(z)


def _year_stable(returns: pd.Series, min_years: int = 2) -> bool:
    idx = returns.index
    if not isinstance(idx, pd.DatetimeIndex):
        idx = pd.to_datetime(idx, errors="coerce")
    years = idx.year
    valid = ~pd.isna(years) if hasattr(years, "__iter__") else None
    s = pd.Series(returns.to_numpy(), index=years)
    s = s[s.index.notna()] if hasattr(s.index, "notna") else s
    by_year = s.groupby(level=0)
    sharpes = by_year.apply(lambda x: _annual_sharpe(np.asarray(x, dtype=float)))
    if len(sharpes) < min_years:
        return False
    return bool((sharpes > 0.0).all())


def _neumann_inverse(cov: np.ndarray, k: int = 4) -> np.ndarray:
    """Truncated Neumann series approximation of Sigma^{-1}.

    Sigma^{-1} ~ alpha * sum_{j=0..k} (I - alpha*Sigma)^j
    where alpha is chosen via power-iteration so that
    ||I - alpha*Sigma||_op < 1.
    """
    n = cov.shape[0]
    rng = np.random.default_rng(7)
    v = rng.standard_normal(n)
    nv = np.linalg.norm(v)
    if nv < 1e-12:
        return np.eye(n)
    v = v / nv
    lam_max = 1.0
    for _ in range(60):
        v = cov @ v
        nv = float(np.linalg.norm(v))
        if nv < 1e-12:
            break
        v = v / nv
        lam_max = float(v @ (cov @ v))
    if lam_max <= 1e-12:
        return np.eye(n)
    alpha = 1.0 / (1.5 * lam_max)
    M = np.eye(n) - alpha * cov
    acc = np.eye(n)
    Mp = np.eye(n)
    for _ in range(k):
        Mp = Mp @ M
        acc = acc + Mp
    return alpha * acc


# --------------------------------------------------------------------------- #
# Selection
# --------------------------------------------------------------------------- #

_CACHE: dict[str, tuple[list[str], pd.DataFrame, dict[str, int]]] = {}


def _build(run_id: str) -> tuple[list[str], pd.DataFrame, dict[str, int]]:
    ids_all = select_all_alphas(run_id)
    if not ids_all:
        return [], pd.DataFrame(), {}
    signs = member_signs_ic(run_id, ids_all)
    R = load_member_is_returns(run_id, ids_all, signs=signs)
    if R is None or R.shape[1] == 0:
        return [], pd.DataFrame(), signs
    R = R.dropna(axis=1, how="all").fillna(0.0)
    if R.shape[1] < 2:
        return list(R.columns), R, signs

    psr_score: dict[str, float] = {}
    sharpe_score: dict[str, float] = {}
    kept: list[str] = []
    for col in R.columns:
        s = R[col].dropna()
        if s.size < 30:
            continue
        arr = s.to_numpy(dtype=float)
        sh = _annual_sharpe(arr)
        sharpe_score[col] = sh
        if sh < 0.5:
            continue
        dd = _max_drawdown(arr)
        if dd > 0.25:
            continue
        try:
            ys = _year_stable(s, min_years=2)
        except Exception:
            ys = False
        if not ys:
            continue
        psr = _psr(arr, sr_benchmark_daily=0.0)
        if math.isnan(psr):
            psr = 0.0
        psr_score[col] = psr
        kept.append(col)

    if len(kept) < 4:
        # Fallback: top-Sharpe with at least 30 days, no other filters.
        kept = sorted(sharpe_score, key=lambda c: sharpe_score[c], reverse=True)[:25]
        psr_score = {c: sharpe_score.get(c, 0.0) for c in kept}

    Rk = R[kept]
    try:
        deduped = correlation_dedup(Rk, threshold=0.85, keep_metric=psr_score)
    except Exception:
        deduped = kept
    if len(deduped) < 4:
        deduped = sorted(kept, key=lambda c: psr_score.get(c, 0.0), reverse=True)[:6]
    ranked = sorted(deduped, key=lambda c: psr_score.get(c, 0.0), reverse=True)
    chosen = ranked[:6]
    if len(chosen) < 2:
        chosen = sorted(sharpe_score, key=lambda c: sharpe_score[c], reverse=True)[:6]
    return chosen, R[chosen], {k: int(signs.get(k, 1)) for k in chosen}


def _get_cached(run_id: str):
    if run_id not in _CACHE:
        _CACHE[run_id] = _build(run_id)
    return _CACHE[run_id]


# --------------------------------------------------------------------------- #
# Public API expected by the harness
# --------------------------------------------------------------------------- #

def select_members(alpha_index: pd.DataFrame) -> list[str]:
    chosen, _, _ = _get_cached(RUN_ID)
    return list(chosen)


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    chosen, R, signs = _get_cached(RUN_ID)
    cols = [m for m in member_ids if m in R.columns]
    if len(cols) < 2:
        eq = 1.0 / max(1, len(member_ids))
        return {m: eq for m in member_ids}

    Rm = R[cols].to_numpy(dtype=float)
    # Ledoit-Wolf-style shrink toward diagonal, then Neumann inverse.
    S = np.cov(Rm, rowvar=False)
    if S.ndim == 0:
        S = np.array([[float(S)]])
    diag = np.diag(np.diag(S))
    lam = 0.15
    Sigma = (1.0 - lam) * S + lam * diag
    Sinv = _neumann_inverse(Sigma, k=4)
    mu = Rm.mean(axis=0)
    raw = Sinv @ mu

    if not np.isfinite(raw).all() or float(np.abs(raw).sum()) < 1e-12:
        raw = np.ones(len(cols), dtype=float)

    coef = {cols[i]: float(raw[i]) for i in range(len(cols))}
    coef = apply_signs(coef, {k: int(signs.get(k, 1)) for k in cols})
    coef = normalize_coefficients(coef, "l1")

    # Push aggregate gross exposure to ~0.7 of the row-L1 budget so the
    # backtest sees a non-anemic typical exposure.
    target_aggregate = 0.7
    coef = {k: float(v) * target_aggregate for k, v in coef.items()}

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