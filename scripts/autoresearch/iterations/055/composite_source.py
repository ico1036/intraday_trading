"""Greedy Gram-Schmidt orthogonal residual selection — covariance-free composite.

Method: rank candidates by IS Sharpe; iteratively QR-project remaining candidates
onto the basis of already-selected members and score the residual by its Sharpe
(residual = orthogonal information not yet captured). Stop when residual Sharpe
falls below floor or n_target reached. Reference: Orthogonal Matching Pursuit
(Pati, Rezaiifar, Krishnaprasad 1993; Mallat & Zhang 1993), adapted from sparse
signal recovery to portfolio construction. Selection gated by per-year IS Sharpe
stability and IS max-drawdown < 20% for regime robustness.
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
    select_all_alphas,
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_055_greedy_gs_orth_resid_yearstable_dd20_n8"
COMPOSITION_NOTE = "greedy_gs_orth_resid_yearstable_dd20_n8_scale12"

RUN_ID = "run_2026_05_c"
N_TARGET = 8
RESID_SHARPE_FLOOR = 0.25
DD_THRESHOLD = 0.20
DEDUP_RHO = 0.85
SCALE_UP = 12.0  # post-normalize gross-exposure multiplier


def _ann_sharpe(r: np.ndarray) -> float:
    if r.size < 2:
        return 0.0
    sd = float(np.std(r, ddof=1))
    if sd <= 1e-12:
        return 0.0
    return float(np.mean(r) / sd * math.sqrt(252.0))


def _max_drawdown(r: pd.Series) -> float:
    eq = (1.0 + r.fillna(0.0)).cumprod().values
    if eq.size == 0:
        return 1.0
    peak = np.maximum.accumulate(eq)
    return float(((peak - eq) / np.maximum(peak, 1e-12)).max())


def _year_stable(r: pd.Series) -> bool:
    if r.shape[0] < 60:
        return True
    idx = r.index
    if not isinstance(idx, pd.DatetimeIndex):
        try:
            idx = pd.to_datetime(idx)
            r = pd.Series(r.values, index=idx)
        except Exception:
            return True
    if len(np.unique(idx.year)) < 2:
        return True
    for _, sub in r.groupby(idx.year):
        if sub.shape[0] < 20:
            continue
        if _ann_sharpe(sub.values) <= 0.0:
            return False
    return True


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    pool = select_is_submittable(RUN_ID)
    if len(pool) < 6:
        extra = select_all_alphas(RUN_ID)
        pool = list(dict.fromkeys(list(pool) + list(extra)))
    if not pool:
        pool = [str(a) for a in alpha_index["alpha_id"].astype(str).tolist()]
    signs = member_signs_ic(RUN_ID, pool)
    R = load_member_is_returns(RUN_ID, pool, signs=signs)
    if R is None or R.shape[1] == 0:
        return []
    R = R.dropna(axis=1, how="all").fillna(0.0)
    if R.shape[1] < 3:
        return list(R.columns)

    # Regime-robust prefilter: per-year stability + drawdown discipline
    kept = [c for c in R.columns if _year_stable(R[c]) and _max_drawdown(R[c]) < DD_THRESHOLD]
    if len(kept) < 4:
        # Relax: keep DD only
        kept = [c for c in R.columns if _max_drawdown(R[c]) < DD_THRESHOLD]
    if len(kept) < 4:
        # Last-resort: take all
        kept = list(R.columns)

    R_k = R[kept]
    sharpe_map = {c: _ann_sharpe(R_k[c].values) for c in kept}

    # Correlation dedup so the residual basis isn't choked by near-clones
    deduped = correlation_dedup(R_k, threshold=DEDUP_RHO, keep_metric=sharpe_map)
    if len(deduped) < 3:
        deduped = sorted(kept, key=lambda c: sharpe_map.get(c, 0.0), reverse=True)[: max(4, N_TARGET)]
    R_d = R_k[deduped]

    # Greedy Gram-Schmidt: pick highest IS-Sharpe seed, then iteratively add the
    # candidate with the highest *residual* Sharpe after projecting out the basis.
    ordered = sorted(deduped, key=lambda c: sharpe_map.get(c, 0.0), reverse=True)
    if not ordered:
        return []
    chosen = [ordered[0]]
    candidates = list(ordered[1:])
    X = R_d[chosen[0]].values.astype(float).reshape(-1, 1)

    while len(chosen) < N_TARGET and candidates:
        try:
            Q, _ = np.linalg.qr(X)
        except np.linalg.LinAlgError:
            break
        best_id, best_score = None, -math.inf
        for cand in candidates:
            y = R_d[cand].values.astype(float)
            resid = y - Q @ (Q.T @ y)
            sh = _ann_sharpe(resid)
            if sh > best_score:
                best_score = sh
                best_id = cand
        if best_id is None or best_score < RESID_SHARPE_FLOOR:
            break
        chosen.append(best_id)
        candidates.remove(best_id)
        X = np.column_stack([X, R_d[best_id].values.astype(float)])

    if len(chosen) < 2:
        chosen = ordered[: min(3, len(ordered))]
    return chosen


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    if not member_ids:
        return {}
    signs = member_signs_ic(RUN_ID, member_ids)
    R = load_member_is_returns(RUN_ID, member_ids, signs=signs)
    if R is None or R.shape[1] == 0:
        coef = {m: 1.0 for m in member_ids}
        coef = normalize_coefficients(coef, "l1")
        return {k: v * SCALE_UP for k, v in coef.items()}
    R = R.fillna(0.0)
    present = [m for m in member_ids if m in R.columns]

    # Weight by IS Sharpe (clipped to >=0); fall back to equal-weight if all zero
    sh = {m: max(_ann_sharpe(R[m].values), 0.0) for m in present}
    total = sum(sh.values())
    if total <= 1e-12:
        base = {m: 1.0 / max(len(present), 1) for m in present}
    else:
        base = {m: sh[m] / total for m in present}
    coef = {m: base.get(m, 0.0) for m in member_ids}

    # Sign-align using IC-derived signs (flip alphas with negative IC)
    coef = apply_signs(coef, signs)

    # L1-normalize so Σ|c|=1, then scale up to occupy the gross-exposure budget.
    # Member weight panels typically have per-row L1 ≪ 1, so the runner's row-L1
    # clamp does not trigger at Σ|c|=1 — we explicitly multiply by SCALE_UP to
    # reach mean row L1 ≈ 0.5–0.8 (clamp catches any overshoot).
    coef = normalize_coefficients(coef, "l1")
    coef = {m: v * SCALE_UP for m, v in coef.items()}
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