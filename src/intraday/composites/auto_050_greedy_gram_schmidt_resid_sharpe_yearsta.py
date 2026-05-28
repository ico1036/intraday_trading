"""Greedy Gram-Schmidt residual-Sharpe orthogonalization on IS returns.

Cites: classical Gram-Schmidt residualization combined with iterative
information-ratio gating (Grinold-Kahn fundamental law style). Cov-FREE
composition (per the never-attempted user menu) that preserves native
member leverage and avoids the inverse-cov 1/sigma-weighting trap which
under-shoots the gross-exposure budget. Pre-filter is regime-aware:
per-year IS-Sharpe positivity + IS max-drawdown discipline.
"""
from __future__ import annotations

import argparse
import numpy as np
import pandas as pd

from intraday.composites._runner import build_and_backtest
from intraday.composites._optim_helpers import (
    select_is_submittable,
    select_all_alphas,
    member_signs_ic,
    load_member_is_returns,
    correlation_dedup,
    apply_signs,
    normalize_coefficients,
    member_is_sharpe,
)

COMPOSITE_ID = "auto_050_greedy_gram_schmidt_resid_sharpe_yearsta"
COMPOSITION_NOTE = "greedy_gram_schmidt_resid_sharpe_yearstable_dd25_top8_gross065"

RUN_ID = "run_2026_05_c"

TARGET_GROSS = 0.65
MAX_MEMBERS = 8
RESIDUAL_SHARPE_FLOOR = 0.3
DEDUP_RHO = 0.85
DD_MAX = 0.25
POOL_TOP_N = 40
WEIGHT_FLOOR = 0.05


def _ann_sharpe(x: np.ndarray) -> float:
    x = x[np.isfinite(x)]
    if x.size < 30:
        return 0.0
    sd = float(x.std(ddof=0))
    if sd <= 1e-12:
        return 0.0
    return float(x.mean() / sd * np.sqrt(252.0))


def _max_dd(x: np.ndarray) -> float:
    x = x[np.isfinite(x)]
    if x.size == 0:
        return 1.0
    eq = np.cumsum(x)
    peak = np.maximum.accumulate(eq)
    dd = peak - eq
    return float(np.clip(dd.max(), 0.0, 1.0))


def _year_stable(s: pd.Series) -> bool:
    if s.empty:
        return False
    try:
        years = s.groupby(s.index.year)
    except Exception:
        return False
    saw_any = False
    for _, grp in years:
        if grp.size < 30:
            continue
        saw_any = True
        if _ann_sharpe(grp.to_numpy()) <= 0.0:
            return False
    return saw_any


def _safe_inv(M: np.ndarray) -> np.ndarray:
    M = M + np.eye(M.shape[0]) * 1e-8
    try:
        return np.linalg.inv(M)
    except np.linalg.LinAlgError:
        return np.linalg.pinv(M)


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    try:
        ids = select_is_submittable(RUN_ID)
    except Exception:
        ids = []
    if len(ids) < 4:
        try:
            ids = select_all_alphas(RUN_ID)
        except Exception:
            ids = []
    if len(ids) < 4 and alpha_index is not None and not alpha_index.empty:
        ids = list(alpha_index["alpha_id"].astype(str).unique())
    if len(ids) < 2:
        return ids[:MAX_MEMBERS]

    try:
        sharpe_map = member_is_sharpe(RUN_ID, ids)
    except Exception:
        sharpe_map = {a: 0.0 for a in ids}
    sharpe_map = {a: float(sharpe_map.get(a, 0.0)) for a in ids}

    ranked = sorted(ids, key=lambda a: sharpe_map.get(a, -1e9), reverse=True)
    pool = ranked[: max(POOL_TOP_N, MAX_MEMBERS * 4)]

    try:
        signs = member_signs_ic(RUN_ID, pool)
    except Exception:
        signs = {a: 1 for a in pool}
    signs = {a: int(signs.get(a, 1)) for a in pool}

    try:
        R_raw = load_member_is_returns(RUN_ID, pool, signs=signs)
    except Exception:
        R_raw = None
    if R_raw is None or R_raw.empty:
        return ranked[:MAX_MEMBERS]
    R_raw = R_raw.dropna(axis=1, how="all")
    if R_raw.shape[1] < 2:
        return ranked[:MAX_MEMBERS]

    kept: list[str] = []
    for a in R_raw.columns:
        s = R_raw[a].dropna()
        if s.size < 60:
            continue
        if _max_dd(s.to_numpy()) > DD_MAX:
            continue
        if not _year_stable(s):
            continue
        kept.append(a)

    if len(kept) < 4:
        kept = [a for a in R_raw.columns if R_raw[a].dropna().size >= 60]
    if len(kept) < 2:
        return ranked[:MAX_MEMBERS]

    R_kept = R_raw[kept]
    keep_metric = {a: sharpe_map.get(a, 0.0) for a in kept}
    try:
        deduped = correlation_dedup(R_kept, threshold=DEDUP_RHO, keep_metric=keep_metric)
    except Exception:
        deduped = kept
    if len(deduped) < 2:
        deduped = kept

    deduped_sorted = sorted(deduped, key=lambda a: sharpe_map.get(a, -1e9), reverse=True)

    R_full = R_raw[deduped_sorted].fillna(0.0)
    if R_full.shape[1] < 2:
        return deduped_sorted[:MAX_MEMBERS]

    selected: list[str] = [deduped_sorted[0]]
    candidates = [a for a in deduped_sorted[1:]]

    while len(selected) < MAX_MEMBERS and candidates:
        X = R_full[selected].to_numpy()
        XtX_inv = _safe_inv(X.T @ X)
        best_a = None
        best_sh = -1e9
        for a in candidates:
            y = R_full[a].to_numpy()
            beta = XtX_inv @ (X.T @ y)
            resid = y - X @ beta
            sh = _ann_sharpe(resid)
            if sh > best_sh:
                best_sh = sh
                best_a = a
        if best_a is None or best_sh < RESIDUAL_SHARPE_FLOOR:
            break
        selected.append(best_a)
        candidates.remove(best_a)

    if len(selected) < 2:
        selected = deduped_sorted[: max(2, min(MAX_MEMBERS, len(deduped_sorted)))]
    return selected


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    if not member_ids:
        return {}

    try:
        signs = member_signs_ic(RUN_ID, member_ids)
    except Exception:
        signs = {}
    signs = {a: int(signs.get(a, 1)) for a in member_ids}

    try:
        R = load_member_is_returns(RUN_ID, member_ids, signs=signs)
    except Exception:
        R = None

    raw: dict[str, float] = {}

    if R is None or R.empty:
        for a in member_ids:
            raw[a] = 1.0
    else:
        R = R.fillna(0.0)
        cols_in_R = [a for a in member_ids if a in R.columns]
        if len(cols_in_R) < 2:
            for a in member_ids:
                raw[a] = 1.0
        else:
            seed = cols_in_R[0]
            raw[seed] = max(_ann_sharpe(R[seed].to_numpy()), WEIGHT_FLOOR * 4.0)
            for k in range(1, len(cols_in_R)):
                X = R[cols_in_R[:k]].to_numpy()
                XtX_inv = _safe_inv(X.T @ X)
                y = R[cols_in_R[k]].to_numpy()
                beta = XtX_inv @ (X.T @ y)
                resid = y - X @ beta
                rs = _ann_sharpe(resid)
                raw[cols_in_R[k]] = max(rs, WEIGHT_FLOOR)
            for a in member_ids:
                if a not in raw:
                    raw[a] = WEIGHT_FLOOR

    try:
        coef = normalize_coefficients(raw, "l1")
    except Exception:
        total = sum(abs(v) for v in raw.values()) or 1.0
        coef = {k: v / total for k, v in raw.items()}

    try:
        coef = apply_signs(coef, signs)
    except Exception:
        coef = {k: v * signs.get(k, 1) for k, v in coef.items()}

    coef = {k: float(v) * TARGET_GROSS for k, v in coef.items()}
    for a in member_ids:
        if a not in coef:
            coef[a] = 0.0
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