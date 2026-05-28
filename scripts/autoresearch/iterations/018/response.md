Looking at this iteration, I need to pick a fresh idea family. The tried list covers Neumann, NCO, HERC, Black-Litterman, DRP, Max-Div, Mean-CVaR, Fractional Kelly, HRP, James-Stein, CSCV bootstrap, anti-bias, stability-cluster, ERC-bootstrap, PBO-spinu, PC1-residualized, and regime-year-stable. So variance-based, drawdown-based, online-learning, and skewness-based optimizations are still open.

The user emphasized regime shift as the dominant failure mode and asked for concentrated, high-return / high-risk combinations. **Mean-Semi-Variance** (Markowitz 1959, ch. 9; Estrada 2008) directly addresses the downside-asymmetry of regime breaks: the semi-covariance matrix only counts joint downside co-deviations, so the tangency weight `w ∝ SC⁻¹μ⁺` actively penalizes members that co-crash and rewards members whose mean comes from upside without joint downside risk. This is conceptually distinct from variance tangency (auto_001/010/017) and CVaR (auto_007) — CVaR is a tail expectation of *portfolio* loss, semi-variance is a *co-deviation* metric on members.

Pairing this with Sortino-based pre-selection (downside-deviation-normalized return, Sortino-Price 1994) keeps the selection and weighting consistent — both penalize downside variance specifically. Concentrated on top-8 after correlation dedup (matches the empirical n∈[4,12] sweet spot). Tikhonov regularization `(SC + λI)⁻¹` for numerical stability (semi-cov is rank-deficient when T close to N). L1-normalize then scale to mean row L1 = 0.65 to hit the gross-exposure budget the prior anemic-return attempts missed.

```python COMPOSITE_FILE
"""Mean-Semi-Variance tangency (Markowitz 1959 ch.9; Estrada 2008
'Mean-semivariance optimization: a heuristic approach') on Sortino-ranked
(Sortino-Price 1994) concentrated IC-aligned top-8 members. Semi-covariance
uses downside co-deviations only; tangency = (SemiCov + lambda*I)^-1 mu_plus
with Tikhonov regularization and pinvh fallback."""
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
    select_is_submittable,
    select_all_alphas,
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_018"
COMPOSITION_NOTE = "mean_semivariance_tangency_sortino_top8_dedup085_gross065"

RUN_ID = "run_2026_05_c"
N_PRESELECT = 30
DEDUP_RHO = 0.85
N_FINAL = 8
TARGET_MEAN_L1 = 0.65
TIKHONOV_FRAC = 0.5


def _sortino(returns: np.ndarray) -> float:
    if returns.size < 30:
        return -np.inf
    downside = np.minimum(returns, 0.0)
    dd = float(np.sqrt(np.mean(downside ** 2)))
    if dd < 1e-9:
        return -np.inf
    return float(returns.mean()) / dd * float(np.sqrt(252.0))


def _semicov(R: np.ndarray) -> np.ndarray:
    """Semi-covariance: E[(r_i - mu_i)^- * (r_j - mu_j)^-]."""
    mu = R.mean(axis=0, keepdims=True)
    centered = R - mu
    downside = np.minimum(centered, 0.0)
    T = R.shape[0]
    return (downside.T @ downside) / float(max(T - 1, 1))


def _signed_returns(run_id: str, ids: list[str]) -> tuple[pd.DataFrame, dict[str, int]]:
    signs = member_signs_ic(run_id, ids)
    R = load_member_is_returns(run_id, ids, signs=signs)
    R = R.dropna(axis=1, how="all").fillna(0.0)
    return R, signs


def _rank_and_dedup(R: pd.DataFrame) -> list[str]:
    cols = list(R.columns)
    if len(cols) == 0:
        return []
    if len(cols) <= N_FINAL:
        return cols
    sortino = {c: _sortino(R[c].to_numpy()) for c in cols}
    sortino = {a: s for a, s in sortino.items() if np.isfinite(s)}
    if len(sortino) < 2:
        return cols[:N_FINAL]
    pre = sorted(sortino, key=lambda a: sortino[a], reverse=True)[:N_PRESELECT]
    R_pre = R[pre]
    keep_metric = {a: sortino[a] for a in pre}
    try:
        deduped = correlation_dedup(R_pre, threshold=DEDUP_RHO, keep_metric=keep_metric)
    except Exception:
        deduped = pre
    if not deduped:
        deduped = pre
    final = sorted(deduped, key=lambda a: sortino.get(a, -np.inf), reverse=True)[:N_FINAL]
    if len(final) < 2:
        final = pre[:N_FINAL]
    return final


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    ids_all = select_is_submittable(RUN_ID)
    if len(ids_all) < 4:
        ids_all = select_all_alphas(RUN_ID)
    R, _ = _signed_returns(RUN_ID, ids_all)
    final = _rank_and_dedup(R)
    if len(final) < 2:
        final = list(R.columns)[: max(2, N_FINAL)]
    return final


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    R, signs = _signed_returns(RUN_ID, member_ids)
    cols = [a for a in member_ids if a in R.columns]
    if len(cols) < 2:
        coef = {a: 1.0 / float(max(len(member_ids), 1)) for a in member_ids}
        coef = normalize_coefficients(coef, "l1")
        coef = {a: v * TARGET_MEAN_L1 for a, v in coef.items()}
        return apply_signs(coef, signs)

    R_arr = R[cols].to_numpy()
    mu = R_arr.mean(axis=0)
    SC = _semicov(R_arr)
    lam = float(np.trace(SC)) / float(max(len(cols), 1)) * TIKHONOV_FRAC + 1e-8
    SC_reg = SC + lam * np.eye(len(cols))

    mu_pos = np.maximum(mu, 0.0)
    if mu_pos.sum() <= 1e-12:
        mu_pos = np.ones_like(mu)

    try:
        w_raw = sla.solve(SC_reg, mu_pos)
    except Exception:
        w_raw = sla.pinvh(SC_reg) @ mu_pos

    w_raw = np.maximum(w_raw, 0.0)
    if not np.isfinite(w_raw).all() or w_raw.sum() <= 1e-12:
        w_raw = np.ones(len(cols))

    coef = dict(zip(cols, w_raw.tolist()))
    coef = normalize_coefficients(coef, "l1")
    coef = {a: v * TARGET_MEAN_L1 for a, v in coef.items()}
    for a in member_ids:
        coef.setdefault(a, 0.0)
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
```
