Looking at this iteration 19, my reasoning before the code:

**Idea family chosen:** Online portfolio selection via **Hedge / Exponentiated-Gradient (Freund-Schapire 1997; Helmbold-Schapire-Singer-Warmuth 1998)**. This is in the "Online portfolio (FTRL/ONS)" menu category but specifically not on the tried list (auto_001…018 covered Neumann, NCO, HERC, BL, DRP, max-div, CVaR, Kelly, HRP, JS, CSCV, antibias, stability-IR, ERC, PBO/Spinu, PC1, regime-year, semivariance).

**Mechanism:** Hedge gives the optimal *regret* bound over any constant-rebalanced portfolio in hindsight. Coefficient `c_a ∝ exp(η · cum_return_a)`. This concentrates *automatically* on the alphas that won the IS path, with concentration controlled by η.

**Regime-aware angle (the dominant failure mode per prior attempts):**
1. Drawdown filter (max IS DD < 30%) — eliminates tail-event survivors.
2. Per-year Sharpe stability (positive in 2022, 2023, 2024) — keeps only alphas robust across LUNA collapse → 2023 chop → 2024 ETF rally.
3. Macro-residualization against the equal-weighted cross-sectional alpha mean — subtracts the dominant common factor so we score on the alpha-specific signal, not common-factor luck. Distinct from auto_016 (PC1) because the equal-weighted mean is a market-portfolio proxy, not an eigenvector-of-Σ.
4. Concentrated top-10 by *residual* Sharpe + correlation dedup at 0.85.
5. Hedge / EG softmax on cumulative residual returns with η=1.5 (moderate concentration; top alpha ≈ 7-20× the bottom of the kept 10).
6. Final gross = 0.75 × L1-normalized → mean row L1 in target window.

Defensive coding: every helper has an "if filter kills everything, keep prior R" fallback; `normalize_coefficients` is called on a dict (the iter-004 trap).

```python COMPOSITE_FILE
"""Hedge / Exponentiated-Gradient online combination (Freund-Schapire 1997 ‘A
decision-theoretic generalization of on-line learning’; Helmbold-Schapire-Singer-
Warmuth 1998 ‘On-Line Portfolio Selection Using Multiplicative Updates’) over
macro-residualized, per-year-stable, drawdown-disciplined alphas. Concentrate via
softmax on cumulative IS residual returns; top-K dedup at |ρ|>0.85; gross 0.75."""
from __future__ import annotations
import argparse
import numpy as np
import pandas as pd

from intraday.composites._runner import build_and_backtest
from intraday.composites._optim_helpers import (
    correlation_dedup,
    member_signs_ic,
    select_is_submittable,
    select_all_alphas,
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_019"
COMPOSITION_NOTE = "hedge_eg_macro_resid_yearstable_dd30_top10_gross075"

RUN_ID = "run_2026_05_c"
TARGET_GROSS = 0.75
TOP_K = 10
DD_TOL = 0.30
DEDUP_RHO = 0.85
EG_ETA = 1.5


def _max_drawdown(returns: pd.Series) -> float:
    r = returns.fillna(0.0).astype(float)
    eq = (1.0 + r).cumprod()
    if len(eq) == 0:
        return 0.0
    peak = eq.cummax()
    dd = (eq / peak) - 1.0
    return float(dd.min())


def _per_year_stable(R: pd.DataFrame, min_per_year: int = 25) -> list[str]:
    try:
        idx = pd.to_datetime(R.index)
    except Exception:
        return list(R.columns)
    years = sorted(set(int(y) for y in idx.year))
    if len(years) < 2:
        return list(R.columns)
    keep = []
    for col in R.columns:
        ok = True
        for y in years:
            mask = (idx.year == y)
            sub = R[col].values[mask]
            if len(sub) < min_per_year:
                continue
            mu = float(np.mean(sub))
            sd = float(np.std(sub, ddof=0))
            if sd <= 0 or (mu / sd) <= 0:
                ok = False
                break
        if ok:
            keep.append(col)
    return keep


def _drawdown_filter(R: pd.DataFrame, max_dd_tol: float = DD_TOL) -> list[str]:
    return [c for c in R.columns if _max_drawdown(R[c]) > -max_dd_tol]


def _macro_residualize(R: pd.DataFrame) -> pd.DataFrame:
    """Subtract beta * equal-weighted cross-sectional mean from each column."""
    if R.shape[1] < 2:
        return R.copy()
    m = R.mean(axis=1).astype(float)
    m_c = m - m.mean()
    mvar = float((m_c.values ** 2).mean())
    if mvar <= 1e-14:
        return R.copy()
    out = pd.DataFrame(index=R.index, columns=R.columns, dtype=float)
    mvals = m.values
    mcvals = m_c.values
    for c in R.columns:
        x = R[c].values.astype(float)
        beta = float(np.mean((x - x.mean()) * mcvals) / mvar)
        out[c] = x - beta * mvals
    return out


def _hedge_eg_softmax(R: pd.DataFrame, eta: float = EG_ETA) -> pd.Series:
    """Hedge / EG closed form on cumulative path: w_i ∝ exp(eta * z_cum_i)."""
    cum = R.sum(axis=0).values.astype(float)
    if len(cum) == 0:
        return pd.Series(dtype=float)
    sd_cum = float(np.std(cum))
    if sd_cum <= 1e-9:
        sd_cum = 1.0
    z = (cum - float(np.mean(cum))) / sd_cum
    z = np.clip(z, -3.0, 3.0)
    e = np.exp(eta * z)
    if (not np.isfinite(e).all()) or (e.sum() <= 0):
        e = np.ones_like(e)
    w = e / e.sum()
    return pd.Series(w, index=R.columns)


def _load_pool() -> pd.DataFrame:
    ids = select_is_submittable(RUN_ID)
    if not ids or len(ids) < 4:
        ids = select_all_alphas(RUN_ID)
    if not ids:
        return pd.DataFrame()
    try:
        signs = member_signs_ic(RUN_ID, ids)
    except Exception:
        signs = {a: 1 for a in ids}
    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    if R is None or R.empty:
        return pd.DataFrame()
    R = R.dropna(axis=1, how="all").fillna(0.0)
    R = R.loc[:, (R.std(axis=0, ddof=0) > 1e-12)]
    return R


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    R = _load_pool()
    if R.empty:
        return []
    if R.shape[1] <= 4:
        return list(R.columns)

    dd_keep = _drawdown_filter(R, max_dd_tol=DD_TOL)
    if len(dd_keep) >= 8:
        R = R[dd_keep]

    ys_keep = _per_year_stable(R, min_per_year=25)
    if len(ys_keep) >= 8:
        R = R[ys_keep]

    Rres = _macro_residualize(R)

    mu = Rres.mean(axis=0)
    sd = Rres.std(axis=0, ddof=0).replace(0.0, np.nan)
    sharpe = (mu / sd).dropna()
    sharpe = sharpe[sharpe > 0.0].sort_values(ascending=False)
    if sharpe.empty:
        raw_mu = R.mean(axis=0)
        raw_sd = R.std(axis=0, ddof=0).replace(0.0, np.nan)
        sharpe = (raw_mu / raw_sd).dropna().sort_values(ascending=False)
    if sharpe.empty:
        cols = list(R.columns)
        return cols[: min(8, len(cols))]

    cols_sorted = list(sharpe.index)
    try:
        dedup = correlation_dedup(
            Rres[cols_sorted] if set(cols_sorted).issubset(set(Rres.columns)) else R[cols_sorted],
            threshold=DEDUP_RHO,
            keep_metric=sharpe.to_dict(),
        )
    except Exception:
        dedup = cols_sorted

    if not dedup:
        dedup = cols_sorted

    dedup_set = set(dedup)
    ranked = [a for a in cols_sorted if a in dedup_set]
    K = min(TOP_K, len(ranked))
    if K < 2:
        return cols_sorted[: max(2, min(8, len(cols_sorted)))]
    return ranked[:K]


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    if not member_ids:
        return {}
    n = len(member_ids)
    if n == 1:
        return {member_ids[0]: TARGET_GROSS}

    try:
        signs = member_signs_ic(RUN_ID, member_ids)
    except Exception:
        signs = {a: 1 for a in member_ids}

    R = load_member_is_returns(RUN_ID, member_ids, signs=signs)
    if R is None or R.empty:
        return {a: TARGET_GROSS / n for a in member_ids}
    R = R.dropna(axis=1, how="all").fillna(0.0)
    R = R.loc[:, (R.std(axis=0, ddof=0) > 1e-12)]
    if R.shape[1] == 0:
        return {a: TARGET_GROSS / n for a in member_ids}

    Rres = _macro_residualize(R)
    eg = _hedge_eg_softmax(Rres, eta=EG_ETA)

    raw: dict[str, float] = {}
    fallback_share = 1.0 / float(n)
    for a in member_ids:
        v = float(eg.get(a, 0.0)) if a in eg.index else 0.0
        if v <= 0.0 or not np.isfinite(v):
            v = 1e-6 * fallback_share
        raw[a] = v

    total = sum(abs(v) for v in raw.values())
    if total <= 0.0 or not np.isfinite(total):
        return {a: TARGET_GROSS / n for a in member_ids}

    try:
        c = normalize_coefficients(raw, "l1")
    except Exception:
        s = sum(abs(v) for v in raw.values()) or 1.0
        c = {a: v / s for a, v in raw.items()}

    out = {a: float(v) * TARGET_GROSS for a, v in c.items()}
    for a in member_ids:
        if a not in out:
            out[a] = 0.0
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
```
