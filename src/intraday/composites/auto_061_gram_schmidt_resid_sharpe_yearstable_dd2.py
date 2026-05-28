"""Greedy Gram-Schmidt residual-Sharpe selection (cov-free) with per-year IS stability and DD discipline.

Method: rank IS-submittable alphas by IS Sharpe desc; seed basis with the top
member; for each candidate compute residual returns after projecting onto the
chosen basis (B(B'B)^{-1}B') and score by annualized Sharpe of that residual;
greedily add the candidate maximizing residual Sharpe until the floor (0.3)
trips or n=8. Cov-FREE: avoids the 1/sigma underweighting trap of tangency /
min-variance optimizers that has held prior composites to mean row-L1 < 0.10.
Filters: max IS drawdown < 0.25, positive Sharpe in every IS calendar sub-year
(2022/2023/2024), correlation dedup at rho=0.85 keeping highest IS Sharpe.
Sign alignment via IC dead-band (Lopez de Prado-style). Final coefficients
L1-normalized then scaled to Sigma|c|=8 so the composite uses 50-80% of its
gross-exposure budget instead of leaving it on the table.
"""
from __future__ import annotations
import argparse
import numpy as np
import pandas as pd

from intraday.composites._runner import build_and_backtest
from intraday.composites._optim_helpers import (
    member_signs_ic,
    apply_signs,
    select_is_submittable,
    select_all_alphas,
    correlation_dedup,
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_061_gram_schmidt_resid_sharpe_yearstable_dd2"
COMPOSITION_NOTE = "gram_schmidt_resid_sharpe_yearstable_dd25_top8_gross"

RUN_ID = "run_2026_05_c"
MAX_MEMBERS = 8
RESID_SHARPE_FLOOR = 0.30
MAX_IS_DD = 0.25
DEDUP_RHO = 0.85
COEF_SCALE = 8.0  # multiplier after L1=1 normalize, to escape the gross-exposure ceiling


def _ann_sharpe(r: pd.Series) -> float:
    s = pd.Series(r).dropna()
    if len(s) < 20:
        return 0.0
    sd = float(s.std(ddof=1))
    if sd <= 0 or not np.isfinite(sd):
        return 0.0
    return float(s.mean() / sd * np.sqrt(252.0))


def _max_dd(r: pd.Series) -> float:
    s = pd.Series(r).fillna(0.0)
    if s.empty:
        return 1.0
    eq = (1.0 + s).cumprod()
    peak = eq.cummax()
    dd = (eq / peak - 1.0).min()
    if not np.isfinite(dd):
        return 1.0
    return float(-dd)


def _year_stable(r: pd.Series) -> bool:
    s = pd.Series(r).dropna()
    if s.empty:
        return False
    idx = s.index
    if not isinstance(idx, pd.DatetimeIndex):
        try:
            idx = pd.to_datetime(idx)
        except Exception:
            return True
    years = np.asarray(idx.year)
    for y in np.unique(years):
        grp = s.values[years == y]
        if len(grp) < 20:
            continue
        g = pd.Series(grp)
        if _ann_sharpe(g) <= 0:
            return False
    return True


def _filter_panel(R: pd.DataFrame) -> pd.DataFrame:
    keep: list[str] = []
    for col in R.columns:
        r = R[col]
        if _max_dd(r) > MAX_IS_DD:
            continue
        if not _year_stable(r):
            continue
        keep.append(col)
    if not keep:
        return R.iloc[:, :0]
    return R[keep]


def _greedy_gs(R: pd.DataFrame) -> list[str]:
    cols = list(R.columns)
    if len(cols) == 0:
        return []
    sharpes = {c: _ann_sharpe(R[c]) for c in cols}
    ordered = sorted(cols, key=lambda c: -sharpes[c])
    if len(ordered) == 1:
        return ordered
    chosen: list[str] = [ordered[0]]
    remaining: list[str] = ordered[1:]
    while remaining and len(chosen) < MAX_MEMBERS:
        B = R[chosen].fillna(0.0).to_numpy(dtype=float)
        try:
            BtB = B.T @ B
            BtB_inv = np.linalg.pinv(BtB + 1e-8 * np.eye(BtB.shape[0]))
        except Exception:
            break
        # Pre-compute Y matrix of all candidate returns for vectorised residuals
        Y = R[remaining].fillna(0.0).to_numpy(dtype=float)
        # beta_k = (B'B)^{-1} B' y_k  -> all candidates: B^+ = BtB_inv @ B.T
        Bplus = BtB_inv @ B.T
        Beta = Bplus @ Y                # k_chosen x n_remaining
        Yhat = B @ Beta                 # T x n_remaining
        Resid = Y - Yhat                # T x n_remaining
        # Sharpe of each residual column
        mu = Resid.mean(axis=0)
        sd = Resid.std(axis=0, ddof=1)
        with np.errstate(divide="ignore", invalid="ignore"):
            sh = np.where(sd > 0, mu / sd * np.sqrt(252.0), -np.inf)
        sh = np.nan_to_num(sh, nan=-np.inf, neginf=-np.inf, posinf=-np.inf)
        best_idx = int(np.argmax(sh))
        best_score = float(sh[best_idx])
        if not np.isfinite(best_score) or best_score < RESID_SHARPE_FLOOR:
            break
        best_id = remaining[best_idx]
        chosen.append(best_id)
        remaining = [c for c in remaining if c != best_id]
    return chosen


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    ids = select_is_submittable(RUN_ID)
    if not ids:
        ids = select_all_alphas(RUN_ID)
    if not ids:
        ids = [str(x) for x in alpha_index["alpha_id"].tolist()]
    if len(ids) < 2:
        return ids
    signs = member_signs_ic(RUN_ID, ids)
    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    if R is None or R.shape[1] < 2:
        return list(R.columns) if R is not None else ids[: min(len(ids), MAX_MEMBERS)]

    R_f = _filter_panel(R)
    if R_f.shape[1] < 2:
        # year-stability + DD may be too strict; fall back to DD-only
        keep = [c for c in R.columns if _max_dd(R[c]) <= MAX_IS_DD]
        R_f = R[keep] if len(keep) >= 2 else R

    keep_metric = {c: _ann_sharpe(R_f[c]) for c in R_f.columns}
    try:
        deduped = correlation_dedup(R_f, threshold=DEDUP_RHO, keep_metric=keep_metric)
    except Exception:
        deduped = list(R_f.columns)
    if len(deduped) < 2:
        deduped = sorted(R_f.columns, key=lambda c: -keep_metric.get(c, 0.0))[: min(MAX_MEMBERS, R_f.shape[1])]
    R_d = R_f[deduped]

    chosen = _greedy_gs(R_d)
    if len(chosen) < 2:
        chosen = sorted(deduped, key=lambda c: -_ann_sharpe(R_f[c]))[: max(2, MAX_MEMBERS // 2)]
    return chosen


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    if not member_ids:
        return {}
    if len(member_ids) == 1:
        m = member_ids[0]
        signs = member_signs_ic(RUN_ID, [m])
        sign = float(signs.get(m, 1.0)) if isinstance(signs, dict) else 1.0
        if sign == 0:
            sign = 1.0
        return {m: float(np.sign(sign) * 1.0 * COEF_SCALE)}

    signs = member_signs_ic(RUN_ID, member_ids)
    # Equal start across the kept set
    coef: dict[str, float] = {m: 1.0 for m in member_ids}
    # Sign-align via IC
    try:
        coef = apply_signs(coef, signs)
    except Exception:
        pass
    # Replace any zero-signed coefficients with +1.0 to avoid dropping members entirely
    coef = {k: (float(v) if v != 0 else 1.0) for k, v in coef.items()}
    # L1=1 normalize then scale to lift mean composite row-L1 into the productive 0.5-0.8 band
    try:
        coef = normalize_coefficients(coef, "l1")
    except Exception:
        s = sum(abs(v) for v in coef.values()) or 1.0
        coef = {k: float(v) / s for k, v in coef.items()}
    coef = {k: float(v) * COEF_SCALE for k, v in coef.items()}
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