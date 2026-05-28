Looking at this iteration, I need to:

**Reasoning**: Attempts 1-14 covered Neumann/NCO/HERC/B-L/DRP/MaxDiv/CVaR/Kelly/HRP/James-Stein/CSCV-bootstrap/middle-quintile/stability-IR/bootstrap-ERC. The dominant failure has been selection bias (IS≈1.3 → OS≈0.2) rather than weighting method. Two failed iters (auto_001, auto_004) errored inside `normalize_coefficients` — likely passed an ndarray instead of a dict, so I'll be strict about dict types.

**Fresh territory**: **PBO-filtered (Bailey-Borwein-Lopez de Prado-Zhu 2014) selection + Risk Budgeting via Spinu 2013 cyclical coordinate descent with information-driven budgets**. None of these together appear in the tried list. The intuition:

1. *Selection* — for each candidate, split its IS return curve into K=5 equal time chunks and compute Sharpe in each. A genuine signal has positive Sharpe in most chunks; an overfit alpha has one big lucky chunk dragging the others. Use the fraction of chunks with positive Sharpe as a per-alpha consistency score — a cheap PBO proxy that does NOT rank by global IS Sharpe.
2. *Weighting* — Roncalli/Spinu risk budgeting where budgets are proportional to the consistency score (not equal as in ERC, not Sharpe-tilted as in tangency). High-consistency alphas get more risk; the Spinu closed-form quadratic per-coordinate update is stable on LW-shrunk Σ and avoids matrix inversion entirely.
3. *Concentration* — 20 members after correlation dedup at ρ=0.85, then row-L1 scale to gross_target=0.65 to land mean row L1 ≈ 0.55-0.7 (in the [0.30, 0.90] band).
4. *Signs* — `member_signs_ic` BEFORE loading R, so the cov and consistency score reflect deployable-sign returns.

Citations: Bailey, Borwein, Lopez de Prado, Zhu (2014) "Pseudo-Mathematics and Financial Charlatanism" (PBO/CSCV motivation) + Spinu (2013) "An Algorithm for Computing Risk Parity Portfolios" + Roncalli (2013) "Introduction to Risk Parity and Budgeting".

```python COMPOSITE_FILE
"""PBO-consistency-screened risk budgeting (Bailey-Lopez de Prado 2014 + Spinu/Roncalli 2013): per-alpha chunk-Sharpe consistency replaces IS-Sharpe ranking; Spinu cyclical solver allocates risk in proportion to consistency."""
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
    shrink_cov,
    select_is_submittable,
    select_all_alphas,
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_015"
COMPOSITION_NOTE = "pbo_chunk_consistency_spinu_risk_budget_top20_ic_signs_g065"

RUN_ID = "run_2026_05_c"
GROSS_TARGET = 0.65
N_SELECT = 20
N_CHUNKS = 5
DEDUP_THRESHOLD = 0.85
CONSISTENCY_FLOOR = 0.6   # ≥3/5 chunks with positive Sharpe
LW_SHRINK = 0.15


def _chunk_consistency(R: pd.DataFrame, n_chunks: int = 5) -> dict[str, float]:
    """Fraction of equal-time-chunks where each alpha has positive Sharpe. Cheap PBO proxy."""
    if R is None or R.shape[0] < n_chunks * 5 or R.shape[1] == 0:
        if R is None or R.shape[1] == 0:
            return {}
        means = R.mean(axis=0).fillna(0.0)
        return {c: float(1.0 if means[c] > 0 else 0.0) for c in R.columns}
    T = R.shape[0]
    bounds = np.linspace(0, T, n_chunks + 1, dtype=int)
    pieces = []
    for k in range(n_chunks):
        sub = R.iloc[bounds[k]:bounds[k + 1]]
        m = sub.mean(axis=0)
        s = sub.std(axis=0)
        s = s.where(s > 1e-12, np.nan)
        sh = (m / s).fillna(0.0)
        pieces.append(sh)
    chunk_df = pd.concat(pieces, axis=1)  # N x n_chunks
    score = (chunk_df > 0.0).sum(axis=1).astype(float) / float(n_chunks)
    return {str(idx): float(v) for idx, v in score.items()}


def _safe_load(ids: list[str]):
    signs = member_signs_ic(RUN_ID, ids, dead_band=0.005)
    if not isinstance(signs, dict):
        signs = {a: 1 for a in ids}
    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    if R is not None:
        R = R.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return signs, R


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    try:
        pool = select_is_submittable(RUN_ID)
    except Exception:
        pool = []
    if not pool or len(pool) < 5:
        try:
            pool = select_all_alphas(RUN_ID)
        except Exception:
            pool = list(alpha_index["alpha_id"].astype(str).unique()) if "alpha_id" in alpha_index.columns else []
    if not pool:
        return []

    signs, R = _safe_load(pool)
    if R is None or R.shape[1] < 5 or R.shape[0] < N_CHUNKS * 5:
        return pool[: max(2, min(N_SELECT, len(pool)))]

    scores = _chunk_consistency(R, n_chunks=N_CHUNKS)
    consistent = [a for a, s in scores.items() if s >= CONSISTENCY_FLOOR]
    if len(consistent) < 5:
        consistent = sorted(scores.keys(), key=lambda a: scores.get(a, 0.0), reverse=True)
        consistent = consistent[: max(40, len(consistent) // 2)]

    # Correlation dedup, keeping by consistency score (tiebreak by global Sharpe)
    R_c = R[[c for c in consistent if c in R.columns]]
    if R_c.shape[1] >= 2:
        m = R_c.mean(axis=0)
        sd = R_c.std(axis=0).replace(0, np.nan)
        global_sh = (m / sd).fillna(0.0)
        keep_metric = {a: scores.get(a, 0.0) + 0.01 * float(global_sh.get(a, 0.0)) for a in R_c.columns}
        try:
            kept = correlation_dedup(R_c, threshold=DEDUP_THRESHOLD, keep_metric=keep_metric)
        except Exception:
            kept = list(R_c.columns)
    else:
        kept = list(R_c.columns)

    if len(kept) < 2:
        kept = sorted(scores.keys(), key=lambda a: scores.get(a, 0.0), reverse=True)[:N_SELECT]

    # Rank survivors by (consistency, global Sharpe) and take top N
    m = R.mean(axis=0)
    sd = R.std(axis=0).replace(0, np.nan)
    global_sh = (m / sd).fillna(0.0).to_dict()
    kept_sorted = sorted(
        kept,
        key=lambda a: (scores.get(a, 0.0), float(global_sh.get(a, 0.0))),
        reverse=True,
    )
    selected = kept_sorted[:N_SELECT]
    if len(selected) < 2:
        selected = kept_sorted[:2] if len(kept_sorted) >= 2 else pool[:2]
    return selected


def _spinu_risk_budget(Sigma: np.ndarray, budgets: np.ndarray,
                       max_iter: int = 800, tol: float = 1e-10) -> np.ndarray:
    """Spinu 2013 cyclical coordinate descent for the long-only risk-budgeting portfolio."""
    n = Sigma.shape[0]
    w = budgets.copy().astype(float)
    w = np.maximum(w, 1e-6)
    w = w / w.sum()
    for _ in range(max_iter):
        w_old = w.copy()
        for i in range(n):
            sii = float(Sigma[i, i])
            if sii <= 0.0 or not np.isfinite(sii):
                continue
            off = float(np.dot(Sigma[i], w) - sii * w[i])
            disc = off * off + 4.0 * sii * float(budgets[i])
            if disc < 0.0 or not np.isfinite(disc):
                continue
            w[i] = (-off + math.sqrt(disc)) / (2.0 * sii)
        w = np.clip(w, 1e-12, None)
        ssum = w.sum()
        if ssum <= 0 or not np.isfinite(ssum):
            return budgets / max(budgets.sum(), 1e-12)
        w = w / ssum
        if np.linalg.norm(w - w_old, 1) < tol:
            break
    return w


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    if not member_ids:
        return {}

    signs, R = _safe_load(member_ids)
    if not isinstance(signs, dict):
        signs = {a: 1 for a in member_ids}

    if R is None or R.shape[1] < 2:
        eq = {a: 1.0 / float(len(member_ids)) for a in member_ids}
        eq = normalize_coefficients(eq, "l1")
        eq = apply_signs(eq, signs)
        return {a: float(v) * GROSS_TARGET for a, v in eq.items()} | {
            a: 0.0 for a in member_ids if a not in eq
        }

    ids = list(R.columns)
    scores = _chunk_consistency(R, n_chunks=N_CHUNKS)
    score_arr = np.array([max(scores.get(a, 0.0), 0.05) for a in ids], dtype=float)
    if score_arr.sum() <= 0 or not np.isfinite(score_arr.sum()):
        score_arr = np.ones_like(score_arr)
    budgets = score_arr / score_arr.sum()

    # Ledoit-Wolf-style shrunk covariance via helper, fallback to ridged sample
    try:
        Sigma = np.asarray(shrink_cov(R, shrinkage=LW_SHRINK), dtype=float)
        if Sigma.shape != (len(ids), len(ids)):
            raise ValueError("shrink_cov shape mismatch")
    except Exception:
        Sigma = np.cov(R.values, rowvar=False)
        Sigma = Sigma + 1e-6 * np.eye(Sigma.shape[0])

    Sigma = 0.5 * (Sigma + Sigma.T)
    Sigma = Sigma + 1e-8 * np.eye(Sigma.shape[0])
    if np.any(~np.isfinite(Sigma)):
        Sigma = np.eye(len(ids))

    try:
        w = _spinu_risk_budget(Sigma, budgets, max_iter=800, tol=1e-10)
    except Exception:
        w = budgets.copy()
    if np.any(~np.isfinite(w)) or w.sum() <= 0:
        w = budgets.copy()

    coef_dict: dict[str, float] = {a: float(w[i]) for i, a in enumerate(ids)}
    coef_dict = normalize_coefficients(coef_dict, "l1")     # Σ|c| = 1
    coef_dict = apply_signs(coef_dict, signs)                # signed coefficients
    coef_dict = {a: float(v) * GROSS_TARGET for a, v in coef_dict.items()}

    # Ensure every requested member id appears (those dropped during load → 0)
    for m in member_ids:
        if m not in coef_dict:
            coef_dict[m] = 0.0
    return coef_dict


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
