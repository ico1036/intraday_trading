Looking at this iteration, I want to thread the leaderboard's winning pattern (n≈6, year-stable, DD-disciplined, dedup, Neumann-series cov inverse) but I'll explicitly bake in the gross-exposure scaling that prior attempts (iter 1, 39) seem to have whiffed on.

**Method cited:** Tikhonov-regularized **Neumann-series cov inverse** (truncated von Neumann series for `Σ⁻¹`, with the step size set via power-iteration estimate of `λ_max(Σ)` — same matrix-free regularizer used by Trefethen & Bau for iterative inverses) feeding a tangency portfolio on **IC-sign-aligned** members. Selection layer: drawdown gate (max IS DD < 22%), **per-year IS-Sharpe stability** filter (Bailey & Lopez de Prado 2014 — robustness via temporal sub-sample agreement), correlation dedup at ρ=0.85 keyed by IS Sharpe, top-6 cut. Coefficients post-scaled to mean gross ≈ 0.72 to escape the anemic-return zone the runner's row-L1 cap creates.

**Why this is fresh:** prior iter 1 used `top60`, prior iter 39 used `top6` but apparently crashed before metrics. This explicitly bounds N to 6 from a **year-stable + DD-gated** pool (regime-resilience first, then optimization), unlike iter 1 which optimized over a 60-wide pool that diluted member weight.

```python COMPOSITE_FILE
"""Neumann-series Tikhonov-regularized tangency on per-year-stable, DD-gated, IC-sign-aligned, ρ-dedup top-6 alphas (Trefethen-Bau iterative inverse + Bailey/Lopez de Prado regime-stability)."""
from __future__ import annotations
import argparse, math
import numpy as np
import pandas as pd
import scipy.linalg as sla

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

COMPOSITE_ID = "auto_042"
COMPOSITION_NOTE = "neumann_k5_tangency_top6_yearstable_dd22_dedup085_gross072"
RUN_ID = "run_2026_05_c"

GROSS_TARGET = 0.72          # post-normalize scale (mean row L1 target)
DEDUP_RHO = 0.85
DD_CAP = 0.22
TOP_PRE_DEDUP = 30
N_FINAL = 6
NEUMANN_K = 5


def _max_drawdown(eq: pd.Series) -> float:
    s = eq.fillna(0.0)
    cum = (1.0 + s).cumprod()
    peak = cum.cummax()
    dd = (cum / peak - 1.0).min()
    if not np.isfinite(dd):
        return 1.0
    return float(abs(dd))


def _year_stable(R: pd.DataFrame, min_years: int = 2) -> list[str]:
    idx = R.index
    if not isinstance(idx, pd.DatetimeIndex):
        try:
            idx = pd.to_datetime(idx)
        except Exception:
            return list(R.columns)
    years = sorted(set(idx.year.tolist()))
    if len(years) < min_years:
        return list(R.columns)
    kept = []
    for col in R.columns:
        ser = R[col]
        ok = True
        pos_count = 0
        for y in years:
            mask = (idx.year == y)
            sub = ser[mask].dropna()
            if len(sub) < 20:
                continue
            sd = sub.std()
            if sd <= 0 or not np.isfinite(sd):
                ok = False; break
            sh = float(sub.mean() / sd) * math.sqrt(252.0)
            if sh > 0:
                pos_count += 1
            else:
                ok = False; break
        if ok and pos_count >= min_years:
            kept.append(col)
    return kept


def _safe_pool() -> list[str]:
    try:
        pool = select_is_submittable(RUN_ID)
    except Exception:
        pool = []
    if not pool or len(pool) < N_FINAL * 2:
        try:
            pool = select_all_alphas(RUN_ID)
        except Exception:
            pool = pool or []
    return list(pool)


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    pool = _safe_pool()
    if len(pool) < N_FINAL:
        return pool

    signs = member_signs_ic(RUN_ID, pool)
    R = load_member_is_returns(RUN_ID, pool, signs=signs)
    if R is None or R.shape[1] < N_FINAL or R.shape[0] < 60:
        return list(pool[:N_FINAL])

    # column hygiene
    good = []
    for c in R.columns:
        s = R[c].dropna()
        if len(s) < 60:
            continue
        sd = s.std()
        if not np.isfinite(sd) or sd <= 0:
            continue
        good.append(c)
    if len(good) < N_FINAL:
        return list(R.columns[:N_FINAL])
    R = R[good]

    # DD gate (relax if too aggressive)
    dd_ok = [c for c in R.columns if _max_drawdown(R[c]) < DD_CAP]
    if len(dd_ok) >= max(N_FINAL * 2, 12):
        R = R[dd_ok]

    # per-year IS stability
    stable = _year_stable(R, min_years=2)
    if len(stable) >= max(N_FINAL * 2, 12):
        R = R[stable]

    # IS Sharpe ranking
    mu = R.mean()
    sd = R.std()
    sharpe = (mu / sd) * math.sqrt(252.0)
    sharpe = sharpe.replace([np.inf, -np.inf], np.nan).dropna()
    sharpe = sharpe[sharpe > 0.0]
    if len(sharpe) < N_FINAL:
        # fall back to plain top-N from full R
        full_mu = R.mean(); full_sd = R.std()
        full_sh = (full_mu / full_sd) * math.sqrt(252.0)
        full_sh = full_sh.replace([np.inf, -np.inf], np.nan).dropna()
        return list(full_sh.sort_values(ascending=False).head(N_FINAL).index)

    top_ids = sharpe.sort_values(ascending=False).head(min(TOP_PRE_DEDUP, len(sharpe))).index.tolist()
    R_top = R[top_ids]
    keep_metric = {a: float(sharpe[a]) for a in top_ids}

    try:
        kept = correlation_dedup(R_top, threshold=DEDUP_RHO, keep_metric=keep_metric)
    except Exception:
        kept = top_ids

    kept = [k for k in kept if k in keep_metric]
    kept_sorted = sorted(kept, key=lambda x: -keep_metric.get(x, 0.0))
    final = kept_sorted[:N_FINAL]
    if len(final) < 2:
        final = list(sharpe.sort_values(ascending=False).head(N_FINAL).index)
    return final


def _neumann_inverse(M: np.ndarray, K: int) -> np.ndarray:
    n = M.shape[0]
    # power iteration for λ_max(M)
    v = np.random.default_rng(0).standard_normal(n)
    v = v / max(np.linalg.norm(v), 1e-12)
    lam = float(np.trace(M)) / max(n, 1)
    for _ in range(60):
        w = M @ v
        nw = np.linalg.norm(w)
        if nw <= 1e-15 or not np.isfinite(nw):
            break
        v = w / nw
        lam = float(v @ (M @ v))
    if lam <= 0 or not np.isfinite(lam):
        lam = float(np.trace(M)) / max(n, 1)
        if lam <= 0:
            lam = 1.0
    alpha = 1.0 / (1.10 * lam)         # contraction guarantee
    A = np.eye(n) - alpha * M
    inv = np.zeros_like(M)
    term = np.eye(n)
    for _ in range(K + 1):
        inv = inv + term
        term = term @ A
    return alpha * inv


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    if not member_ids:
        return {}
    if len(member_ids) < 2:
        only = member_ids[0]
        return {only: GROSS_TARGET}

    signs = member_signs_ic(RUN_ID, member_ids)
    R = load_member_is_returns(RUN_ID, member_ids, signs=signs)
    if R is None or R.shape[1] < 2 or R.shape[0] < 30:
        equal = GROSS_TARGET / len(member_ids)
        out = {m: equal for m in member_ids}
        return apply_signs(out, signs) if signs else out

    cols = [c for c in member_ids if c in R.columns]
    if len(cols) < 2:
        equal = GROSS_TARGET / len(member_ids)
        return apply_signs({m: equal for m in member_ids}, signs)
    R = R[cols].dropna(how="any")
    if R.shape[0] < 30:
        equal = GROSS_TARGET / len(member_ids)
        return apply_signs({m: equal for m in member_ids}, signs)

    mu = R.mean().values * 252.0
    cov = np.cov(R.values, rowvar=False) * 252.0
    n = cov.shape[0]
    trace_per_n = float(np.trace(cov)) / max(n, 1)
    if not np.isfinite(trace_per_n) or trace_per_n <= 0:
        trace_per_n = 1.0
    # Tikhonov ridge for PSD safety
    cov_reg = cov + 1e-3 * trace_per_n * np.eye(n)

    try:
        inv = _neumann_inverse(cov_reg, K=NEUMANN_K)
        w_raw = inv @ mu
        if not np.all(np.isfinite(w_raw)):
            raise ValueError("non-finite Neumann weights")
    except Exception:
        try:
            inv = sla.pinvh(cov_reg)
            w_raw = inv @ mu
        except Exception:
            w_raw = np.ones(n)

    # if tangency went negative-dominant (degenerate), fall back to inverse-vol
    if np.sum(np.maximum(w_raw, 0.0)) < 1e-9 or not np.all(np.isfinite(w_raw)):
        diag = np.diag(cov_reg)
        diag = np.where(diag > 0, diag, 1.0)
        w_raw = 1.0 / np.sqrt(diag)

    w_dict_signed = {c: float(w_raw[i]) for i, c in enumerate(cols)}
    for m in member_ids:
        w_dict_signed.setdefault(m, 0.0)

    # back to raw-alpha basis
    w_dict_raw = apply_signs(w_dict_signed, signs)

    # numerical hygiene
    w_dict_raw = {k: (v if np.isfinite(v) else 0.0) for k, v in w_dict_raw.items()}
    total_abs = sum(abs(v) for v in w_dict_raw.values())
    if total_abs <= 1e-12:
        equal = GROSS_TARGET / len(member_ids)
        return apply_signs({m: equal for m in member_ids}, signs)

    w_dict_raw = normalize_coefficients(w_dict_raw, "l1")
    w_dict_raw = {k: float(v) * GROSS_TARGET for k, v in w_dict_raw.items()}
    return w_dict_raw


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
