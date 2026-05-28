"""PSR-screened concentrated tangency: Bailey & Lopez de Prado (2012) Probabilistic
Sharpe Ratio filter (skew/kurtosis/N-adjusted) on IS returns, correlation dedup,
then Ledoit-Wolf-shrunk tangency on the top-6 survivors. PSR penalizes fat-tailed
alphas — precisely the regime-fragile ones — so survivors are more likely to keep
their edge across the 2022-2024 IS → 2024-2026 OS regime shift."""
from __future__ import annotations
import argparse
import math
import numpy as np
import pandas as pd
import scipy.linalg as sla
import scipy.stats as sst

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

COMPOSITE_ID = "auto_036_psr_baileylopezdeprado_top6_lw_tangency"
COMPOSITION_NOTE = "psr_baileylopezdeprado_top6_lw_tangency_concentrated"

RUN_ID = "run_2026_05_c"
TOP_K = 6
PSR_BENCHMARK_SR = 0.0      # daily-Sharpe units; PSR vs zero (positive edge)
PSR_CONFIDENCE = 0.85       # keep alphas with ≥85% confidence Sharpe > 0
DEDUP_THRESHOLD = 0.80
TARGET_GROSS_L1 = 0.72      # mean row-L1 target after Σ|c|=1 normalization
LW_SHRINKAGE = 0.20         # diagonal shrinkage intensity
RIDGE_EPS = 1e-8


def _psr(returns: np.ndarray, sr_benchmark: float = 0.0) -> float:
    """Bailey & Lopez de Prado (2012) Probabilistic Sharpe Ratio.

    PSR(SR*) = Φ( (SR_hat - SR*) · sqrt(N-1) / sqrt(1 - γ3·SR_hat + (γ4/4)·SR_hat²) )

    Returns the probability that the *true* Sharpe exceeds sr_benchmark, given
    the observed SR, sample skewness γ3, sample excess kurtosis γ4, and N obs.
    """
    r = returns[np.isfinite(returns)]
    n = len(r)
    if n < 30:
        return 0.0
    mu = float(np.mean(r))
    sd = float(np.std(r, ddof=1))
    if sd <= 0 or not math.isfinite(sd):
        return 0.0
    sr = mu / sd
    try:
        skew = float(sst.skew(r, bias=False))
        kurt = float(sst.kurtosis(r, fisher=True, bias=False))  # excess
    except Exception:
        skew, kurt = 0.0, 0.0
    if not math.isfinite(skew):
        skew = 0.0
    if not math.isfinite(kurt):
        kurt = 0.0
    denom_sq = 1.0 - skew * sr + 0.25 * kurt * (sr * sr)
    if denom_sq <= 0:
        return 0.0
    z = (sr - sr_benchmark) * math.sqrt(n - 1) / math.sqrt(denom_sq)
    return float(sst.norm.cdf(z))


def _safe_sharpe(r: np.ndarray) -> float:
    r = r[np.isfinite(r)]
    if len(r) < 2:
        return 0.0
    sd = float(np.std(r, ddof=1))
    if sd <= 0:
        return 0.0
    return float(np.mean(r)) / sd


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    candidates = select_is_submittable(RUN_ID)
    if len(candidates) < TOP_K * 3:
        candidates = select_all_alphas(RUN_ID)
    if len(candidates) < 2:
        return candidates[: max(2, TOP_K)]

    signs = member_signs_ic(RUN_ID, candidates)
    R = load_member_is_returns(RUN_ID, candidates, signs=signs)
    if R.empty or R.shape[1] < 2:
        return candidates[:TOP_K]

    # 1) PSR per alpha (returns are already sign-aligned, so mu>0 is the edge)
    psr_map: dict[str, float] = {}
    sharpe_map: dict[str, float] = {}
    for aid in R.columns:
        s = R[aid].to_numpy()
        psr_map[aid] = _psr(s, sr_benchmark=PSR_BENCHMARK_SR)
        sharpe_map[aid] = _safe_sharpe(s)

    # 2) Threshold; relax adaptively if too few survive
    kept = [a for a, p in psr_map.items() if p >= PSR_CONFIDENCE]
    if len(kept) < TOP_K * 3:
        kept = sorted(psr_map, key=lambda a: psr_map[a], reverse=True)[: max(TOP_K * 4, 24)]

    # 3) Correlation dedup, keep ranking by PSR (regime-robust prior)
    R_kept = R[kept].dropna(how="all")
    if R_kept.shape[1] >= 2:
        dedup_keep = correlation_dedup(R_kept, threshold=DEDUP_THRESHOLD, keep_metric=psr_map)
    else:
        dedup_keep = list(R_kept.columns)

    # 4) Top-K by PSR
    selected = sorted(dedup_keep, key=lambda a: psr_map.get(a, 0.0), reverse=True)[:TOP_K]

    # Fallbacks to guarantee >= 2 members
    if len(selected) < 2:
        selected = sorted(R.columns, key=lambda a: sharpe_map.get(a, 0.0), reverse=True)[:TOP_K]
    if len(selected) < 2:
        selected = list(R.columns)[:TOP_K] if len(R.columns) else candidates[:TOP_K]
    return list(selected)


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    n_in = max(len(member_ids), 1)

    signs = member_signs_ic(RUN_ID, member_ids)
    R = load_member_is_returns(RUN_ID, member_ids, signs=signs)
    cols = [c for c in member_ids if c in R.columns]

    # Equal-weight fallback if we lost too many curves
    if len(cols) < 2:
        eq = {m: TARGET_GROSS_L1 / n_in for m in member_ids}
        return apply_signs(eq, signs)

    R = R[cols].fillna(0.0)
    mu = R.mean().to_numpy()
    S = np.cov(R.to_numpy(), rowvar=False, ddof=1)
    p = S.shape[0]

    # Ledoit-Wolf-style fixed shrinkage to the diagonal target + small ridge
    diag_target = np.diag(np.diag(S))
    S_shr = (1.0 - LW_SHRINKAGE) * S + LW_SHRINKAGE * diag_target
    S_shr = S_shr + RIDGE_EPS * np.eye(p)

    # Tangency w ∝ Σ⁻¹ μ ; mu should be ~positive (signs aligned)
    try:
        w = sla.solve(S_shr, mu, assume_a="pos")
    except Exception:
        w = sla.pinvh(S_shr) @ mu

    # Long-only on aligned space (negative tangency weights mean the alpha is
    # actually hurting the portfolio on the sign-aligned axis — drop it).
    w = np.clip(w, 0.0, None)
    if not np.isfinite(w).all() or w.sum() <= 0:
        w = np.ones(p)

    coef = dict(zip(cols, [float(x) for x in w.tolist()]))
    # Map coefficients back to the deployable sign of each member alpha
    coef = apply_signs(coef, signs)

    # Σ|c|=1 then scale to desired aggregate gross-exposure budget
    coef = normalize_coefficients(coef, scheme="l1")
    coef = {k: float(v) * TARGET_GROSS_L1 for k, v in coef.items()}

    # Guarantee every requested member id appears in the output
    for m in member_ids:
        if m not in coef:
            coef[m] = 0.0
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