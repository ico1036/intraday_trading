"""Greedy Gram-Schmidt residual-Sharpe composite (matching pursuit, cov-free).

Mechanism (Mallat & Zhang 1993 matching pursuit / greedy orthogonal
forward selection): iteratively add the candidate alpha that maximizes
residual Sharpe after OLS-projecting onto the span of already-selected
members. This selects for *marginal* information rather than raw IS
Sharpe, and bypasses the 1/sigma weighting trap that crushes
tangency/min-variance composites (mean row L1 ~ 0.05 in prior attempts).

Pre-filters: IC-aligned signs, per-year IS stability (positive mean
return in every IS calendar year), max IS drawdown < 25%, correlation
dedup at rho=0.85. Final n<=8 members; coefficients proportional to
each member's residual Sharpe at inclusion time, then L1-normalized and
scaled 10x to target mean row L1 ~ 0.5-0.7 within the [0.30, 0.90] gross
budget (Lopez de Prado MLAM Ch. 16; Choueifaty diversification spirit
preserved by orthogonalization).
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

COMPOSITE_ID = "auto_058_gram_schmidt_resid_sharpe_yearstable_dd2"
COMPOSITION_NOTE = "gram_schmidt_resid_sharpe_yearstable_dd25_n8_gross_x10"

RUN_ID = "run_2026_05_c"
N_MAX = 8
RESID_SHARPE_FLOOR = 0.30
DEDUP_RHO = 0.85
MAX_DD_THRESHOLD = 0.25
GROSS_SCALE = 10.0  # multiply L1-normalized coefs to escape 1/sigma trap


def _ann_sharpe(r: np.ndarray) -> float:
    r = r[np.isfinite(r)]
    if r.size < 5:
        return -np.inf
    sd = float(r.std(ddof=1))
    if sd <= 1e-12:
        return -np.inf
    return float(r.mean() / sd * math.sqrt(252.0))


def _max_dd(r: np.ndarray) -> float:
    r = r[np.isfinite(r)]
    if r.size < 5:
        return 1.0
    eq = np.cumprod(1.0 + r)
    cm = np.maximum.accumulate(eq)
    dd = (eq - cm) / np.where(cm > 0, cm, 1.0)
    return float(-dd.min())


def _per_year_positive(R: pd.DataFrame) -> list[str]:
    years = R.index.year
    uy = sorted({int(y) for y in years})
    if len(uy) < 2:
        return list(R.columns)
    keep: list[str] = []
    for col in R.columns:
        ok = True
        for y in uy:
            mask = (years == y)
            seg = R[col].values[mask]
            seg = seg[np.isfinite(seg)]
            if seg.size < 20:
                continue
            if float(seg.mean()) <= 0.0:
                ok = False
                break
        if ok:
            keep.append(col)
    return keep


def _dd_keep(R: pd.DataFrame, threshold: float) -> list[str]:
    keep: list[str] = []
    for col in R.columns:
        if _max_dd(R[col].values) < threshold:
            keep.append(col)
    return keep


def _gram_schmidt_select(R: pd.DataFrame, sharpes: dict[str, float]) -> list[tuple[str, float]]:
    cols = list(R.columns)
    if not cols:
        return []
    cols.sort(key=lambda c: sharpes.get(c, -np.inf), reverse=True)
    first = cols[0]
    selected: list[tuple[str, float]] = [(first, max(float(sharpes.get(first, 1.0)), 1e-3))]
    while len(selected) < N_MAX:
        sel_ids = [s[0] for s in selected]
        X = R[sel_ids].values
        best_id = None
        best_sh = -np.inf
        for c in cols:
            if c in sel_ids:
                continue
            y = R[c].values
            mask = np.isfinite(y) & np.all(np.isfinite(X), axis=1)
            if int(mask.sum()) < 20:
                continue
            Xm = X[mask]
            ym = y[mask]
            try:
                beta, *_ = np.linalg.lstsq(Xm, ym, rcond=None)
            except np.linalg.LinAlgError:
                continue
            resid = ym - Xm @ beta
            sh = _ann_sharpe(resid)
            if sh > best_sh:
                best_sh = sh
                best_id = c
        if best_id is None or best_sh < RESID_SHARPE_FLOOR:
            break
        selected.append((best_id, max(float(best_sh), 1e-3)))
    return selected


def _load_pool() -> list[str]:
    try:
        ids = list(select_is_submittable(RUN_ID))
    except Exception:
        ids = []
    if len(ids) < 4:
        try:
            ids = list(select_all_alphas(RUN_ID))
        except Exception:
            pass
    return ids


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    ids = _load_pool()
    if len(ids) < 2 and "alpha_id" in alpha_index.columns:
        ids = list(alpha_index["alpha_id"])
    if len(ids) < 2:
        return ids
    signs = member_signs_ic(RUN_ID, ids)
    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    R = R.dropna(axis=1, how="all")
    if R.shape[1] < 2:
        return list(R.columns)[:2] if R.shape[1] else ids[:2]
    sharpes = {c: _ann_sharpe(R[c].values) for c in R.columns}
    # Year stability
    stable = _per_year_positive(R)
    R1 = R[stable] if len(stable) >= 4 else R
    # Drawdown discipline
    ddk = _dd_keep(R1, MAX_DD_THRESHOLD)
    R2 = R1[ddk] if len(ddk) >= 4 else R1
    # Correlation dedup
    keep_metric = {c: float(sharpes.get(c, 0.0)) for c in R2.columns}
    try:
        deduped = list(correlation_dedup(R2, DEDUP_RHO, keep_metric=keep_metric))
    except Exception:
        deduped = list(R2.columns)
    if len(deduped) < 2:
        ranked = sorted(R.columns, key=lambda k: sharpes.get(k, -np.inf), reverse=True)
        return ranked[: max(4, N_MAX)]
    R3 = R2[deduped]
    selected = _gram_schmidt_select(R3, sharpes)
    if len(selected) < 2:
        ranked = sorted(R.columns, key=lambda k: sharpes.get(k, -np.inf), reverse=True)
        return ranked[: max(4, N_MAX)]
    return [s[0] for s in selected]


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    if not member_ids:
        return {}
    signs = member_signs_ic(RUN_ID, member_ids)
    R = load_member_is_returns(RUN_ID, member_ids, signs=signs)
    R = R.reindex(columns=member_ids).dropna(axis=1, how="all")
    cols = list(R.columns)
    if not cols:
        n = len(member_ids)
        return {m: 1.0 / n for m in member_ids}
    # Replay Gram-Schmidt amplitudes in the order they were selected.
    sharpes = {c: _ann_sharpe(R[c].values) for c in cols}
    cols_sorted = sorted(cols, key=lambda c: sharpes.get(c, -np.inf), reverse=True)
    resid_sh: dict[str, float] = {}
    resid_sh[cols_sorted[0]] = max(float(sharpes.get(cols_sorted[0], 1.0)), 1e-3)
    for k in range(1, len(cols_sorted)):
        prior = cols_sorted[:k]
        X = R[prior].values
        y = R[cols_sorted[k]].values
        mask = np.isfinite(y) & np.all(np.isfinite(X), axis=1)
        if int(mask.sum()) < 20:
            resid_sh[cols_sorted[k]] = 1e-3
            continue
        Xm = X[mask]
        ym = y[mask]
        try:
            beta, *_ = np.linalg.lstsq(Xm, ym, rcond=None)
            resid = ym - Xm @ beta
            sh = _ann_sharpe(resid)
        except np.linalg.LinAlgError:
            sh = 1e-3
        if not np.isfinite(sh):
            sh = 1e-3
        resid_sh[cols_sorted[k]] = max(float(sh), 1e-3)
    raw: dict[str, float] = {c: float(resid_sh[c]) for c in cols_sorted}
    # Ensure every requested member has a coefficient (zero-vol or missing
    # IS returns get the mean amplitude so the runner does not crash).
    mean_amp = float(np.mean(list(raw.values()))) if raw else 1.0
    for m in member_ids:
        raw.setdefault(m, mean_amp)
    # L1-normalize to dict-keyed unit sum, then scale to escape the
    # 1/sigma weighting ceiling identified in prior attempts.
    try:
        coef = normalize_coefficients(raw, "l1")
    except Exception:
        s = sum(abs(v) for v in raw.values()) or 1.0
        coef = {k: v / s for k, v in raw.items()}
    coef = {k: float(v) * GROSS_SCALE for k, v in coef.items()}
    # Deploy via raw (un-signed) weight panels: bake IC-aligned signs in.
    try:
        coef = apply_signs(coef, signs)
    except Exception:
        coef = {k: float(signs.get(k, 1)) * float(v) for k, v in coef.items()}
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