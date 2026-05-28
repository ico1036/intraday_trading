"""Greedy Gram-Schmidt residualization (cov-free composition).

Method: classical Gram-Schmidt orthogonalization on IS return space.
Order candidates by IS Sharpe; iteratively add the candidate whose
OLS residual against the kept basis has the highest Sharpe (i.e. the
most orthogonal *and* profitable new direction). This is cov-free —
no Sigma inversion, no 1/sigma weighting trap — so post-L1-normalize
coefficients do not auto-shrink gross exposure to ~0.05 (the failure
mode of every prior tangency/min-var attempt). Per-year IS Sharpe
stability + max-DD discipline gate the candidate set before greedy
selection, matching the leaderboard pattern (n in [5,8], year-stable,
DD<25%). Coefficients are L1-normalized then multiplied to push mean
row L1 toward the 0.5-0.8 sweet spot.
"""
from __future__ import annotations

import argparse
import math
import numpy as np
import pandas as pd

from intraday.composites._runner import build_and_backtest
from intraday.composites._optim_helpers import (
    select_is_submittable,
    select_all_alphas,
    member_signs_ic,
    apply_signs,
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_051_greedy_gram_schmidt_resid_sharpe_top8_ye"
COMPOSITION_NOTE = "greedy_gram_schmidt_resid_sharpe_top8_yearstable_dd25_gross06"

RUN_ID = "run_2026_05_c"
MAX_MEMBERS = 8
MIN_KEPT = 4
MIN_RESIDUAL_SHARPE = 0.30
DD_CAP = 0.25
POST_NORMALIZE_SCALE = 5.0  # push L1-normalized coefs up for usable gross


def _sharpe(x: np.ndarray) -> float:
    if x.size < 10:
        return 0.0
    s = float(np.std(x, ddof=1))
    if s <= 0 or not np.isfinite(s):
        return 0.0
    return float(np.mean(x) / s * math.sqrt(252.0))


def _is_sharpe_map(R: pd.DataFrame) -> dict[str, float]:
    out: dict[str, float] = {}
    for col in R.columns:
        x = R[col].dropna().values.astype(float)
        out[col] = _sharpe(x)
    return out


def _per_year_stable(R: pd.DataFrame) -> list[str]:
    if R.empty or not isinstance(R.index, pd.DatetimeIndex):
        return list(R.columns)
    years = sorted(set(R.index.year))
    if len(years) < 2:
        return list(R.columns)
    kept: list[str] = []
    for col in R.columns:
        ok = True
        for y in years:
            sub = R[col].loc[R.index.year == y].dropna()
            if len(sub) < 20:
                continue
            sd = float(sub.std(ddof=1))
            if sd <= 0:
                ok = False
                break
            sh = float(sub.mean()) / sd * math.sqrt(252.0)
            if sh <= 0:
                ok = False
                break
        if ok:
            kept.append(col)
    return kept


def _dd_filter(R: pd.DataFrame, cap: float) -> list[str]:
    kept: list[str] = []
    for col in R.columns:
        x = R[col].fillna(0.0).values.astype(float)
        eq = np.cumprod(1.0 + x)
        peak = np.maximum.accumulate(eq)
        dd = float(np.min(eq / np.where(peak <= 0, 1.0, peak) - 1.0))
        if dd > -cap:
            kept.append(col)
    return kept


def _greedy_gs(R: pd.DataFrame, sharpe_map: dict[str, float]) -> tuple[list[str], dict[str, float]]:
    cols = [c for c in R.columns if sharpe_map.get(c, 0.0) > 0.0]
    if not cols:
        return [], {}
    cands = sorted(cols, key=lambda c: -sharpe_map.get(c, 0.0))
    kept: list[str] = [cands[0]]
    resid_sh: dict[str, float] = {cands[0]: sharpe_map[cands[0]]}
    while len(kept) < MAX_MEMBERS:
        B = R[kept].fillna(0.0).values.astype(float)
        # Use pseudo-inverse for numerical safety with near-collinear cols
        try:
            BtB_inv = np.linalg.pinv(B.T @ B)
        except np.linalg.LinAlgError:
            break
        best_id: str | None = None
        best_sh = -np.inf
        for c in cands:
            if c in kept:
                continue
            y = R[c].fillna(0.0).values.astype(float)
            beta = BtB_inv @ (B.T @ y)
            resid = y - B @ beta
            sh = _sharpe(resid)
            if sh > best_sh:
                best_sh = sh
                best_id = c
        if best_id is None or best_sh < MIN_RESIDUAL_SHARPE:
            break
        kept.append(best_id)
        resid_sh[best_id] = max(best_sh, 0.0)
    return kept, resid_sh


def _fetch_pool() -> list[str]:
    ids = select_is_submittable(RUN_ID)
    if len(ids) < MIN_KEPT:
        ids = select_all_alphas(RUN_ID)
    return list(ids)


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    ids = _fetch_pool()
    if len(ids) < 2:
        return ids
    signs = member_signs_ic(RUN_ID, ids)
    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    if R is None or R.empty or R.shape[1] < 2:
        # graceful fallback: top-IS-Sharpe by index column if available
        if "is_sharpe" in alpha_index.columns:
            sub = alpha_index[alpha_index["alpha_id"].isin(ids)]
            sub = sub.sort_values("is_sharpe", ascending=False)
            return list(sub["alpha_id"].head(6))
        return ids[:6]

    # Gate 1: per-year IS Sharpe stability
    stable = _per_year_stable(R)
    if len(stable) >= MIN_KEPT:
        R = R[stable]

    # Gate 2: drawdown discipline
    dd_ok = _dd_filter(R, DD_CAP)
    if len(dd_ok) >= MIN_KEPT:
        R = R[dd_ok]

    sharpe_map = _is_sharpe_map(R)
    # Keep only positive-IS candidates above a small floor
    cols = [c for c in R.columns if sharpe_map.get(c, 0.0) > 0.20]
    if len(cols) < 2:
        # last-ditch: top-6 raw IS Sharpe from the surviving R
        ranked = sorted(R.columns, key=lambda c: -sharpe_map.get(c, 0.0))
        return ranked[: max(MIN_KEPT, min(6, len(ranked)))]
    R = R[cols]

    kept, _ = _greedy_gs(R, sharpe_map)
    if len(kept) < 2:
        ranked = sorted(R.columns, key=lambda c: -sharpe_map.get(c, 0.0))
        kept = ranked[: max(MIN_KEPT, min(6, len(ranked)))]
    return kept


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    ids = list(member_ids)
    if not ids:
        return {}
    signs = member_signs_ic(RUN_ID, ids)
    R = load_member_is_returns(RUN_ID, ids, signs=signs)

    if R is None or R.empty:
        base = {a: 1.0 for a in ids}
        coef = normalize_coefficients(base, "l1")
        coef = {k: v * POST_NORMALIZE_SCALE for k, v in coef.items()}
        return apply_signs(coef, signs)

    cols = [c for c in ids if c in R.columns]
    if len(cols) < 2:
        base = {a: 1.0 for a in ids}
        coef = normalize_coefficients(base, "l1")
        coef = {k: v * POST_NORMALIZE_SCALE for k, v in coef.items()}
        return apply_signs(coef, signs)

    sharpe_map = _is_sharpe_map(R[cols])
    _, resid_sh = _greedy_gs(R[cols], sharpe_map)

    # Weight each kept member by its residual Sharpe (orthogonal contribution).
    # Fall back to raw IS Sharpe for any member missing a residual score.
    raw: dict[str, float] = {}
    for a in cols:
        v = resid_sh.get(a, sharpe_map.get(a, 0.0))
        raw[a] = max(float(v), 0.0)
    if sum(raw.values()) <= 0:
        raw = {a: 1.0 for a in cols}

    coef = normalize_coefficients(raw, "l1")
    # Push coefficient magnitudes up so mean composite row L1 lands in
    # [0.5, 0.8]; the runner row-L1-clamps to <=1 anyway, so over-shooting
    # is safe and avoids the chronic 0.05 gross-exposure ceiling.
    coef = {k: float(v) * POST_NORMALIZE_SCALE for k, v in coef.items()}
    # Re-deploy in IC-aware sign space
    coef = apply_signs(coef, signs)
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