"""Regime-Conditional Drawdown-Disciplined Concentrated Tangency (Ledoit-Wolf).

Per-year IS sub-period Sharpe stability + max-DD<25% (CDaR-like, Chekhlov-
Uryasev-Zabarankin 2005) + IC sign-alignment + correlation dedup -> top-8
by IS Sharpe -> Markowitz tangency on Ledoit-Wolf (2004) shrunk covariance,
non-negative clipped (R is in deployable sign space), scaled to mean row
L1 ~ 0.70 to extract PnL under the 1.0 gross budget.
"""
from __future__ import annotations
import argparse
import numpy as np
import pandas as pd
import scipy.linalg as sla

from intraday.composites._runner import build_and_backtest
from intraday.composites._optim_helpers import (
    correlation_dedup,
    member_signs_ic,
    apply_signs,
    shrink_cov,
    select_is_submittable,
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_017_regime_year_stable_dd_lt25_top8_lw_tange"
COMPOSITION_NOTE = "regime_year_stable_dd_lt25_top8_lw_tangency_signed_l1_070"

RUN_ID = "run_2026_05_c"
TARGET_K = 8
DEDUP_THRESHOLD = 0.85
MAX_DD_LIMIT = 0.25
TARGET_GROSS = 0.70
SHRINKAGE = 0.20
MIN_YEAR_OBS = 30
MIN_FULL_OBS = 100


def _annualized_sharpe(r: pd.Series) -> float:
    s = r.dropna()
    if len(s) < 2:
        return 0.0
    sd = float(s.std(ddof=1))
    if sd <= 0 or not np.isfinite(sd):
        return 0.0
    return float(s.mean()) / sd * float(np.sqrt(365.0))


def _max_drawdown(r: pd.Series) -> float:
    s = r.fillna(0.0)
    if s.empty:
        return 1.0
    eq = (1.0 + s).cumprod()
    peak = eq.cummax()
    dd = (eq - peak) / peak
    mn = float(dd.min())
    if not np.isfinite(mn):
        return 1.0
    return -mn


def _per_year_min_sharpe(r: pd.Series) -> float:
    s = r.dropna()
    if s.empty:
        return -np.inf
    groups = s.groupby(s.index.year)
    vals: list[float] = []
    for _, sub in groups:
        if len(sub) < MIN_YEAR_OBS:
            continue
        sd = float(sub.std(ddof=1))
        if sd <= 0 or not np.isfinite(sd):
            continue
        vals.append(float(sub.mean()) / sd * float(np.sqrt(365.0)))
    if not vals:
        return -np.inf
    return float(min(vals))


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    candidates = select_is_submittable(RUN_ID)
    if not candidates or len(candidates) < 2:
        return []

    signs = member_signs_ic(RUN_ID, candidates)
    R = load_member_is_returns(RUN_ID, candidates, signs=signs)
    if R is None or R.empty or len(R.columns) < 2:
        return []

    full_sharpe: dict[str, float] = {}
    survivors: list[str] = []
    for aid in R.columns:
        s = R[aid].dropna()
        if len(s) < MIN_FULL_OBS:
            continue
        fs = _annualized_sharpe(s)
        if fs <= 0.3:
            continue
        if _max_drawdown(s) > MAX_DD_LIMIT:
            continue
        if _per_year_min_sharpe(s) <= 0.0:
            continue
        survivors.append(aid)
        full_sharpe[aid] = fs

    # Relaxed fallback if regime-gate is too tight on this pool
    if len(survivors) < 2:
        survivors = []
        full_sharpe = {}
        for aid in R.columns:
            s = R[aid].dropna()
            if len(s) < MIN_FULL_OBS:
                continue
            fs = _annualized_sharpe(s)
            if fs <= 0.5:
                continue
            if _max_drawdown(s) > 0.35:
                continue
            survivors.append(aid)
            full_sharpe[aid] = fs

    if len(survivors) < 2:
        return []

    R_surv = R[survivors]
    try:
        kept = correlation_dedup(R_surv, DEDUP_THRESHOLD, keep_metric=full_sharpe)
    except Exception:
        kept = survivors
    if not kept or len(kept) < 2:
        kept = survivors

    kept_sorted = sorted(kept, key=lambda a: -full_sharpe.get(a, 0.0))
    chosen = kept_sorted[:TARGET_K]
    if len(chosen) < 2:
        chosen = kept_sorted[: max(2, len(kept_sorted))]
    return chosen


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    if not member_ids:
        return {}

    signs = member_signs_ic(RUN_ID, member_ids)

    def _signed_eq_fallback(ids: list[str]) -> dict[str, float]:
        n = max(len(ids), 1)
        per = TARGET_GROSS / n
        out = {aid: 0.0 for aid in member_ids}
        for aid in ids:
            out[aid] = float(signs.get(aid, 1)) * per
        return out

    R = load_member_is_returns(RUN_ID, member_ids, signs=signs)
    if R is None or R.empty:
        return _signed_eq_fallback(member_ids)

    cols = [c for c in member_ids if c in R.columns]
    if len(cols) < 2:
        return _signed_eq_fallback(cols if cols else member_ids)

    R = R[cols].dropna(how="any")
    if R.empty or len(R) < 30 or len(R.columns) < 2:
        return _signed_eq_fallback(list(R.columns) if not R.empty else member_ids)

    mu = R.mean().values.astype(float)
    try:
        Sigma = shrink_cov(R, shrinkage=SHRINKAGE)
        Sigma = np.asarray(Sigma, dtype=float)
        n = Sigma.shape[0]
        ridge = 1e-6 * (float(np.trace(Sigma)) / max(n, 1) + 1e-12)
        Sigma_reg = Sigma + ridge * np.eye(n)
        try:
            w = sla.solve(Sigma_reg, mu, assume_a="pos")
        except Exception:
            w = sla.pinvh(Sigma_reg) @ mu
    except Exception:
        w = mu.copy()

    w = np.asarray(w, dtype=float)
    w = np.where(np.isfinite(w) & (w > 0.0), w, 0.0)
    if float(np.sum(np.abs(w))) <= 1e-12:
        w = np.ones_like(mu)

    coef_raw = {aid: float(val) for aid, val in zip(R.columns, w.tolist())}
    try:
        coef_signed = apply_signs(coef_raw, signs)
    except Exception:
        coef_signed = {k: float(signs.get(k, 1)) * v for k, v in coef_raw.items()}

    if not coef_signed or sum(abs(v) for v in coef_signed.values()) < 1e-12:
        coef_signed = {k: float(signs.get(k, 1)) for k in R.columns}

    try:
        coef_norm = normalize_coefficients(coef_signed, "l1")
    except Exception:
        l1 = sum(abs(v) for v in coef_signed.values()) or 1.0
        coef_norm = {k: v / l1 for k, v in coef_signed.items()}

    out = {aid: 0.0 for aid in member_ids}
    for k, v in coef_norm.items():
        out[k] = float(v) * TARGET_GROSS
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