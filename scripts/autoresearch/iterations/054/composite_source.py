"""Greedy Gram-Schmidt orthogonal addition by residual Sharpe (Feng, Giglio, Xiu 2020, 'Taming the Factor Zoo', JF). Cov-free composition; year-stability + DD-discipline pre-filter; native gross exposure preserved."""
from __future__ import annotations
import argparse
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

COMPOSITE_ID = "auto_054_greedy_gram_schmidt_residsharpe_yearstab"
COMPOSITION_NOTE = "greedy_gram_schmidt_residsharpe_yearstable_dd20_top8_scale12x"

RUN_ID = "run_2026_05_c"
N_MAX = 8
RESIDUAL_SHARPE_FLOOR = 0.30
DD_MAX = 0.20
DEDUP_RHO = 0.90
SCALE_UP = 12.0  # offsets the systemic 1/sigma underweighting from L1-normalization


def _ann_sharpe(r) -> float:
    a = np.asarray(r, dtype=float)
    a = a[np.isfinite(a)]
    if a.size < 20:
        return -np.inf
    sd = a.std(ddof=1)
    if not np.isfinite(sd) or sd <= 1e-12:
        return -np.inf
    return float(a.mean() / sd * np.sqrt(252.0))


def _max_drawdown_frac(r) -> float:
    a = np.asarray(r, dtype=float)
    a = np.where(np.isfinite(a), a, 0.0)
    if a.size == 0:
        return 1.0
    eq = np.cumsum(a)
    peak = np.maximum.accumulate(eq)
    dd = peak - eq
    return float(dd.max())


def _year_stable(s: pd.Series) -> bool:
    s = s.dropna()
    if s.empty:
        return False
    try:
        idx = pd.DatetimeIndex(s.index)
    except Exception:
        return True
    years = np.asarray(idx.year)
    uniq = np.unique(years)
    if uniq.size < 2:
        return True
    for y in uniq:
        mask = (years == y)
        sub = s.values[mask]
        sh = _ann_sharpe(sub)
        if not np.isfinite(sh) or sh <= 0.0:
            return False
    return True


def _greedy_gs_select(R: pd.DataFrame, n_max: int, floor: float) -> list[str]:
    cols = list(R.columns)
    if not cols:
        return []
    sharpe_map = {c: _ann_sharpe(R[c].values) for c in cols}
    ordered = sorted(cols, key=lambda c: sharpe_map[c], reverse=True)
    if sharpe_map[ordered[0]] <= -np.inf + 1:
        return []
    X = R.fillna(0.0)
    selected = [ordered[0]]
    while len(selected) < n_max:
        Y = X[selected].values
        try:
            YtY_inv = np.linalg.pinv(Y.T @ Y)
        except np.linalg.LinAlgError:
            break
        H = Y @ YtY_inv @ Y.T
        best = None
        best_sh = -np.inf
        for c in ordered:
            if c in selected:
                continue
            v = X[c].values
            resid = v - H @ v
            sh = _ann_sharpe(resid)
            if sh > best_sh:
                best_sh = sh
                best = c
        if best is None or not np.isfinite(best_sh) or best_sh < floor:
            break
        selected.append(best)
    return selected


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    ids = select_is_submittable(RUN_ID)
    if not ids or len(ids) < 5:
        ids = select_all_alphas(RUN_ID)
    if not ids:
        return []
    signs = member_signs_ic(RUN_ID, ids)
    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    if R is None or R.shape[1] < 2:
        return list(R.columns) if R is not None else []

    keep_strict = []
    keep_loose = []
    for col in R.columns:
        s = R[col].dropna()
        if s.empty:
            continue
        if not _year_stable(s):
            continue
        keep_loose.append(col)
        if _max_drawdown_frac(s.values) <= DD_MAX:
            keep_strict.append(col)

    pool = keep_strict if len(keep_strict) >= 4 else (keep_loose if len(keep_loose) >= 2 else list(R.columns))
    R_pool = R[pool].copy()

    sharpe_map = {c: _ann_sharpe(R_pool[c].values) for c in R_pool.columns}
    deduped = correlation_dedup(R_pool, threshold=DEDUP_RHO, keep_metric=sharpe_map)
    if len(deduped) < 2:
        deduped = list(R_pool.columns)
    R_d = R_pool[deduped].copy()

    selected = _greedy_gs_select(R_d, N_MAX, RESIDUAL_SHARPE_FLOOR)
    if len(selected) < 2:
        ranked = sorted(R_d.columns, key=lambda c: _ann_sharpe(R_d[c].values), reverse=True)
        selected = ranked[:max(4, min(N_MAX, len(ranked)))]
    return list(selected)


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    if not member_ids:
        return {}
    signs = member_signs_ic(RUN_ID, member_ids)
    R = load_member_is_returns(RUN_ID, member_ids, signs=signs)
    cols = [c for c in member_ids if (R is not None and c in R.columns)]
    if not cols:
        eq = 1.0 / float(len(member_ids))
        out = {a: eq for a in member_ids}
        out = apply_signs(out, signs)
        out = normalize_coefficients(out, scheme="l1")
        return {k: v * SCALE_UP for k, v in out.items()}

    X = R[cols].fillna(0.0).values
    T, k = X.shape

    raw = {}
    first = cols[0]
    sh0 = _ann_sharpe(X[:, 0])
    raw[first] = float(max(sh0, 0.10))
    for i in range(1, k):
        Y = X[:, :i]
        try:
            YtY_inv = np.linalg.pinv(Y.T @ Y)
            H = Y @ YtY_inv @ Y.T
        except np.linalg.LinAlgError:
            raw[cols[i]] = 0.10
            continue
        v = X[:, i]
        resid = v - H @ v
        sh = _ann_sharpe(resid)
        if not np.isfinite(sh):
            sh = 0.10
        raw[cols[i]] = float(max(sh, 0.10))

    for a in member_ids:
        raw.setdefault(a, 0.10)

    raw = apply_signs(raw, signs)
    raw = normalize_coefficients(raw, scheme="l1")
    out = {k_: float(v) * SCALE_UP for k_, v in raw.items()}
    return out


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