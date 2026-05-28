"""Concentrated Omega-ratio portfolio (Keating & Shadwick 2002) with per-year regime-stability gate and max-drawdown (CDaR-inspired) discipline."""
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

COMPOSITE_ID = "auto_029_omega_keating_shadwick_yearstable_cdar_t"
COMPOSITION_NOTE = "omega_keating_shadwick_yearstable_cdar_top6_concentrated_gross070"
RUN_ID = "run_2026_05_c"

TARGET_GROSS = 0.70
TARGET_N = 6
DEDUP_RHO = 0.80
OMEGA_THRESHOLD = 0.0


def _omega_ratio(r: np.ndarray, threshold: float = 0.0) -> float:
    if r.size == 0:
        return 0.0
    gains = float(np.maximum(r - threshold, 0.0).mean())
    losses = float(np.maximum(threshold - r, 0.0).mean())
    if losses <= 1e-12:
        return 1e6 if gains > 0 else 0.0
    return gains / losses


def _max_drawdown(r: np.ndarray) -> float:
    if r.size == 0:
        return 0.0
    eq = np.cumsum(r)
    peak = np.maximum.accumulate(eq)
    dd = peak - eq
    return float(dd.max())


def _yearstable_positive(R: pd.DataFrame) -> list[str]:
    try:
        idx = pd.to_datetime(R.index)
    except Exception:
        return list(R.columns)
    years = sorted(set(idx.year.tolist()))
    keep: list[str] = []
    for col in R.columns:
        s = R[col].dropna()
        if s.empty:
            continue
        s_dt = pd.Series(s.values, index=pd.to_datetime(s.index))
        ok = True
        seen = 0
        for y in years:
            chunk = s_dt[s_dt.index.year == y]
            if chunk.size < 20:
                continue
            seen += 1
            mu = float(chunk.mean())
            sd = float(chunk.std(ddof=0))
            if sd <= 1e-12 or mu <= 0.0:
                ok = False
                break
        if ok and seen >= 1:
            keep.append(col)
    return keep


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    candidates = select_is_submittable(RUN_ID)
    if not candidates or len(candidates) < 12:
        try:
            candidates = select_all_alphas(RUN_ID)
        except Exception:
            pass
    if not candidates:
        return []

    signs = member_signs_ic(RUN_ID, candidates)
    R = load_member_is_returns(RUN_ID, candidates, signs=signs)
    if R is None or R.shape[1] < 4:
        if R is None:
            return candidates[:TARGET_N]
        return list(R.columns)[:TARGET_N]

    # 1) Regime stability gate — positive Sharpe in every calendar year
    stable = _yearstable_positive(R)
    if len(stable) < max(8, 2 * TARGET_N):
        stable = list(R.columns)
    Rs = R[stable]

    # 2) Drawdown discipline — keep lower-half by max IS drawdown (CDaR-style)
    dd_vals = {c: _max_drawdown(Rs[c].fillna(0.0).to_numpy()) for c in Rs.columns}
    if len(dd_vals) > 2 * TARGET_N:
        sorted_by_dd = sorted(dd_vals, key=lambda c: dd_vals[c])
        cutoff = max(2 * TARGET_N, len(sorted_by_dd) // 2)
        Rs = Rs[sorted_by_dd[:cutoff]]

    # 3) Omega ratio ranking (Keating & Shadwick 2002)
    omegas = {
        c: _omega_ratio(Rs[c].fillna(0.0).to_numpy(), OMEGA_THRESHOLD)
        for c in Rs.columns
    }
    omegas = {c: (v if np.isfinite(v) else 0.0) for c, v in omegas.items()}

    # 4) Correlation dedup at 0.80, keep by Omega
    short = sorted(omegas, key=lambda c: omegas[c], reverse=True)[: min(30, len(omegas))]
    try:
        kept = correlation_dedup(Rs[short], threshold=DEDUP_RHO, keep_metric=omegas)
    except Exception:
        kept = short

    # 5) Concentrate to top-N
    kept = sorted(kept, key=lambda c: omegas.get(c, 0.0), reverse=True)[:TARGET_N]
    if len(kept) < 2:
        kept = sorted(omegas, key=lambda c: omegas[c], reverse=True)[: max(4, TARGET_N)]
    return kept


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    signs = member_signs_ic(RUN_ID, member_ids)

    if not member_ids:
        return {}

    R = load_member_is_returns(RUN_ID, member_ids, signs=signs)
    if R is None or R.empty:
        eq = {m: 1.0 / float(len(member_ids)) for m in member_ids}
        eq = normalize_coefficients(eq, "l1")
        eq = {k: v * TARGET_GROSS for k, v in eq.items()}
        return apply_signs(eq, signs)

    cols = [c for c in member_ids if c in R.columns]
    if not cols:
        eq = {m: 1.0 / float(len(member_ids)) for m in member_ids}
        eq = normalize_coefficients(eq, "l1")
        eq = {k: v * TARGET_GROSS for k, v in eq.items()}
        return apply_signs(eq, signs)

    Rm = R[cols].fillna(0.0)

    # Omega tilt: weight by upside-over-baseline (Ω − 1)⁺
    omegas = np.array(
        [_omega_ratio(Rm[c].to_numpy(), OMEGA_THRESHOLD) for c in cols], dtype=float
    )
    omegas = np.where(np.isfinite(omegas), omegas, 0.0)
    tilt = np.clip(omegas - 1.0, 0.0, None)
    if tilt.sum() <= 1e-12:
        tilt = np.where(omegas > 0.0, omegas, 1.0)

    # Inverse-variance risk budgeting (diagonal-only, no matrix inversion)
    var = Rm.var(ddof=0).to_numpy()
    inv_var = 1.0 / np.where(var > 1e-12, var, 1e-12)

    raw = tilt * inv_var
    if raw.sum() <= 1e-12:
        raw = np.ones_like(raw)
    raw = raw / raw.sum()

    coef = {c: float(raw[i]) for i, c in enumerate(cols)}
    for m in member_ids:
        coef.setdefault(m, 0.0)

    coef = normalize_coefficients(coef, "l1")
    coef = {k: v * TARGET_GROSS for k, v in coef.items()}
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