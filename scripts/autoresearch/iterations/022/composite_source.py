"""Calmar-ratio weighted concentrated composite (Young 1991).

Selects the top-8 IS-submittable alphas by Calmar ratio
(annualized return / max drawdown), correlation-deduped at rho=0.85
(keeping by Calmar), and weights members linearly in Calmar. IC signs
are applied to the coefficient dict so IC-negative alphas contribute
their deployable sign. Mean row-L1 is targeted to ~0.70 of the gross
budget so the composite isn't anemic on PnL.

Mechanism cited:
- Young, T.W. (1991). "Calmar Ratio: A Smoother Tool". Futures Magazine.
- Magdon-Ismail, M. & Atiya, A. (2004). "Maximum Drawdown". (Used as
  the denominator of the Calmar ratio.)

Distinct from prior tried families (Neumann tangency, NCO+MP+detone,
HERC, Black-Litterman, DRP eigenbasis, max-div, mean-CVaR, frac Kelly,
HRP, James-Stein, CSCV bootstrap, anti-bias, stability/IR cluster,
bootstrap ERC, PBO/Spinu, PC1-residual, regime-year+LW, mean-semivar,
hedge-EG, CCM Elton-Gruber, STARR).
"""
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
    select_is_submittable,
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_022_calmar_young91_top8_dedup085_linear_weig"
COMPOSITION_NOTE = "calmar_young91_top8_dedup085_linear_weight_l1_07"

RUN_ID = "run_2026_05_c"
TOP_K = 8
DEDUP_THRESHOLD = 0.85
TARGET_L1 = 0.70
MIN_CALMAR = 0.5
PERIODS_PER_YEAR = 365.0
MIN_OBS = 30
MIN_MDD = 1e-4


def _max_drawdown(equity: np.ndarray) -> float:
    if equity.size == 0:
        return 0.0
    peak = np.maximum.accumulate(equity)
    safe_peak = np.where(peak > 0, peak, 1.0)
    dd = (equity - peak) / safe_peak
    return float(-dd.min())


def _calmar(r: np.ndarray) -> float:
    if r.size < MIN_OBS:
        return 0.0
    if float(np.std(r)) < 1e-9:
        return 0.0
    equity = np.cumprod(1.0 + r)
    mdd = _max_drawdown(equity)
    if mdd < MIN_MDD:
        return 0.0
    ann_ret = float(np.mean(r)) * PERIODS_PER_YEAR
    return ann_ret / mdd


def _compute_calmars(R: pd.DataFrame) -> dict[str, float]:
    out: dict[str, float] = {}
    for a in R.columns:
        col = R[a].dropna()
        if col.size < MIN_OBS:
            continue
        c = _calmar(col.to_numpy())
        if math.isfinite(c) and c > 0.0:
            out[a] = c
    return out


def _core_select() -> tuple[list[str], dict[str, float]]:
    candidates = select_is_submittable(RUN_ID)
    if not candidates or len(candidates) < 2:
        return [], {}

    signs = member_signs_ic(RUN_ID, candidates)
    R = load_member_is_returns(RUN_ID, candidates, signs=signs)
    if R.empty or R.shape[1] < 2:
        return [], {}

    R = R.dropna(how="all").fillna(0.0)
    calmars = _compute_calmars(R)
    if not calmars:
        return [], {}

    keep = [a for a, c in calmars.items() if c >= MIN_CALMAR]
    if len(keep) < 2:
        keep = sorted(calmars, key=lambda a: -calmars[a])[: max(2, TOP_K)]
    if len(keep) < 2:
        return [], calmars

    cols_avail = [a for a in keep if a in R.columns]
    if len(cols_avail) < 2:
        return [], calmars

    R_keep = R[cols_avail]
    metric = {a: calmars[a] for a in cols_avail}

    try:
        deduped = correlation_dedup(
            R_keep, threshold=DEDUP_THRESHOLD, keep_metric=metric
        )
    except Exception:
        deduped = cols_avail

    if not deduped or len(deduped) < 2:
        deduped = sorted(metric, key=lambda a: -metric[a])[: max(2, TOP_K)]

    ranked = sorted(deduped, key=lambda a: -calmars.get(a, 0.0))
    selected = ranked[:TOP_K]
    if len(selected) < 2:
        # ultimate fallback: just take top-K by Calmar from whatever was in R
        selected = sorted(calmars, key=lambda a: -calmars[a])[: max(2, TOP_K)]
    return selected, calmars


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    members, _ = _core_select()
    # de-duplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for m in members:
        if m not in seen:
            seen.add(m)
            unique.append(m)
    return unique


def member_weights(
    member_ids: list[str], alpha_index: pd.DataFrame
) -> dict[str, float]:
    if not member_ids:
        return {}

    signs = member_signs_ic(RUN_ID, member_ids)
    R = load_member_is_returns(RUN_ID, member_ids, signs=signs)

    calmars: dict[str, float] = {}
    if not R.empty:
        R = R.dropna(how="all").fillna(0.0)
        calmars = _compute_calmars(R)

    raw: dict[str, float] = {}
    for a in member_ids:
        c = calmars.get(a, 0.0)
        if c <= 0.0 or not math.isfinite(c):
            raw[a] = 0.0
        else:
            raw[a] = float(c)

    total = sum(raw.values())
    if total <= 1e-12:
        # equal-weight fallback so we never emit a zero composite
        coef = {a: 1.0 / float(len(member_ids)) for a in member_ids}
    else:
        # if some members got zero Calmar, give them a tiny floor so the
        # final dict still covers all ids without zero coefficients
        floor = 1e-6 * total
        coef = {a: (raw[a] if raw[a] > 0.0 else floor) for a in member_ids}
        s = sum(coef.values())
        coef = {a: v / s for a, v in coef.items()}

    # flip IC-negative members to their deployable sign
    coef = apply_signs(coef, signs)

    # L1-normalize then scale to target gross-exposure budget
    coef = normalize_coefficients(coef, scheme="l1")
    coef = {a: float(v) * TARGET_L1 for a, v in coef.items()}
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