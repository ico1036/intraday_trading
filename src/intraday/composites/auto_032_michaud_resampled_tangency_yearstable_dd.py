"""Michaud (1998) resampled efficient frontier tangency on year-stable, drawdown<25%
top-8 alphas with IC-aligned signs and LW-shrunk pseudo-inverse per bootstrap —
addresses tangency estimation error under IS->OS regime change via bootstrap
aggregation (Michaud & Michaud 2008, 'Estimation Error and Portfolio Optimization')."""
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
    select_all_alphas,
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_032_michaud_resampled_tangency_yearstable_dd"
COMPOSITION_NOTE = "michaud_resampled_tangency_yearstable_dd25_top8_signic_gross070"

RUN_ID = "run_2026_05_c"
TARGET_GROSS = 0.70
BOOTSTRAP_B = 200
BOOTSTRAP_SEED = 11
TOP_K_FINAL = 8
DEDUP_RHO = 0.80
DD_LIMIT = 0.25
LW_SHRINK = 0.20


def _max_drawdown(s: pd.Series) -> float:
    eq = (1.0 + s.fillna(0.0)).cumprod()
    peak = eq.cummax()
    dd = (eq / peak - 1.0).min()
    return float(abs(dd)) if np.isfinite(dd) else 1.0


def _year_stable(R: pd.DataFrame, min_pos_years: int = 2) -> list[str]:
    """Keep alphas with positive annualized Sharpe in every IS year that has
    >=10 obs. Falls back gracefully if the index is not datetime."""
    R = R.copy()
    try:
        R.index = pd.to_datetime(R.index)
    except Exception:
        return list(R.columns)
    if not isinstance(R.index, pd.DatetimeIndex):
        return list(R.columns)
    years = sorted({int(y) for y in R.index.year.unique()})
    if len(years) < 2:
        return list(R.columns)
    kept: list[str] = []
    for col in R.columns:
        s = R[col].dropna()
        if s.empty:
            continue
        n_pos = 0
        any_neg = False
        for y in years:
            sy = s[s.index.year == y]
            if len(sy) < 10:
                continue
            mu = sy.mean()
            sd = sy.std()
            if not np.isfinite(mu) or not np.isfinite(sd) or sd <= 1e-12:
                continue
            shp = mu / sd * np.sqrt(252.0)
            if shp > 0.0:
                n_pos += 1
            else:
                any_neg = True
                break
        if (not any_neg) and n_pos >= min_pos_years:
            kept.append(col)
    return kept


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    ids_all = select_all_alphas(RUN_ID)
    if len(ids_all) < 4:
        return ids_all
    signs = member_signs_ic(RUN_ID, ids_all)
    R = load_member_is_returns(RUN_ID, ids_all, signs=signs)
    cols = list(R.columns)
    if len(cols) < 4:
        return cols

    # Annualized IS Sharpe in sign-aligned space.
    mu = R.mean(axis=0)
    sd = R.std(axis=0).replace(0, np.nan)
    sharpe = (mu / sd * np.sqrt(252.0)).dropna()
    sharpe = sharpe[sharpe > 0.0]
    if sharpe.empty:
        # Pathological: fall back to raw top-K from alpha_index if present.
        return cols[:max(2, min(TOP_K_FINAL, len(cols)))]

    # Drawdown discipline.
    dd_map = {c: _max_drawdown(R[c]) for c in sharpe.index}
    keep_dd = [c for c, d in dd_map.items() if d < DD_LIMIT]
    if len(keep_dd) < 12:
        keep_dd = [c for c, d in dd_map.items() if d < 0.32]
    if len(keep_dd) < 8:
        keep_dd = list(sharpe.index)

    # Year-stable regime filter.
    R_dd = R[keep_dd]
    keep_ys = _year_stable(R_dd, min_pos_years=2)
    if len(keep_ys) < 8:
        keep_ys = keep_dd

    # Rank by sign-aligned IS Sharpe and prune to a working pool.
    pool = [c for c in keep_ys if c in sharpe.index]
    pool.sort(key=lambda c: -float(sharpe[c]))
    pool = pool[:30]
    if len(pool) < 2:
        return cols[:max(2, min(TOP_K_FINAL, len(cols)))]

    # Correlation dedup to enforce complementarity.
    R_pool = R[pool]
    metric = {c: float(sharpe[c]) for c in pool}
    try:
        kept = correlation_dedup(R_pool, threshold=DEDUP_RHO, keep_metric=metric)
    except Exception:
        kept = pool

    kept.sort(key=lambda c: -float(sharpe[c]))
    out = kept[:TOP_K_FINAL] if len(kept) >= TOP_K_FINAL else kept
    if len(out) < 2:
        out = pool[:max(2, min(TOP_K_FINAL, len(pool)))]
    return out


def _michaud_resampled_weights(R: pd.DataFrame) -> np.ndarray:
    """Bootstrap B times: resample rows with replacement, compute LW-shrunk
    covariance, solve tangency w ∝ Σ⁻¹ μ via pseudo-inverse, clip negatives
    (signs already aligned), normalize, average. Michaud-Michaud 2008."""
    T, N = R.shape
    arr = R.fillna(0.0).to_numpy()
    cols = list(R.columns)
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    W = np.zeros(N, dtype=float)
    ok = 0
    for _ in range(BOOTSTRAP_B):
        idx = rng.integers(0, T, size=T)
        sample = arr[idx]
        mu_b = sample.mean(axis=0)
        if not np.all(np.isfinite(mu_b)):
            continue
        try:
            df_b = pd.DataFrame(sample, columns=cols)
            Sigma = shrink_cov(df_b, shrinkage=LW_SHRINK)
        except Exception:
            Sigma = np.cov(sample, rowvar=False)
            Sigma = Sigma + 1e-4 * np.eye(N)
        try:
            inv = sla.pinvh(Sigma + 1e-8 * np.eye(N))
        except Exception:
            continue
        w = inv @ mu_b
        if not np.all(np.isfinite(w)):
            continue
        w = np.clip(w, 0.0, None)
        s = w.sum()
        if s <= 1e-12:
            continue
        W += w / s
        ok += 1
    if ok == 0:
        return np.full(N, 1.0 / N, dtype=float)
    W = W / float(ok)
    s = W.sum()
    if s <= 1e-12 or not np.isfinite(s):
        return np.full(N, 1.0 / N, dtype=float)
    return W / s


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    if len(member_ids) < 2:
        n = max(len(member_ids), 1)
        return {m: TARGET_GROSS / n for m in member_ids}

    signs = member_signs_ic(RUN_ID, member_ids)
    R = load_member_is_returns(RUN_ID, member_ids, signs=signs)
    cols = [c for c in member_ids if c in R.columns]
    if len(cols) < 2:
        n = max(len(member_ids), 1)
        equal = {m: TARGET_GROSS / n for m in member_ids}
        return apply_signs(equal, signs) if signs else equal

    R = R[cols].dropna(how="all").fillna(0.0)
    if R.shape[0] < 30:
        # Too little IS history for bootstrap; equal-weight fallback.
        n = len(cols)
        equal = {c: 1.0 / n for c in cols}
        coef = apply_signs(equal, signs)
        coef = normalize_coefficients(coef, "l1")
        out = {k: v * TARGET_GROSS for k, v in coef.items()}
        for m in member_ids:
            out.setdefault(m, 0.0)
        return out

    w = _michaud_resampled_weights(R)
    aligned_coef = {c: float(v) for c, v in zip(cols, w.tolist())}

    # Re-attach deployed signs (R was IC-flipped; the runner takes raw signs).
    deployed = apply_signs(aligned_coef, signs)

    # Normalize to Σ|c|=1 then scale to target mean gross exposure.
    deployed = normalize_coefficients(deployed, "l1")
    out = {k: float(v) * TARGET_GROSS for k, v in deployed.items()}
    for m in member_ids:
        out.setdefault(m, 0.0)
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